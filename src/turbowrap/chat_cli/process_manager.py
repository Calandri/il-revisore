"""
CLI Process Manager - Gestisce processi claude/gemini CLI.

Permette di:
- Spawning di processi CLI con configurazione
- Streaming stdout/stderr asincrono
- Gestione lifecycle (start, stop, terminate)
- Tracking processi attivi

Usage:
    manager = CLIProcessManager()

    proc = await manager.spawn_claude(
        session_id="abc123",
        working_dir=Path("/path/to/repo"),
        model="claude-opus-4-5-20251101",
        agent_path=Path("/path/to/agent.md"),  # Optional
        thinking_budget=10000,  # Optional
    )

    async for chunk in manager.send_message("abc123", "Hello"):
        print(chunk, end="")

    await manager.terminate("abc123")
"""

import asyncio
import codecs
import json
import logging
import os
import tempfile
import uuid
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from ..utils.async_utils import asyncio_timeout
from ..utils.env_utils import build_env_with_api_keys
from ..utils.file_utils import validate_working_dir
from .models import CLIType, SessionStatus

logger = logging.getLogger(__name__)

# Timeouts
DEFAULT_TIMEOUT = 120  # 2 minutes
CLAUDE_TIMEOUT = 900  # 15 minutes (for complex tasks)
GEMINI_TIMEOUT = 120  # 2 minutes

STALE_PROCESS_HOURS = 3  # Kill processes older than 3 hours
CLEANUP_INTERVAL_SECONDS = 300  # Check every 5 minutes


# Type alias for process stats entry
class ProcessStatsEntry:
    """Type for process stats entry."""

    session_id: str
    cli_type: str
    pid: int | None
    status: str
    age_hours: float
    model: str


@dataclass
class CLIProcess:
    """Represents a running CLI process."""

    session_id: str
    cli_type: CLIType
    process: asyncio.subprocess.Process | None
    working_dir: Path
    model: str
    agent_name: str | None = None
    started_at: datetime = field(default_factory=datetime.utcnow)
    status: SessionStatus = SessionStatus.RUNNING
    temp_prompt_file: Path | None = None  # Temp file for combined context+agent
    claude_session_id: str | None = None  # Claude CLI's session ID for --resume
    thinking_budget: int | None = None
    mcp_config: Path | None = None
    gemini_context: str | None = None  # Context to prepend to first message
    context_used: bool = False  # Whether context has been prepended
    message_history_callback: Callable[[], str] | None = None  # Callback to load history from DB

    @property
    def pid(self) -> int | None:
        """Get process ID."""
        return self.process.pid if self.process else None

    @property
    def is_running(self) -> bool:
        """Check if process is still running."""
        return self.process is not None and self.process.returncode is None

    def cleanup(self) -> None:
        """Cleanup temporary files."""
        if self.temp_prompt_file and self.temp_prompt_file.exists():
            try:
                self.temp_prompt_file.unlink()
                logger.debug(f"Cleaned up temp file: {self.temp_prompt_file}")
            except Exception as e:
                logger.warning(f"Failed to cleanup temp file: {e}")


