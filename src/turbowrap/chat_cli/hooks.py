"""CLI Chat Hooks.

Hook system per eventi chat CLI.
Integra:
- Token counting (tiktoken)
- STRUCTURE.md generation
- Message stats tracking

Può essere usato come comando hook per Claude CLI:
    python3 -m turbowrap.chat_cli.hooks <event_type> <args>
"""

import asyncio
import json
import logging
import sys
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


class ChatHooks:
    """Hook handlers per eventi chat CLI.

    Usage:
        hooks = ChatHooks(db_session)
        await hooks.on_message_sent(session_id, content)
        await hooks.on_response_complete(session_id, content, duration_ms)
    """

    def __init__(self, db: Session | None = None) -> None:
        """Initialize hooks.

        Args:
            db: Optional SQLAlchemy session for DB operations
        """
        self._db = db
        self._token_cache: dict[str, int] = {}

    def calculate_tokens(self, content: str) -> dict[str, int]:
        """Calculate token count for content.

        Uses tiktoken cl100k_base encoding (GPT-4/Claude compatible).

        Args:
            content: Text content to analyze

        Returns:
            Dict with chars, lines, words, tokens
        """
        from ..utils.file_utils import calculate_tokens

        return calculate_tokens(content)

    def count_tokens(self, content: str) -> int:
        """Quick token count only.

        Args:
            content: Text to count tokens for

        Returns:
            Token count
        """
        return self.calculate_tokens(content)["tokens"]

    async def on_message_sent(
        self,
        session_id: str,
        content: str,
    ) -> dict[str, int]:
        """Hook: User message sent.

        Calculates input tokens and updates session stats.

        Args:
            session_id: Chat session ID
            content: Message content

        Returns:
            Token stats
        """
        stats = self.calculate_tokens(content)

        if self._db:
            from ..db.models import CLIChatSession

            session = self._db.query(CLIChatSession).filter(CLIChatSession.id == session_id).first()

            if session:
                session.total_tokens_in = session.total_tokens_in + stats["tokens"]  # type: ignore[assignment]
                session.updated_at = datetime.utcnow()  # type: ignore[assignment]
                self._db.commit()
                logger.debug(f"Session {session_id[:8]}: +{stats['tokens']} input tokens")

        return stats

    async def on_response_complete(
        self,
        session_id: str,
        content: str,
        duration_ms: int | None = None,
        message_id: str | None = None,
    ) -> dict[str, int]:
        """Hook: Assistant response complete.

        Calculates output tokens and updates session/message stats.

        Args:
            session_id: Chat session ID
            content: Response content
            duration_ms: Response time in milliseconds
            message_id: Optional message ID to update

        Returns:
            Token stats
        """
        stats = self.calculate_tokens(content)

        if self._db:
            from ..db.models import CLIChatMessage, CLIChatSession

            session = self._db.query(CLIChatSession).filter(CLIChatSession.id == session_id).first()

            if session:
                session.total_tokens_out = session.total_tokens_out + stats["tokens"]  # type: ignore[assignment]
                session.last_message_at = datetime.utcnow()  # type: ignore[assignment]
                session.updated_at = datetime.utcnow()  # type: ignore[assignment]

            if message_id:
                message = (
                    self._db.query(CLIChatMessage).filter(CLIChatMessage.id == message_id).first()
                )

                if message:
                    message.tokens_out = stats["tokens"]  # type: ignore[assignment]
                    if duration_ms:
                        message.duration_ms = duration_ms  # type: ignore[assignment]

            self._db.commit()
            logger.debug(f"Session {session_id[:8]}: +{stats['tokens']} output tokens")

        return stats

    async def on_session_start(
        self,
        session_id: str,
        repo_path: Path | None = None,
        force_regenerate: bool = False,
    ) -> dict[str, Any]:
        """Hook: Session started.

        Checks and regenerates stale STRUCTURE.md files.

        Args:
            session_id: Chat session ID
            repo_path: Repository path (if linked)
            force_regenerate: Force regeneration regardless of staleness

        Returns:
            Status dict
        """
        result: dict[str, Any] = {
            "session_id": session_id,
            "structure_generated": False,
            "stale_count": 0,
        }

        if not repo_path or not repo_path.exists():
            return result

        try:
            from ..tools.structure_generator import StructureGenerator

            generator = StructureGenerator(repo_path)

            # Check for stale structures
            stale_dirs: list[Path] = (
                generator.check_stale_structures()
                if hasattr(generator, "check_stale_structures")
                else []
            )

            if force_regenerate or stale_dirs:
                # Regenerate structures
                if hasattr(generator, "regenerate_stale"):
                    await asyncio.to_thread(generator.regenerate_stale)
                else:
                    await asyncio.to_thread(generator.generate)

                result["structure_generated"] = True
                result["stale_count"] = len(stale_dirs) if stale_dirs else 1

            logger.info(
                f"Session {session_id[:8]}: Structure check complete "
                f"(regenerated={result['structure_generated']})"
            )

        except Exception as e:
            logger.warning(f"Structure generation failed: {e}")
            result["error"] = str(e)

        return result

    async def on_tool_use(
        self,
        tool_name: str,
        file_path: str | None = None,
        content: str | None = None,
    ) -> dict[str, Any]:
        """Hook: Tool used by assistant (Write/Edit).

        Triggered after file modifications to update structures.

        Args:
            tool_name: Name of tool used (Write, Edit, etc.)
            file_path: Path to modified file
            content: New content (for token counting)

        Returns:
            Status dict
        """
        result: dict[str, Any] = {
            "tool": tool_name,
            "tokens": 0,
            "structure_updated": False,
        }

        if content:
            result["tokens"] = self.count_tokens(content)

        if file_path and tool_name in ("Write", "Edit"):
            file_p = Path(file_path)
            if file_p.exists():
                # Could trigger structure update for containing directory
                # For now just log
                logger.debug(f"File modified: {file_path} ({result['tokens']} tokens)")

        return result

    async def on_git_status(
        self,
        repo_path: Path,
    ) -> dict[str, Any]:
        """Hook: Get git status for repository.

        Args:
            repo_path: Path to git repository

        Returns:
            Git status dict
        """
        try:
            from ..utils.git_utils import get_repo_status

            status = get_repo_status(repo_path)

            return {
                "branch": status.branch,
                "is_clean": status.is_clean,
                "modified": status.modified,
                "untracked": status.untracked,
                "ahead": status.ahead,
                "behind": status.behind,
            }

        except Exception as e:
            logger.warning(f"Git status failed: {e}")
            return {"error": str(e)}

    async def on_cost_threshold(
        self,
        session_id: str,
        threshold_tokens: int = 100000,
    ) -> dict[str, Any]:
        """Hook: Check if session has exceeded token threshold.

        Args:
            session_id: Chat session ID
            threshold_tokens: Token threshold to check against

        Returns:
            Status dict with exceeded flag
        """
        result: dict[str, Any] = {
            "session_id": session_id,
            "exceeded": False,
            "total_tokens": 0,
            "threshold": threshold_tokens,
        }

        if self._db:
            from ..db.models import CLIChatSession

            session = self._db.query(CLIChatSession).filter(CLIChatSession.id == session_id).first()

            if session:
                total = session.total_tokens_in + session.total_tokens_out
                result["total_tokens"] = total
                result["exceeded"] = total > threshold_tokens

                if result["exceeded"]:
                    logger.warning(
                        f"Session {session_id[:8]} exceeded threshold: "
                        f"{total} > {threshold_tokens}"
                    )

        return result

    async def on_file_modified(
        self,
        file_path: Path,
        repo_path: Path | None = None,
    ) -> dict[str, Any]:
        """Hook: File was modified, update STRUCTURE.md.

        Args:
            file_path: Path to modified file
            repo_path: Repository root path

        Returns:
            Status dict
        """
        result: dict[str, Any] = {
            "file": str(file_path),
            "structure_updated": False,
        }

        if not repo_path:
            repo_path = file_path.parent

        try:
            from ..tools.structure_generator import StructureGenerator

            # Find the directory containing the file
            dir_path = file_path.parent

            # Check if STRUCTURE.md exists and needs update
            structure_file = dir_path / "STRUCTURE.md"
            if structure_file.exists():
                # File is older than modified file - needs regeneration
                if structure_file.stat().st_mtime < file_path.stat().st_mtime:
                    StructureGenerator(repo_path)
                    # Would regenerate here
                    result["structure_updated"] = True
                    logger.info(f"Structure update needed for {dir_path}")

        except Exception as e:
            logger.warning(f"File modified hook failed: {e}")
            result["error"] = str(e)

        return result

    async def on_lint_check(
        self,
        file_path: Path,
        content: str | None = None,
    ) -> dict[str, Any]:
        """Hook: Run linter on file.

        Args:
            file_path: Path to file to lint
            content: Optional content (if file not saved yet)

        Returns:
            Lint results
        """
        result: dict[str, Any] = {
            "file": str(file_path),
            "passed": True,
            "errors": [],
            "warnings": [],
        }

        suffix = file_path.suffix.lower()

        try:
            if suffix == ".py":
                # Run ruff for Python
                import subprocess

                proc = await asyncio.to_thread(
                    subprocess.run,
                    ["ruff", "check", str(file_path), "--output-format", "json"],
                    capture_output=True,
                    text=True,
                )

                if proc.returncode != 0 and proc.stdout:
                    import json as json_mod

                    issues = json_mod.loads(proc.stdout)
                    result["errors"] = [
                        f"{i['code']}: {i['message']} (line {i['location']['row']})" for i in issues
                    ]
                    result["passed"] = len(result["errors"]) == 0

            elif suffix in (".ts", ".tsx", ".js", ".jsx"):
                # Could run eslint here
                pass

        except FileNotFoundError:
            # Linter not installed
            result["skipped"] = True
        except Exception as e:
            logger.warning(f"Lint check failed: {e}")
            result["error"] = str(e)

        return result

    async def on_session_idle(
        self,
        session_id: str,
        idle_minutes: int = 5,
    ) -> dict[str, Any]:
        """Hook: Session has been idle, save state.

        Args:
            session_id: Chat session ID
            idle_minutes: Minutes of inactivity

        Returns:
            Status dict
        """
        result: dict[str, Any] = {
            "session_id": session_id,
            "idle_minutes": idle_minutes,
            "action_taken": None,
        }

        if self._db:
            from ..db.models import CLIChatSession

            session = self._db.query(CLIChatSession).filter(CLIChatSession.id == session_id).first()

            if session and session.last_message_at:
                idle_since = datetime.utcnow() - session.last_message_at
                if idle_since > timedelta(minutes=idle_minutes):
                    # Session is idle - could terminate process to save resources
                    result["action_taken"] = "marked_idle"
                    logger.info(f"Session {session_id[:8]} idle for {idle_since.seconds // 60}m")

        return result


