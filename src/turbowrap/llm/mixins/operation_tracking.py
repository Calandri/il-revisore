"""Mixin for operation tracking in CLI runners."""

import logging
import uuid
from abc import abstractmethod
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from turbowrap.api.services.operation_tracker import Operation

logger = logging.getLogger(__name__)


class OperationTrackingMixin:
    """Mixin providing operation tracking for CLI runners.

    Subclasses must define:
        - cli_name: str - The CLI identifier ("claude", "gemini", "grok")
        - model: str - The model being used
        - working_dir: Path | None - Working directory
        - agent_md_path: Path | None (optional) - Agent file path

    Usage:
        class MyCLI(OperationTrackingMixin):
            cli_name = "mycli"

            def __init__(self):
                self.model = "my-model"
                self.working_dir = Path("/some/path")
    """

    # Must be set by subclass
    cli_name: str
    model: str
    working_dir: Path | None

    # Optional - only Claude uses this
    agent_md_path: Path | None = None

    def _extract_repo_name(self) -> str | None:
        """Extract repository name from working_dir."""
        if self.working_dir:
            return self.working_dir.name
        return None

    def _infer_operation_type(self, explicit_type: str | None, prompt: str) -> str:
        """Infer operation type from context.

        Can be overridden by subclasses for custom logic.

        Args:
            explicit_type: Explicitly provided type
            prompt: The prompt being executed

        Returns:
            OperationType value string
        """
        if explicit_type:
            return explicit_type

        # Check agent_md_path if available (Claude-specific)
        if hasattr(self, "agent_md_path") and self.agent_md_path:
            agent_name = self.agent_md_path.stem.lower()
            if "fix" in agent_name:
                return "fix"
            if "review" in agent_name:
                return "review"
            if "commit" in agent_name:
                return "git_commit"

        # Infer from prompt keywords
        prompt_lower = prompt.lower()[:500]
        if "fix" in prompt_lower or "correggi" in prompt_lower:
            return "fix"
        if "review" in prompt_lower or "analizza" in prompt_lower:
            return "review"
        if "lint" in prompt_lower or "mypy" in prompt_lower or "ruff" in prompt_lower:
            return "review"
        if "commit" in prompt_lower:
            return "git_commit"
        if "merge" in prompt_lower:
            return "git_merge"

        return "cli_task"

    def _get_cli_specific_details(self) -> dict[str, Any]:
        """Get CLI-specific details for operation registration.

        Override in subclass to add custom fields.
        """
        details: dict[str, Any] = {
            "cli": self.cli_name,
        }
        # Add agent if available (Claude-specific)
        if hasattr(self, "agent_md_path") and self.agent_md_path:
            details["agent"] = self.agent_md_path.stem
        return details

    def _register_operation(
        self,
        context_id: str | None,
        prompt: str,
        operation_type: str | None,
        repo_name: str | None,
        user_name: str | None,
        operation_details: dict[str, Any] | None,
    ) -> "Operation | None":
        """Register operation in tracker.

        Returns:
            Operation instance or None if registration fails
        """
        try:
            from turbowrap.api.services.operation_tracker import OperationType, get_tracker

            tracker = get_tracker()
            op_type_str = self._infer_operation_type(operation_type, prompt)

            # Convert string to OperationType enum
            try:
                op_type = OperationType(op_type_str)
            except ValueError:
                op_type = OperationType.CLI_TASK

            # Extract prompt preview (first 150 chars, cleaned)
            prompt_preview = prompt[:150].replace("\n", " ").strip()
            if len(prompt) > 150:
                prompt_preview += "..."

            # Extract parent_session_id as first-class field (for hierarchical queries)
            details_copy = dict(operation_details or {})
            parent_session_id = details_copy.pop("parent_session_id", None)

            # Build details
            details = {
                "model": self.model,
                "working_dir": str(self.working_dir) if self.working_dir else None,
                "prompt_preview": prompt_preview,
                "prompt_length": len(prompt),
                **self._get_cli_specific_details(),
                **details_copy,
            }

            operation = tracker.register(
                op_type=op_type,
                operation_id=context_id or str(uuid.uuid4()),
                repo_name=repo_name or self._extract_repo_name(),
                user=user_name,
                parent_session_id=parent_session_id,
                details=details,
            )

            logger.info(
                f"[{self.cli_name.upper()} CLI] Operation registered: "
                f"{operation.operation_id[:8]} ({op_type.value})"
            )
            return operation

        except Exception as e:
            logger.warning(f"[{self.cli_name.upper()} CLI] Failed to register operation: {e}")
            return None

    @abstractmethod
    def _build_completion_result(
        self,
        duration_ms: int,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Build the result dict for operation completion.

        Must be implemented by subclass as each CLI has different stats.

        Args:
            duration_ms: Operation duration in milliseconds
            **kwargs: CLI-specific stats (model_usage, session_stats, etc.)

        Returns:
            Dict with result data for tracker.complete()
        """
        ...

    def _complete_operation(
        self,
        operation_id: str,
        duration_ms: int,
        **kwargs: Any,
    ) -> None:
        """Complete operation in tracker with stats.

        Subclass should call this with their specific stats:
            self._complete_operation(
                operation_id,
                duration_ms,
                model_usage=my_model_usage,
                tools_used=my_tools,
            )
        """
        try:
            from turbowrap.api.services.operation_tracker import get_tracker

            tracker = get_tracker()
            result = self._build_completion_result(duration_ms, **kwargs)
            tracker.complete(operation_id, result=result)

            # Log with token info if available
            tokens = result.get("total_tokens", result.get("tokens", 0))
            tools_count = len(result.get("tools_used", []))
            cost = result.get("cost_usd", 0)

            log_msg = f"[{self.cli_name.upper()} CLI] Operation completed: {operation_id[:8]}"
            if tokens:
                log_msg += f" ({tokens} tokens"
                if cost:
                    log_msg += f", ${cost:.4f}"
                log_msg += f", {tools_count} tools)"
            else:
                log_msg += f" ({tools_count} tools)"

            logger.info(log_msg)

        except Exception as e:
            logger.warning(f"[{self.cli_name.upper()} CLI] Failed to complete operation: {e}")

    def _fail_operation(self, operation_id: str, error: str) -> None:
        """Fail operation in tracker."""
        try:
            from turbowrap.api.services.operation_tracker import get_tracker

            tracker = get_tracker()
            tracker.fail(operation_id, error=error[:200])
            logger.info(f"[{self.cli_name.upper()} CLI] Operation failed: {operation_id[:8]}")

        except Exception as e:
            logger.warning(f"[{self.cli_name.upper()} CLI] Failed to mark operation as failed: {e}")

    def _update_operation(self, operation_id: str, details: dict[str, Any]) -> None:
        """Update operation details in tracker (e.g., add S3 URLs)."""
        try:
            from turbowrap.api.services.operation_tracker import get_tracker

            tracker = get_tracker()
            tracker.update(operation_id, details=details)

        except Exception as e:
            logger.warning(f"[{self.cli_name.upper()} CLI] Failed to update operation: {e}")