class CLIProcessManager:
    """Manages multiple CLI processes in parallel.

    Thread-safe management of Claude and Gemini CLI subprocesses
    with streaming output and lifecycle management.
    """

    def __init__(self, max_processes: int = 10):
        """Initialize manager.

        Args:
            max_processes: Maximum concurrent processes allowed
        """
        self._processes: dict[str, CLIProcess] = {}
        self._lock = asyncio.Lock()
        self._max_processes = max_processes
        self._shared_resume_ids: dict[str, str] = {}

    def set_shared_resume_id(self, session_id: str, claude_session_id: str) -> None:
        """Store a shared claude_session_id for a forked session.

        When a session is forked, the forked session can share the
        claude_session_id to use --resume and access the conversation history.

        Args:
            session_id: The forked session ID
            claude_session_id: The original session's claude_session_id
        """
        self._shared_resume_ids[session_id] = claude_session_id
        logger.info(f"[FORK] Stored shared resume ID for {session_id}: {claude_session_id}")

    def get_shared_resume_id(self, session_id: str) -> str | None:
        """Get and consume a shared resume ID for a session.

        Args:
            session_id: Session to check for shared resume ID

        Returns:
            claude_session_id if available, None otherwise
        """
        return self._shared_resume_ids.pop(session_id, None)

    async def spawn_claude(
        self,
        session_id: str,
        working_dir: Path,
        model: str = "claude-opus-4-5-20251101",
        agent_path: Path | None = None,
        thinking_budget: int | None = None,
        mcp_config: Path | None = None,
        context: str | None = None,
        existing_session_id: str | None = None,
        message_history_callback: Callable[[], str] | None = None,
    ) -> CLIProcess:
        """Spawn a new Claude CLI process.

        Args:
            session_id: Unique session identifier
            working_dir: Working directory for CLI
            model: Claude model to use
            agent_path: Path to agent markdown file for --system-prompt-file
            thinking_budget: Extended thinking token budget (None = disabled)
            mcp_config: Path to MCP config JSON file

        Returns:
            CLIProcess instance

        Raises:
            RuntimeError: If max processes reached or session already exists
            SecurityError: If working directory is outside allowed paths
        """
        validated_working_dir = validate_working_dir(working_dir)

        async with self._lock:
            if session_id in self._processes:
                raise RuntimeError(f"Session {session_id} already exists")

            if len(self._processes) >= self._max_processes:
                raise RuntimeError(f"Max processes ({self._max_processes}) reached")

        # Build environment with API keys from config
        env = build_env_with_api_keys()
        env["TMPDIR"] = "/tmp"  # Workaround for Bun file watcher bug
        env["PYTHONUNBUFFERED"] = "1"  # Disable Python buffering
        env["NODE_OPTIONS"] = "--no-warnings"  # Less noise from node

        # Set thinking budget if enabled
        if thinking_budget:
            env["MAX_THINKING_TOKENS"] = str(thinking_budget)
            logger.info(f"[CLAUDE] Extended thinking: {thinking_budget} tokens")

        # Determine claude_session_id and whether to use --resume
        # Priority: 1) existing_session_id (from DB), 2) shared_resume_id (fork), 3) new UUID
        shared_resume_id = self.get_shared_resume_id(session_id)
        use_resume = False

        if existing_session_id:
            # Resuming existing session from database
            claude_session_id = existing_session_id
            use_resume = True
            logger.info(f"[CLAUDE] Resuming existing session: {claude_session_id}")
        elif shared_resume_id:
            # Forked session - share parent's context
            claude_session_id = shared_resume_id
            use_resume = True
            logger.info(f"[CLAUDE] Using shared resume ID: {claude_session_id}")
        else:
            # Brand new session
            claude_session_id = str(uuid.uuid4())
            logger.info(f"[CLAUDE] New session ID: {claude_session_id}")

        # Build CLI arguments
        args: list[str] = [
            "claude",
            "--print",
        ]

        if use_resume:
            args.extend(["--resume", claude_session_id])
        else:
            args.extend(["--session-id", claude_session_id])

        args.extend(
            [
                "--verbose",
                "--dangerously-skip-permissions",
                "--model",
                model,
                "--output-format",
                "stream-json",
                "--include-partial-messages",  # Enable real-time streaming of chunks
            ]
        )

        # Create system prompt file combining context and agent
        temp_prompt_file = None
        system_prompt_parts = []

        if context:
            system_prompt_parts.append(context)
            logger.info(f"[CLAUDE] Context added: {len(context)} chars")

        if agent_path and agent_path.exists():
            agent_content = agent_path.read_text()
            system_prompt_parts.append(f"\n\n---\n\n# Agent Instructions\n\n{agent_content}")
            logger.info(f"[CLAUDE] Using agent: {agent_path.stem}")

        # Create temp file if we have any system prompt content
        if system_prompt_parts:
            combined_prompt = "\n".join(system_prompt_parts)
            # Create temp file that persists until explicitly deleted
            fd, temp_path = tempfile.mkstemp(suffix=".md", prefix="turbowrap_prompt_")
            temp_prompt_file = Path(temp_path)
            with os.fdopen(fd, "w") as f:
                f.write(combined_prompt)
            args.extend(["--system-prompt-file", str(temp_prompt_file)])
            logger.info(
                f"[CLAUDE] System prompt file: {temp_prompt_file} ({len(combined_prompt)} chars)"
            )

        if mcp_config and mcp_config.exists():
            args.extend(["--mcp-config", str(mcp_config)])
            logger.info(f"[CLAUDE] MCP config: {mcp_config}")

        # Create subprocess (not started yet - will start on first message)
        process = await asyncio.create_subprocess_exec(
            *args,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(validated_working_dir),
            env=env,
        )

        if process.stdout:
            process.stdout._limit = 1024 * 1024  # type: ignore[attr-defined]

        cli_proc = CLIProcess(
            session_id=session_id,
            cli_type=CLIType.CLAUDE,
            process=process,
            working_dir=validated_working_dir,
            model=model,
            agent_name=agent_path.stem if agent_path else None,
            status=SessionStatus.RUNNING,
            temp_prompt_file=temp_prompt_file,
            claude_session_id=claude_session_id,
            thinking_budget=thinking_budget,
            mcp_config=mcp_config,
            message_history_callback=message_history_callback,
        )

        async with self._lock:
            self._processes[session_id] = cli_proc

        logger.info(
            f"[CLAUDE] Spawned process PID={process.pid} for session {session_id} "
            f"(claude_session={claude_session_id})"
        )
        return cli_proc

    async def spawn_gemini(
        self,
        session_id: str,
        working_dir: Path,
        model: str = "gemini-3-pro-preview",
        reasoning: bool = False,
        context: str | None = None,
    ) -> CLIProcess:
        """Spawn a new Gemini CLI process.

        Args:
            session_id: Unique session identifier
            working_dir: Working directory for CLI
            model: Gemini model to use
            reasoning: Enable deep reasoning mode
            context: Context to prepend to first message (Gemini doesn't have system-prompt-file)

        Returns:
            CLIProcess instance

        Note:
            Gemini CLI doesn't support stdin input like Claude.
            Each message spawns a new process with prompt as argument.
            Context is stored and prepended to the first message.

        Raises:
            SecurityError: If working directory is outside allowed paths
        """
        validated_working_dir = validate_working_dir(working_dir)

        async with self._lock:
            if session_id in self._processes:
                raise RuntimeError(f"Session {session_id} already exists")

            if len(self._processes) >= self._max_processes:
                raise RuntimeError(f"Max processes ({self._max_processes}) reached")

        # Create a placeholder process (Gemini starts fresh per message)
        # Note: Environment with API keys is built in _send_gemini_message
        cli_proc = CLIProcess(
            session_id=session_id,
            cli_type=CLIType.GEMINI,
            process=None,  # Will be set on first message
            working_dir=validated_working_dir,
            model=model,
            agent_name=None,  # Gemini doesn't support custom agents
            status=SessionStatus.IDLE,
        )

        if context:
            cli_proc.gemini_context = context
            cli_proc.context_used = False
            logger.info(
                f"[GEMINI] Context stored: {len(context)} chars (will prepend to first msg)"
            )

        async with self._lock:
            self._processes[session_id] = cli_proc

        logger.info(f"[GEMINI] Session {session_id} created (process spawns per message)")
        return cli_proc

    async def _respawn_claude_with_resume(
        self, proc: CLIProcess, force_new_session: bool = False
    ) -> None:
        """Respawn Claude process with --resume to continue conversation.

        When a Claude process ends (after processing a message), this method
        spawns a new process that resumes the same conversation using
        Claude CLI's --resume flag.

        Args:
            proc: The CLIProcess to respawn
            force_new_session: If True, create a new session instead of resuming
        """
        # Build environment with API keys from config
        env = build_env_with_api_keys()
        env["TMPDIR"] = "/tmp"
        env["PYTHONUNBUFFERED"] = "1"
        env["NODE_OPTIONS"] = "--no-warnings"

        if proc.thinking_budget:
            env["MAX_THINKING_TOKENS"] = str(proc.thinking_budget)

        # Build args - use --resume or --session-id depending on force_new_session
        args = [
            "claude",
            "--print",
        ]

        # Track if we need to inject history (only for fresh sessions after failed resume)
        recovery_prompt_file: Path | None = None

        if force_new_session or not proc.claude_session_id:
            # Create a fresh session
            new_session_id = str(uuid.uuid4())
            args.extend(["--session-id", new_session_id])
            proc.claude_session_id = new_session_id
            logger.info(f"[CLAUDE] Creating fresh session: {new_session_id}")

            # If we have a history callback and this is a recovery (force_new_session=True),
            # load message history from DB and inject as system prompt
            if force_new_session and proc.message_history_callback:
                try:
                    history = proc.message_history_callback()
                    if history:
                        logger.info(
                            f"[CLAUDE] [RECOVERY] Injecting message history ({len(history)} chars)"
                        )
                        # Create temp file with history as context
                        fd, temp_path = tempfile.mkstemp(suffix=".md", prefix="turbowrap_recovery_")
                        recovery_prompt_file = Path(temp_path)
                        with os.fdopen(fd, "w") as f:
                            f.write(f"""# Previous Conversation History

The following is the conversation history from a previous session that was interrupted.
Continue naturally from where we left off. The user's new message follows this context.

---

{history}

---

""")
                        args.extend(["--system-prompt-file", str(recovery_prompt_file)])
                except Exception as e:
                    logger.error(f"[CLAUDE] Failed to load message history: {e}")
        else:
            args.extend(["--resume", proc.claude_session_id])

        args.extend(
            [
                "--verbose",
                "--dangerously-skip-permissions",
                "--model",
                proc.model,
                "--output-format",
                "stream-json",
                "--include-partial-messages",  # Enable real-time streaming of chunks
            ]
        )

        if proc.mcp_config and proc.mcp_config.exists():
            args.extend(["--mcp-config", str(proc.mcp_config)])

        new_process = await asyncio.create_subprocess_exec(
            *args,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(proc.working_dir),
            env=env,
        )

        if new_process.stdout:
            new_process.stdout._limit = 1024 * 1024  # type: ignore[attr-defined]

        proc.process = new_process
        proc.status = SessionStatus.RUNNING

        logger.debug(
            f"[CLAUDE] Respawned process PID={new_process.pid} "
            f"(claude_session={proc.claude_session_id}, force_new={force_new_session})"
        )

    async def send_message(
        self,
        session_id: str,
        message: str,
        timeout: int | None = None,
    ) -> AsyncIterator[str]:
        """Send message to CLI and stream response.

        Args:
            session_id: Session to send message to
            message: Message content
            timeout: Override default timeout

        Yields:
            Response chunks as they arrive

        Raises:
            RuntimeError: If session not found
        """
        async with self._lock:
            if session_id not in self._processes:
                raise RuntimeError(f"Session {session_id} not found")
            proc = self._processes[session_id]

        if proc.cli_type == CLIType.CLAUDE:
            async for chunk in self._send_claude_message(proc, message, timeout):
                yield chunk
        else:
            async for chunk in self._send_gemini_message(proc, message, timeout):
                yield chunk

    async def _send_claude_message(
        self,
        proc: CLIProcess,
        message: str,
        timeout: int | None = None,
        _retry_with_new_session: bool = False,
    ) -> AsyncIterator[str]:
        """Send message to Claude CLI process.

        Args:
            proc: CLIProcess instance
            message: Message to send
            timeout: Optional timeout override
            _retry_with_new_session: Internal flag for retry logic
        """
        timeout_value = timeout or CLAUDE_TIMEOUT
        process = proc.process

        # Check if process is dead OR stdin is closed (from previous message)
        # After each message stdin is closed (EOF), so we need to respawn for next message
        stdin_unusable = (
            process
            and process.stdin
            and (
                process.stdin.is_closing()
                or getattr(process.stdin, "_transport", None) is None
                or getattr(getattr(process.stdin, "_transport", None), "_closing", False)
                or getattr(
                    getattr(process.stdin, "_transport", None), "is_closing", lambda: False
                )()
            )
        )
        if not process or process.returncode is not None or stdin_unusable:
            logger.debug(
                f"[CLAUDE] Process ended or stdin closed, respawning "
                f"(returncode={process.returncode if process else None}, stdin_unusable={stdin_unusable}, "
                f"force_new_session={_retry_with_new_session})"
            )
            await self._respawn_claude_with_resume(proc, force_new_session=_retry_with_new_session)
            process = proc.process  # Get the new process

        if process is None or process.stdin is None:
            raise RuntimeError("Claude process or stdin is None")

        proc.status = SessionStatus.STREAMING

        prompt_bytes = message.encode()
        try:
            logger.debug(f"[CLAUDE] Writing {len(prompt_bytes)} bytes to stdin")
            process.stdin.write(prompt_bytes)
            await process.stdin.drain()
            process.stdin.close()
            await process.stdin.wait_closed()
            logger.debug("[CLAUDE] Stdin closed (EOF sent)")
        except (ConnectionResetError, RuntimeError) as e:
            # Handle closed transport errors - respawn and retry
            if "handler is closed" in str(e) or isinstance(e, ConnectionResetError):
                logger.debug(f"[CLAUDE] Transport closed ({e}), respawning with --resume")
                await self._respawn_claude_with_resume(proc)
                process = proc.process
                if process is None or process.stdin is None:
                    raise RuntimeError("Failed to respawn Claude process")
                process.stdin.write(prompt_bytes)
                await process.stdin.drain()
                process.stdin.close()
                await process.stdin.wait_closed()
                logger.debug("[CLAUDE] Stdin closed (EOF sent) after respawn")
            else:
                raise
        except Exception as e:
            logger.error(f"[CLAUDE] Stdin error: {e}")
            raise

        if process.stdout is None:
            raise RuntimeError("Claude process stdout is None")

        chunks_yielded = False
        try:
            async with asyncio_timeout(timeout_value):
                while True:
                    line_bytes = await process.stdout.readline()
                    if not line_bytes:
                        break

                    line = line_bytes.decode("utf-8", errors="replace")
                    logger.debug(f"[CLAUDE] Line: {len(line)} chars")

                    if line:
                        chunks_yielded = True
                        yield line

        except asyncio.TimeoutError:
            logger.error(f"[CLAUDE] Timeout after {timeout_value}s")
            process.kill()
            proc.status = SessionStatus.ERROR
            raise

        await process.wait()
        logger.debug(
            f"[CLAUDE] Process exited with code {process.returncode}, chunks_yielded={chunks_yielded}"
        )

        # Always check stderr for useful info (even on success)
        stderr_text = ""
        if process.stderr:
            stderr_content = await process.stderr.read()
            if stderr_content:
                stderr_text = stderr_content.decode("utf-8", errors="replace")
                if process.returncode == 0:
                    logger.debug(f"[CLAUDE] Stderr (success): {stderr_text[:500]}")
                else:
                    logger.error(f"[CLAUDE] Stderr (error): {stderr_text}")

        if process.returncode != 0:
            # Check if this is a "session not found" error and we haven't retried yet
            if (
                "No conversation found with session ID" in stderr_text
                and not _retry_with_new_session
            ):
                logger.warning(
                    f"[CLAUDE] Session not found in Claude CLI (chunks_yielded={chunks_yielded}), "
                    "clearing invalid session and retrying with fresh session"
                )
                # Clear the invalid claude_session_id so we don't try to resume again
                proc.claude_session_id = None
                async for chunk in self._send_claude_message(
                    proc, message, timeout, _retry_with_new_session=True
                ):
                    yield chunk
                return  # Don't set error status, we recovered

            proc.status = SessionStatus.ERROR
            # Yield error to frontend
            error_event = {
                "type": "error",
                "error": {
                    "type": "cli_error",
                    "message": stderr_text or "Claude CLI process failed unexpectedly",
                },
            }
            yield json.dumps(error_event) + "\n"
        else:
            proc.status = SessionStatus.COMPLETED

    async def _send_gemini_message(
        self,
        proc: CLIProcess,
        message: str,
        timeout: int | None = None,
    ) -> AsyncIterator[str]:
        """Send message to Gemini CLI (spawns new process per message)."""
        timeout_value = timeout or GEMINI_TIMEOUT
        proc.status = SessionStatus.STREAMING

        # Build environment with API keys from config
        env = build_env_with_api_keys()

        full_message = message
        if proc.gemini_context and not proc.context_used:
            context = proc.gemini_context
            full_message = f"""<context>
{context}
</context>

---

{message}"""
            proc.context_used = True
            logger.info(f"[GEMINI] Context prepended to message ({len(context)} chars)")

        args = [
            "gemini",
            "-m",
            proc.model,
            "--yolo",
            full_message,
        ]

        process = await asyncio.create_subprocess_exec(
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(proc.working_dir),
            env=env,
        )

        if process.stdout:
            process.stdout._limit = 1024 * 1024  # type: ignore[attr-defined]

        # Update proc reference
        proc.process = process
        logger.info(f"[GEMINI] Spawned process PID={process.pid}")

        if process.stdout is None:
            raise RuntimeError("Gemini process stdout is None")

        decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")

        try:
            async with asyncio_timeout(timeout_value):
                while True:
                    chunk = await process.stdout.read(1024)
                    if not chunk:
                        decoded = decoder.decode(b"", final=True)
                        if decoded:
                            yield decoded
                        break

                    decoded = decoder.decode(chunk)
                    if decoded:
                        yield decoded

        except asyncio.TimeoutError:
            logger.error(f"[GEMINI] Timeout after {timeout_value}s")
            process.kill()
            proc.status = SessionStatus.ERROR
            raise

        await process.wait()
        logger.info(f"[GEMINI] Process exited with code {process.returncode}")

        if process.returncode != 0:
            if process.stderr:
                stderr = await process.stderr.read()
                logger.error(f"[GEMINI] Error: {stderr.decode()}")
            proc.status = SessionStatus.ERROR
        else:
            proc.status = SessionStatus.IDLE  # Ready for next message

    async def terminate(self, session_id: str) -> bool:
        """Terminate a CLI process gracefully.

        Args:
            session_id: Session to terminate

        Returns:
            True if terminated, False if not found
        """
        async with self._lock:
            if session_id not in self._processes:
                return False

            proc = self._processes.pop(session_id)

        if proc.process and proc.process.returncode is None:
            logger.info(f"[{proc.cli_type.value.upper()}] Terminating PID={proc.pid}")
            proc.process.terminate()
            try:
                await asyncio.wait_for(proc.process.wait(), timeout=5)
            except asyncio.TimeoutError:
                logger.warning(f"[{proc.cli_type.value.upper()}] Force killing PID={proc.pid}")
                proc.process.kill()

        proc.cleanup()

        return True

    async def terminate_all(self) -> int:
        """Terminate all active processes.

        Returns:
            Number of processes terminated
        """
        session_ids = list(self._processes.keys())
        count = 0
        for sid in session_ids:
            if await self.terminate(sid):
                count += 1
        return count

    def get_active_sessions(self) -> list[str]:
        """Get list of active session IDs."""
        return list(self._processes.keys())

    def get_process(self, session_id: str) -> CLIProcess | None:
        """Get process info by session ID."""
        return self._processes.get(session_id)

    def get_status(self, session_id: str) -> SessionStatus | None:
        """Get session status."""
        proc = self._processes.get(session_id)
        return proc.status if proc else None

    async def cleanup_stale_processes(self, max_age_hours: float = STALE_PROCESS_HOURS) -> int:
        """Terminate processes that have been running too long.

        Args:
            max_age_hours: Maximum age in hours before killing a process

        Returns:
            Number of processes terminated
        """
        from datetime import timedelta

        now = datetime.utcnow()
        max_age = timedelta(hours=max_age_hours)
        stale_sessions = []

        async with self._lock:
            for session_id, proc in self._processes.items():
                age = now - proc.started_at
                if age > max_age:
                    stale_sessions.append((session_id, proc.pid, age))

        count = 0
        for session_id, pid, age in stale_sessions:
            hours = age.total_seconds() / 3600
            logger.warning(
                f"[CLEANUP] Terminating stale process: session={session_id}, "
                f"PID={pid}, age={hours:.1f}h (max={max_age_hours}h)"
            )
            if await self.terminate(session_id):
                count += 1

        if count > 0:
            logger.info(f"[CLEANUP] Terminated {count} stale processes")

        return count

    def get_process_stats(self) -> dict[str, Any]:
        """Get statistics about running processes.

        Returns:
            Dict with process statistics
        """
        now = datetime.utcnow()
        processes_list: list[dict[str, Any]] = []

        for session_id, proc in self._processes.items():
            age_seconds = (now - proc.started_at).total_seconds()
            processes_list.append(
                {
                    "session_id": session_id,
                    "cli_type": proc.cli_type.value,
                    "pid": proc.pid,
                    "status": proc.status.value,
                    "age_hours": round(age_seconds / 3600, 2),
                    "model": proc.model,
                }
            )

        stats: dict[str, Any] = {
            "total_processes": len(self._processes),
            "max_processes": self._max_processes,
            "processes": processes_list,
        }

        return stats


_manager: CLIProcessManager | None = None


def get_process_manager() -> CLIProcessManager:
    """Get singleton CLIProcessManager instance."""
    global _manager
    if _manager is None:
        _manager = CLIProcessManager()
    return _manager
