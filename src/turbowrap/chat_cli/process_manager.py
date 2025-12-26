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
import json
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import AsyncIterator, Callable, Awaitable

from .models import CLIType, SessionStatus

logger = logging.getLogger(__name__)

# Timeouts
DEFAULT_TIMEOUT = 120  # 2 minutes
CLAUDE_TIMEOUT = 900  # 15 minutes (for complex tasks)
GEMINI_TIMEOUT = 120  # 2 minutes


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

    @property
    def pid(self) -> int | None:
        """Get process ID."""
        return self.process.pid if self.process else None

    @property
    def is_running(self) -> bool:
        """Check if process is still running."""
        return self.process and self.process.returncode is None


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

    async def spawn_claude(
        self,
        session_id: str,
        working_dir: Path,
        model: str = "claude-opus-4-5-20251101",
        agent_path: Path | None = None,
        thinking_budget: int | None = None,
        mcp_config: Path | None = None,
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
        """
        async with self._lock:
            if session_id in self._processes:
                raise RuntimeError(f"Session {session_id} already exists")

            if len(self._processes) >= self._max_processes:
                raise RuntimeError(f"Max processes ({self._max_processes}) reached")

        # Build environment
        env = os.environ.copy()
        env["TMPDIR"] = "/tmp"  # Workaround for Bun file watcher bug

        # Set thinking budget if enabled
        if thinking_budget:
            env["MAX_THINKING_TOKENS"] = str(thinking_budget)
            logger.info(f"[CLAUDE] Extended thinking: {thinking_budget} tokens")

        # Build CLI arguments
        # Using --print mode for non-interactive chat
        args = [
            "claude",
            "--print",
            "--verbose",
            "--dangerously-skip-permissions",
            "--model",
            model,
            "--output-format",
            "stream-json",
        ]

        # Add agent system prompt if provided
        if agent_path and agent_path.exists():
            args.extend(["--system-prompt-file", str(agent_path)])
            logger.info(f"[CLAUDE] Using agent: {agent_path.stem}")

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
            cwd=str(working_dir),
            env=env,
        )

        cli_proc = CLIProcess(
            session_id=session_id,
            cli_type=CLIType.CLAUDE,
            process=process,
            working_dir=working_dir,
            model=model,
            agent_name=agent_path.stem if agent_path else None,
            status=SessionStatus.RUNNING,
        )

        async with self._lock:
            self._processes[session_id] = cli_proc

        logger.info(f"[CLAUDE] Spawned process PID={process.pid} for session {session_id}")
        return cli_proc

    async def spawn_gemini(
        self,
        session_id: str,
        working_dir: Path,
        model: str = "gemini-3-pro-preview",
        reasoning: bool = False,
    ) -> CLIProcess:
        """Spawn a new Gemini CLI process.

        Args:
            session_id: Unique session identifier
            working_dir: Working directory for CLI
            model: Gemini model to use
            reasoning: Enable deep reasoning mode

        Returns:
            CLIProcess instance

        Note:
            Gemini CLI doesn't support stdin input like Claude.
            Each message spawns a new process with prompt as argument.
        """
        async with self._lock:
            if session_id in self._processes:
                raise RuntimeError(f"Session {session_id} already exists")

            if len(self._processes) >= self._max_processes:
                raise RuntimeError(f"Max processes ({self._max_processes}) reached")

        # Build environment
        env = os.environ.copy()

        # Create a placeholder process (Gemini starts fresh per message)
        # We'll create the actual process in send_message
        cli_proc = CLIProcess(
            session_id=session_id,
            cli_type=CLIType.GEMINI,
            process=None,  # Will be set on first message
            working_dir=working_dir,
            model=model,
            agent_name=None,  # Gemini doesn't support custom agents
            status=SessionStatus.IDLE,
        )

        async with self._lock:
            self._processes[session_id] = cli_proc

        logger.info(f"[GEMINI] Session {session_id} created (process spawns per message)")
        return cli_proc

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
            # Process ended, need to respawn
            # For now, raise error - respawn logic can be added later
            raise RuntimeError("Claude process has ended")

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

        # Read stdout with streaming
        decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
        output_chunks = []

        try:
            async with asyncio.timeout(timeout):
                while True:
                    chunk = await process.stdout.read(1024)
                    if not chunk:
                        # Flush remaining
                        decoded = decoder.decode(b"", final=True)
                        if decoded:
                            output_chunks.append(decoded)
                            yield decoded
                        break

                    decoded = decoder.decode(chunk)
                    if decoded:
                        output_chunks.append(decoded)
                        yield decoded

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

        # Gemini expects prompt as positional argument
        args = [
            "gemini",
            "-m",
            proc.model,
            "--yolo",
            message,
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


# Singleton instance
_manager: CLIProcessManager | None = None


def get_process_manager() -> CLIProcessManager:
    """Get singleton CLIProcessManager instance."""
    global _manager
    if _manager is None:
        _manager = CLIProcessManager()
    return _manager
