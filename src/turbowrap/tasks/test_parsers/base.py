"""Base test parser interface."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class TestCaseResult:
    """Result of a single test case."""

    name: str
    status: str  # passed | failed | skipped | error
    file: str | None = None
    class_name: str | None = None
    line: int | None = None
    duration_ms: int | None = None
    error_message: str | None = None
    stack_trace: str | None = None
    metadata: dict[str, Any] | None = field(default_factory=dict)


@dataclass
class ParsedTestResults:
    """Aggregated results from parsing test output."""

    test_cases: list[TestCaseResult]
    total: int = 0
    passed: int = 0
    failed: int = 0
    skipped: int = 0
    errors: int = 0
    duration_seconds: float | None = None
    raw_output: str | None = None

    def __post_init__(self) -> None:
        """Calculate totals from test cases if not provided."""
        if self.total == 0 and self.test_cases:
            self.total = len(self.test_cases)
            self.passed = sum(1 for tc in self.test_cases if tc.status == "passed")
            self.failed = sum(1 for tc in self.test_cases if tc.status == "failed")
            self.skipped = sum(1 for tc in self.test_cases if tc.status == "skipped")
            self.errors = sum(1 for tc in self.test_cases if tc.status == "error")


class BaseTestParser(ABC):
    """Abstract base class for test output parsers."""

    @property
    @abstractmethod
    def framework(self) -> str:
        """Framework name (e.g., 'pytest', 'jest')."""
        ...

    @abstractmethod
    def parse(self, output: str, exit_code: int = 0) -> ParsedTestResults:
        """Parse test output and extract results.

        Args:
            output: Raw test output (stdout + stderr).
            exit_code: Process exit code.

        Returns:
            ParsedTestResults with test case details.
        """
        ...

    @abstractmethod
    def get_default_command(self, path: str) -> list[str]:
        """Get default command to run tests with JSON output.

        Args:
            path: Path to tests directory or file.

        Returns:
            Command as list of strings.
        """
        ...

    def get_env_vars(self) -> dict[str, str]:
        """Get additional environment variables for test execution.

        Returns:
            Dictionary of env vars to set.
        """
        return {}