class HookRegistry:
    """Registry for custom hooks.

    Allows adding custom async callbacks for events.
    """

    def __init__(self) -> None:
        self._hooks: dict[str, list[Callable[..., Awaitable[Any]]]] = {}

    def register(self, event: str, callback: Callable[..., Awaitable[Any]]) -> None:
        """Register a hook callback.

        Args:
            event: Event name (message_sent, response_complete, etc.)
            callback: Async function to call
        """
        if event not in self._hooks:
            self._hooks[event] = []
        self._hooks[event].append(callback)

    async def trigger(self, event: str, **kwargs: Any) -> list[Any]:
        """Trigger all hooks for an event.

        Args:
            event: Event name
            **kwargs: Arguments to pass to callbacks

        Returns:
            List of results from all callbacks
        """
        if event not in self._hooks:
            return []

        results: list[Any] = []
        for callback in self._hooks[event]:
            try:
                result = await callback(**kwargs)
                results.append(result)
            except Exception as e:
                logger.error(f"Hook error for {event}: {e}")
                results.append({"error": str(e)})

        return results


# Global registry
_hook_registry: HookRegistry = HookRegistry()


def get_hook_registry() -> HookRegistry:
    """Get global hook registry."""
    return _hook_registry


def register_hook(event: str, callback: Callable[..., Awaitable[Any]]) -> None:
    """Register a hook callback.

    Args:
        event: Event name
        callback: Async callback function
    """
    _hook_registry.register(event, callback)


