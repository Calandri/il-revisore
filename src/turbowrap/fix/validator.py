"""Issue validation for the Fix Issue system."""

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class ValidationResult:
    """Result of issue validation."""

    is_valid: bool
    file_exists: bool
    code_matches: bool
    file_content: Optional[str] = None
    error: Optional[str] = None
    warning: Optional[str] = None


class IssueValidator:
    """Validates that issues are still applicable."""

    def __init__(self, repo_path: Path):
        """Initialize with repository path."""
        self.repo_path = repo_path

    def validate_issue(
        self,
        file_path: str,
        line: Optional[int],
        current_code: Optional[str],
    ) -> ValidationResult:
        """
        Validate that an issue is still applicable.

        Checks:
        1. File exists
        2. If current_code is provided, it still exists in the file
        3. If line is provided, the code is near that line

        Args:
            file_path: Relative path to the file
            line: Line number where issue was found
            current_code: Code snippet that was flagged

        Returns:
            ValidationResult with details
        """
        full_path = self.repo_path / file_path

        # Check file exists
        if not full_path.exists():
            logger.warning(f"File not found: {file_path}")
            return ValidationResult(
                is_valid=False,
                file_exists=False,
                code_matches=False,
                error=f"File not found: {file_path}",
            )

        # Read file content
        try:
            file_content = full_path.read_text(encoding="utf-8")
        except Exception as e:
            logger.error(f"Failed to read file {file_path}: {e}")
            return ValidationResult(
                is_valid=False,
                file_exists=True,
                code_matches=False,
                error=f"Failed to read file: {e}",
            )

        # If no current_code provided, consider valid (can't verify)
        if not current_code:
            return ValidationResult(
                is_valid=True,
                file_exists=True,
                code_matches=True,
                file_content=file_content,
                warning="No code snippet to verify - assuming issue is still valid",
            )

        # Check if current_code exists in file
        # Normalize whitespace for comparison
        normalized_code = self._normalize_code(current_code)
        normalized_content = self._normalize_code(file_content)

        if normalized_code not in normalized_content:
            # Try fuzzy match - code might have minor changes
            if self._fuzzy_match(current_code, file_content):
                return ValidationResult(
                    is_valid=True,
                    file_exists=True,
                    code_matches=True,
                    file_content=file_content,
                    warning="Code partially matches - issue may have been modified",
                )

            logger.warning(f"Code snippet not found in {file_path}")
            return ValidationResult(
                is_valid=False,
                file_exists=True,
                code_matches=False,
                file_content=file_content,
                error="Code snippet not found in file - issue may have been fixed or code changed",
            )

        # Optionally verify line number
        if line:
            actual_line = self._find_code_line(file_content, current_code)
            if actual_line and abs(actual_line - line) > 20:
                return ValidationResult(
                    is_valid=True,
                    file_exists=True,
                    code_matches=True,
                    file_content=file_content,
                    warning=f"Code found but at line {actual_line} (expected {line})",
                )

        return ValidationResult(
            is_valid=True,
            file_exists=True,
            code_matches=True,
            file_content=file_content,
        )

    def _normalize_code(self, code: str) -> str:
        """Normalize code for comparison."""
        # Remove leading/trailing whitespace from each line
        lines = [line.strip() for line in code.strip().split("\n")]
        # Join with single space
        return " ".join(line for line in lines if line)

    def _fuzzy_match(self, needle: str, haystack: str, threshold: float = 0.6) -> bool:
        """
        Check if needle fuzzy-matches somewhere in haystack.

        Uses simple line-by-line matching.
        """
        needle_lines = [line.strip() for line in needle.strip().split("\n") if line.strip()]
        haystack_lines = [
            line.strip() for line in haystack.strip().split("\n") if line.strip()
        ]

        if not needle_lines:
            return False

        # Count how many needle lines appear in haystack
        matches = sum(1 for line in needle_lines if line in haystack_lines)
        match_ratio = matches / len(needle_lines)

        return match_ratio >= threshold

    def _find_code_line(self, file_content: str, code_snippet: str) -> Optional[int]:
        """Find the line number where code snippet starts."""
        file_lines = file_content.split("\n")
        snippet_first_line = code_snippet.strip().split("\n")[0].strip()

        for i, line in enumerate(file_lines, 1):
            if snippet_first_line in line:
                return i

        return None


def validate_issue_for_fix(
    repo_path: Path,
    file_path: str,
    line: Optional[int],
    current_code: Optional[str],
) -> ValidationResult:
    """
    Convenience function to validate an issue.

    Args:
        repo_path: Repository root path
        file_path: Relative path to file
        line: Line number
        current_code: Code snippet to find

    Returns:
        ValidationResult
    """
    validator = IssueValidator(repo_path)
    return validator.validate_issue(file_path, line, current_code)
