"""
CLI Process Manager - Gestisce processi claude/gemini CLI.

Permette di:
- Spawning di processi CLI con configurazione
- Streaming stdout/stderr asincrono
- Gestione lifecycle (start, stop, terminate)
- Tracking processi attivi

Usage:
    manager = CLIProcessManager()

    # Spawn Claude
    proc = await manager.spawn_claude(
        session_id="abc123",
        working_dir=Path("/path/to/repo"),
        model="claude-opus-4-5-20251101",
        agent_path=Path("/path/to/agent.md"),  # Optional
        thinking_budget=10000,  # Optional
    )

    # Send message and stream response
    async for chunk in manager.send_message("abc123", "Hello"):
        print(chunk, end="")

    # Terminate
    await manager.terminate("abc123")
"""

import asyncio
import codecs
import logging
import os
import tempfile
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from .models import CLIType, SessionStatus
from ..config import get_settings
from ..exceptions import SecurityError

logger = logging.getLogger(__name__)

# Timeouts
DEFAULT_TIMEOUT = 120  # 2 minutes
CLAUDE_TIMEOUT = 900  # 15 minutes (for complex tasks)
GEMINI_TIMEOUT = 120  # 2 minutes

# Cleanup settings
STALE_PROCESS_HOURS = 3  # Kill processes older than 3 hours
CLEANUP_INTERVAL_SECONDS = 300  # Check every 5 minutes