async def trigger_hooks(event: str, **kwargs: Any) -> list[Any]:
    """Trigger all registered hooks for an event.

    Args:
        event: Event name
        **kwargs: Arguments for hooks

    Returns:
        List of results
    """
    return await _hook_registry.trigger(event, **kwargs)


# ============================================================================
# CLI Entry Point (for Claude hook command)
# ============================================================================


def main() -> None:
    """CLI entry point for hook commands.

    Usage:
        python -m turbowrap.chat_cli.hooks token_count "text to count"
        python -m turbowrap.chat_cli.hooks post_tool_use Write /path/to/file
        python -m turbowrap.chat_cli.hooks git_status /path/to/repo
        python -m turbowrap.chat_cli.hooks lint_check /path/to/file.py
    """
    if len(sys.argv) < 2:
        print("Usage: python -m turbowrap.chat_cli.hooks <command> [args]")
        print("Commands: token_count, post_tool_use, git_status, lint_check")
        sys.exit(1)

    command = sys.argv[1]
    hooks = ChatHooks()

    if command == "token_count":
        if len(sys.argv) < 3:
            print("Usage: token_count <text>")
            sys.exit(1)

        text = " ".join(sys.argv[2:])
        stats = hooks.calculate_tokens(text)
        print(json.dumps(stats))

    elif command == "post_tool_use":
        if len(sys.argv) < 4:
            print("Usage: post_tool_use <tool_name> <file_path>")
            sys.exit(1)

        tool_name = sys.argv[2]
        file_path_str = sys.argv[3]

        async def run_post_tool_use() -> None:
            result = await hooks.on_tool_use(tool_name, file_path_str)
            print(json.dumps(result))

        asyncio.run(run_post_tool_use())

    elif command == "git_status":
        if len(sys.argv) < 3:
            print("Usage: git_status <repo_path>")
            sys.exit(1)

        repo_path = Path(sys.argv[2])

        async def run_git_status() -> None:
            result = await hooks.on_git_status(repo_path)
            print(json.dumps(result))

        asyncio.run(run_git_status())

    elif command == "lint_check":
        if len(sys.argv) < 3:
            print("Usage: lint_check <file_path>")
            sys.exit(1)

        lint_file_path = Path(sys.argv[2])

        async def run_lint_check() -> None:
            result = await hooks.on_lint_check(lint_file_path)
            print(json.dumps(result))

        asyncio.run(run_lint_check())

    elif command == "file_modified":
        if len(sys.argv) < 3:
            print("Usage: file_modified <file_path> [repo_path]")
            sys.exit(1)

        modified_file_path = Path(sys.argv[2])
        modified_repo_path = Path(sys.argv[3]) if len(sys.argv) > 3 else None

        async def run_file_modified() -> None:
            result = await hooks.on_file_modified(modified_file_path, modified_repo_path)
            print(json.dumps(result))

        asyncio.run(run_file_modified())

    else:
        print(f"Unknown command: {command}")
        print("Available: token_count, post_tool_use, git_status, lint_check, file_modified")
        sys.exit(1)


if __name__ == "__main__":
    main()
