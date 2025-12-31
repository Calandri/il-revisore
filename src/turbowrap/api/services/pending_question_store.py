"""
Pending question store - thread-safe singleton for managing pending questions.

Handles:
- Clarification questions during fix sessions
- Scope violation prompts when files outside workspace are modified

Extracted from fix.py global state to follow Single Responsibility Principle.
"""

from __future__ import annotations

import asyncio
import logging
import threading
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from turbowrap.fix import ClarificationAnswer, ClarificationQuestion

logger = logging.getLogger(__name__)


class ScopeViolationResponse(BaseModel):
    """Response to a scope violation prompt."""

    allow: bool = Field(..., description="Whether to allow the paths")
    paths: list[str] = Field(default_factory=list, description="Paths to add")


class PendingQuestionStore:
    """Thread-safe singleton store for pending questions.

    Manages two types of pending questions:
    1. Clarification questions: Q&A during fix sessions
    2. Scope violation prompts: When files outside workspace are modified

    Uses asyncio.Future for blocking waits and threading.RLock for thread safety.
    """

    _instance: PendingQuestionStore | None = None
    _lock = threading.Lock()

    def __init__(self) -> None:
        """Initialize the store. Use get_instance() instead of direct instantiation."""
        # Clarification questions
        self._clarifications: dict[str, ClarificationQuestion] = {}
        self._clarification_futures: dict[str, asyncio.Future[ClarificationAnswer]] = {}

        # Scope violation prompts
        self._scope_violations: dict[str, dict[str, Any]] = {}
        self._scope_futures: dict[str, asyncio.Future[ScopeViolationResponse]] = {}

        # Internal lock for thread-safe operations
        self._store_lock = threading.RLock()

    @classmethod
    def get_instance(cls) -> PendingQuestionStore:
        """Get the singleton instance.

        Thread-safe double-checked locking pattern.

        Returns:
            The singleton PendingQuestionStore instance.
        """
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    @classmethod
    def reset_instance(cls) -> None:
        """Reset the singleton instance. Used for testing."""
        with cls._lock:
            cls._instance = None

    # =========================================================================
    # Clarification Questions
    # =========================================================================

    def register_clarification(
        self,
        question_id: str,
        question: ClarificationQuestion,
    ) -> asyncio.Future[ClarificationAnswer]:
        """Register a pending clarification question.

        Called by the orchestrator when user input is needed.
        Creates a Future that will be resolved when the user responds.

        Args:
            question_id: Unique identifier for the question.
            question: The clarification question object.

        Returns:
            Future that resolves with the user's answer.
        """
        with self._store_lock:
            self._clarifications[question_id] = question
            loop = asyncio.get_event_loop()
            future: asyncio.Future[ClarificationAnswer] = loop.create_future()
            self._clarification_futures[question_id] = future
            logger.debug(f"Registered clarification question: {question_id}")
            return future

    def resolve_clarification(
        self,
        question_id: str,
        answer: ClarificationAnswer,
    ) -> bool:
        """Resolve a pending clarification question.

        Called when the user submits an answer via the API.

        Args:
            question_id: The question ID to resolve.
            answer: The user's answer.

        Returns:
            True if resolved successfully, False if not found or already resolved.
        """
        with self._store_lock:
            if question_id not in self._clarification_futures:
                logger.warning(f"No pending clarification: {question_id}")
                return False

            future = self._clarification_futures[question_id]
            if future.done():
                logger.warning(f"Clarification already resolved: {question_id}")
                return False

            future.set_result(answer)
            logger.debug(f"Resolved clarification: {question_id}")
            return True

    def has_pending_clarification(self, question_id: str) -> bool:
        """Check if a clarification question is pending.

        Args:
            question_id: The question ID to check.

        Returns:
            True if the question is pending.
        """
        with self._store_lock:
            return question_id in self._clarification_futures

    def get_clarification(self, question_id: str) -> ClarificationQuestion | None:
        """Get a pending clarification question.

        Args:
            question_id: The question ID to get.

        Returns:
            The clarification question, or None if not found.
        """
        with self._store_lock:
            return self._clarifications.get(question_id)

    def remove_clarification(self, question_id: str) -> None:
        """Remove a clarification question from the store.

        Args:
            question_id: The question ID to remove.
        """
        with self._store_lock:
            self._clarifications.pop(question_id, None)
            self._clarification_futures.pop(question_id, None)
            logger.debug(f"Removed clarification: {question_id}")

    # =========================================================================
    # Scope Violations
    # =========================================================================

    def register_scope_violation(
        self,
        question_id: str,
        dirs: set[str],
        repo_id: str,
    ) -> asyncio.Future[ScopeViolationResponse]:
        """Register a pending scope violation question.

        Called by the orchestrator when scope violations are detected.
        Creates a Future that will be resolved when the user responds.

        Args:
            question_id: Unique identifier for the question (usually "scope_{session_id}").
            dirs: Set of directories/paths that violated the scope.
            repo_id: The repository ID.

        Returns:
            Future that resolves with the user's response.
        """
        with self._store_lock:
            self._scope_violations[question_id] = {
                "dirs": list(dirs),
                "repo_id": repo_id,
            }
            loop = asyncio.get_event_loop()
            future: asyncio.Future[ScopeViolationResponse] = loop.create_future()
            self._scope_futures[question_id] = future
            logger.debug(f"Registered scope violation: {question_id} with dirs: {dirs}")
            return future

    async def wait_for_scope_response(
        self,
        question_id: str,
    ) -> ScopeViolationResponse:
        """Wait for user response to a scope violation prompt.

        Args:
            question_id: The question ID (usually "scope_{session_id}").

        Returns:
            The user's response.

        Raises:
            KeyError: If no pending question with this ID.
        """
        with self._store_lock:
            if question_id not in self._scope_futures:
                raise KeyError(f"No pending scope question: {question_id}")
            future = self._scope_futures[question_id]

        # Wait outside the lock to avoid blocking other operations
        return await future

    def resolve_scope_violation(
        self,
        question_id: str,
        response: ScopeViolationResponse,
    ) -> bool:
        """Resolve a pending scope violation question.

        Called when the user submits a response via the API.

        Args:
            question_id: The question ID to resolve.
            response: The user's response.

        Returns:
            True if resolved successfully, False if not found or already resolved.
        """
        with self._store_lock:
            if question_id not in self._scope_futures:
                logger.warning(f"No pending scope violation: {question_id}")
                return False

            future = self._scope_futures[question_id]
            if future.done():
                logger.warning(f"Scope violation already resolved: {question_id}")
                return False

            future.set_result(response)
            logger.debug(f"Resolved scope violation: {question_id}")
            return True

    def has_pending_scope_violation(self, question_id: str) -> bool:
        """Check if a scope violation question is pending.

        Args:
            question_id: The question ID to check.

        Returns:
            True if the question is pending.
        """
        with self._store_lock:
            return question_id in self._scope_futures

    def get_scope_violation(self, question_id: str) -> dict[str, Any] | None:
        """Get pending scope violation data.

        Args:
            question_id: The question ID to get.

        Returns:
            Dict with "dirs" and "repo_id", or None if not found.
        """
        with self._store_lock:
            return self._scope_violations.get(question_id)

    def remove_scope_violation(self, question_id: str) -> None:
        """Remove a scope violation question from the store.

        Args:
            question_id: The question ID to remove.
        """
        with self._store_lock:
            self._scope_violations.pop(question_id, None)
            self._scope_futures.pop(question_id, None)
            logger.debug(f"Removed scope violation: {question_id}")


# Convenience function for getting the singleton
def get_pending_question_store() -> PendingQuestionStore:
    """Get the singleton PendingQuestionStore instance.

    Returns:
        The singleton instance.
    """
    return PendingQuestionStore.get_instance()