@dataclass
class CLIProcess:
    """Represents a running CLI process."""

    session_id: str
    cli_type: CLIType
    process: asyncio.subprocess.Process
    working_dir: Path
    model: str
    agent_name: str | None = None
    started_at: datetime = field(default_factory=datetime.utcnow)
    status: SessionStatus = SessionStatus.RUNNING
    temp_prompt_file: Path | None = None  # Temp file for combined context+agent
    # Fields for respawning with --resume
    claude_session_id: str | None = None  # Claude CLI's session ID for --resume
    thinking_budget: int | None = None
    mcp_config: Path | None = None

    @property
    def pid(self) -> int | None:
        """Get process ID."""
        return self.process.pid if self.process else None

    @property
    def is_running(self) -> bool:
        """Check if process is still running."""
        return self.process and self.process.returncode is None

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

    def _validate_working_dir(self, working_dir: Path) -> Path:
        """Validate working directory is within allowed paths.

        Args:
            working_dir: The working directory to validate

        Returns:
            Resolved absolute path

        Raises:
            SecurityError: If working directory is outside allowed base
            ValueError: If working directory does not exist
        """
        resolved = working_dir.resolve()
        settings = get_settings()
        allowed_base = settings.repos_dir.resolve()

        if not str(resolved).startswith(str(allowed_base) + os.sep) and resolved != allowed_base:
            raise SecurityError(f"Working directory {resolved} outside allowed base {allowed_base}")

        if not resolved.is_dir():
            raise ValueError(f"Working directory does not exist: {resolved}")

        return resolved

    async def spawn_claude(
        self,
        session_id: str,
        working_dir: Path,
        model: str = "claude-opus-4-5-20251101",
        agent_path: Path | None = None,
        thinking_budget: int | None = None,
        mcp_config: Path | None = None,
        context: str | None = None,
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
        # Validate working directory before processing
        validated_working_dir = self._validate_working_dir(working_dir)

        async with self._lock:
            if session_id in self._processes:
                raise RuntimeError(f"Session {session_id} already exists")

            if len(self._processes) >= self._max_processes:
                raise RuntimeError(f"Max processes ({self._max_processes}) reached")

        # Build environment
        env = os.environ.copy()
        env["TMPDIR"] = "/tmp"  # Workaround for Bun file watcher bug
        env["PYTHONUNBUFFERED"] = "1"  # Disable Python buffering
        env["NODE_OPTIONS"] = "--no-warnings"  # Less noise from node

        # Set thinking budget if enabled
        if thinking_budget:
            env["MAX_THINKING_TOKENS"] = str(thinking_budget)
            logger.info(f"[CLAUDE] Extended thinking: {thinking_budget} tokens")

        # Generate a unique session ID for Claude CLI (for --resume support)
        claude_session_id = str(uuid.uuid4())

        # Build CLI arguments
        # Using --print mode for non-interactive chat
        args = [
            "claude",
            "--print",
            "--session-id",
            claude_session_id,  # Set session ID for later --resume
            "--verbose",
            "--dangerously-skip-permissions",
            "--model",
            model,
            "--output-format",
            "stream-json",
        ]

        # Create system prompt file combining context and agent
        temp_prompt_file = None
        system_prompt_parts = []

        # Add context if provided
        if context:
            system_prompt_parts.append(context)
            logger.info(f"[CLAUDE] Context added: {len(context)} chars")

        # Add agent prompt if provided
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

        # Add MCP config if provided
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
        )

        async with self._lock:
            self._processes[session_id] = cli_proc

        logger.info(
            f"[CLAUDE] Spawned process PID={process.pid} for session {session_id} (claude_session={claude_session_id})"
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
        # Validate working directory before processing
        validated_working_dir = self._validate_working_dir(working_dir)

        async with self._lock:
            if session_id in self._processes:
                raise RuntimeError(f"Session {session_id} already exists")

            if len(self._processes) >= self._max_processes:
                raise RuntimeError(f"Max processes ({self._max_processes}) reached")

        # Build environment
        os.environ.copy()

        # Create a placeholder process (Gemini starts fresh per message)
        # We'll create the actual process in send_message
        cli_proc = CLIProcess(
            session_id=session_id,
            cli_type=CLIType.GEMINI,
            process=None,  # Will be set on first message
            working_dir=validated_working_dir,
            model=model,
            agent_name=None,  # Gemini doesn't support custom agents
            status=SessionStatus.IDLE,
        )

        # Store context for Gemini (will be prepended to first message)
        if context:
            cli_proc._gemini_context = context
            cli_proc._context_used = False
            logger.info(
                f"[GEMINI] Context stored: {len(context)} chars (will prepend to first msg)"
            )

        async with self._lock:
            self._processes[session_id] = cli_proc

        logger.info(f"[GEMINI] Session {session_id} created (process spawns per message)")
        return cli_proc

    async def _respawn_claude_with_resume(self, proc: CLIProcess) -> None:
        """Respawn Claude process with --resume to continue conversation.

        When a Claude process ends (after processing a message), this method
        spawns a new process that resumes the same conversation using
        Claude CLI's --resume flag.

        Args:
            proc: The CLIProcess to respawn
        """
        if not proc.claude_session_id:
            raise RuntimeError("Cannot respawn: no claude_session_id")

        # Build environment
        env = os.environ.copy()
        env["TMPDIR"] = "/tmp"
        env["PYTHONUNBUFFERED"] = "1"
        env["NODE_OPTIONS"] = "--no-warnings"

        if proc.thinking_budget:
            env["MAX_THINKING_TOKENS"] = str(proc.thinking_budget)

        # Build args with --resume instead of --session-id
        args = [
            "claude",
            "--print",
            "--resume",
            proc.claude_session_id,  # Continue existing conversation
            "--verbose",
            "--dangerously-skip-permissions",
            "--model",
            proc.model,
            "--output-format",
            "stream-json",
        ]

        # Add MCP config if available
        if proc.mcp_config and proc.mcp_config.exists():
            args.extend(["--mcp-config", str(proc.mcp_config)])

        # Spawn new process
        new_process = await asyncio.create_subprocess_exec(
            *args,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(proc.working_dir),
            env=env,
        )

        # Replace the old process
        proc.process = new_process
        proc.status = SessionStatus.RUNNING

        logger.info(
            f"[CLAUDE] Respawned process PID={new_process.pid} with --resume "
            f"(claude_session={proc.claude_session_id})"
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
    ) -> AsyncIterator[str]:
        """Send message to Claude CLI process."""
        timeout = timeout or CLAUDE_TIMEOUT
        process = proc.process

        if not process or process.returncode is not None:
            # Process ended, respawn with --resume to continue conversation
            logger.info("[CLAUDE] Process ended, respawning with --resume")
            await self._respawn_claude_with_resume(proc)
            process = proc.process  # Get the new process

        proc.status = SessionStatus.STREAMING

        # Write message to stdin
        prompt_bytes = message.encode()
        try:
            logger.info(f"[CLAUDE] Writing {len(prompt_bytes)} bytes to stdin")
            process.stdin.write(prompt_bytes)
            await process.stdin.drain()
            process.stdin.close()
            await process.stdin.wait_closed()
            logger.info("[CLAUDE] Stdin closed (EOF sent)")
        except Exception as e:
            logger.error(f"[CLAUDE] Stdin error: {e}")
            raise

        # Read stdout LINE BY LINE for proper streaming
        # stream-json outputs one JSON object per line
        try:
            async with asyncio.timeout(timeout):
                while True:
                    # Read line by line - this is key for streaming!
                    line_bytes = await process.stdout.readline()
                    if not line_bytes:
                        break

                    line = line_bytes.decode("utf-8", errors="replace")
                    logger.debug(f"[CLAUDE] Line: {len(line)} chars")

                    # Yield each line immediately
                    if line:
                        yield line

        except asyncio.TimeoutError:
            logger.error(f"[CLAUDE] Timeout after {timeout}s")
            process.kill()
            proc.status = SessionStatus.ERROR
            raise

        # Wait for process to exit
        await process.wait()
        logger.info(f"[CLAUDE] Process exited with code {process.returncode}")

        if process.returncode != 0:
            proc.status = SessionStatus.ERROR
        else:
            proc.status = SessionStatus.COMPLETED

    async def _send_gemini_message(
        self,
        proc: CLIProcess,
        message: str,
        timeout: int | None = None,
    ) -> AsyncIterator[str]:
        """Send message to Gemini CLI (spawns new process per message)."""
        timeout = timeout or GEMINI_TIMEOUT
        proc.status = SessionStatus.STREAMING

        # Build environment
        env = os.environ.copy()

        # Prepend context to first message if available
        full_message = message
        if hasattr(proc, "_gemini_context") and not getattr(proc, "_context_used", True):
            context = proc._gemini_context
            full_message = f"""<context>
{context}
</context>

---

{message}"""
            proc._context_used = True
            logger.info(f"[GEMINI] Context prepended to message ({len(context)} chars)")

        # Gemini expects prompt as positional argument
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

        # Update proc reference
        proc.process = process
        logger.info(f"[GEMINI] Spawned process PID={process.pid}")

        # Stream stdout
        decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")

        try:
            async with asyncio.timeout(timeout):
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
            logger.error(f"[GEMINI] Timeout after {timeout}s")
            process.kill()
            proc.status = SessionStatus.ERROR
            raise

        await process.wait()
        logger.info(f"[GEMINI] Process exited with code {process.returncode}")

        if process.returncode != 0:
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

        # Cleanup temporary files
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

    def get_process_stats(self) -> dict:
        """Get statistics about running processes.

        Returns:
            Dict with process statistics
        """
        now = datetime.utcnow()
        stats = {
            "total_processes": len(self._processes),
            "max_processes": self._max_processes,
            "processes": [],
        }

        for session_id, proc in self._processes.items():
            age_seconds = (now - proc.started_at).total_seconds()
            stats["processes"].append(
                {
                    "session_id": session_id,
                    "cli_type": proc.cli_type.value,
                    "pid": proc.pid,
                    "status": proc.status.value,
                    "age_hours": round(age_seconds / 3600, 2),
                    "model": proc.model,
                }
            )

        return stats


# Singleton instance
_manager: CLIProcessManager | None = None


def get_process_manager() -> CLIProcessManager:
    """Get singleton CLIProcessManager instance."""
    global _manager
    if _manager is None:
        _manager = CLIProcessManager()
    return _manager
