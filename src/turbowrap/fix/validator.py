"""Issue validation for the Fix Issue system."""

import logging
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class ValidationResult:
    """Result of issue validation."""

    is_valid: bool
    file_exists: bool
    code_matches: bool
    file_content: str | None = None
    error: str | None = None
    warning: str | None = None
    warnings: list[str] = field(default_factory=list)  # Multiple warnings
    has_uncommitted_changes: bool = False  # File has local modifications
    is_binary: bool = False  # File is binary (can't be fixed)


class IssueValidator:
    """Validates that issues are still applicable."""

    # Binary file extensions that can't be fixed
    BINARY_EXTENSIONS = {
        ".png",
        ".jpg",
        ".jpeg",
        ".gif",
        ".ico",
        ".webp",
        ".svg",
        ".pdf",
        ".zip",
        ".tar",
        ".gz",
        ".woff",
        ".woff2",
        ".ttf",
        ".eot",
        ".mp3",
        ".mp4",
        ".avi",
        ".mov",
        ".pyc",
        ".pyo",
        ".so",
        ".dll",
        ".exe",
        ".bin",
        ".dat",
        ".db",
        ".sqlite",
    }

    def __init__(self, repo_path: Path):
        """Initialize with repository path."""
        self.repo_path = repo_path

    def _check_git_status(self, file_path: str) -> tuple[bool, bool]:
        """Check git status of a file.

        Returns:
            Tuple of (has_uncommitted_changes, is_tracked)
        """
        try:
            # Check if file has uncommitted changes
            result = subprocess.run(
                ["git", "status", "--porcelain", file_path],
                cwd=self.repo_path,
                capture_output=True,
                text=True,
                timeout=10,
            )
            output = result.stdout.strip()

            if not output:
                return False, True  # No changes, is tracked

            # Parse git status codes
            # M = modified, A = added, D = deleted, ?? = untracked
            status_code = output[:2]
            has_changes = status_code.strip() != ""
            is_tracked = "?" not in status_code

            return has_changes, is_tracked

        except (subprocess.TimeoutExpired, subprocess.SubprocessError) as e:
            logger.warning(f"Failed to check git status: {e}")
            return False, True  # Assume no issues on git check failure

    def _is_binary_file(self, file_path: str) -> bool:
        """Check if a file is binary based on extension."""
        suffix = Path(file_path).suffix.lower()
        return suffix in self.BINARY_EXTENSIONS

    def _check_syntax_valid(self, file_path: str, content: str) -> tuple[bool, str | None]:
        """Basic syntax validation for Python files.

        Returns:
            Tuple of (is_valid, error_message)
        """
        suffix = Path(file_path).suffix.lower()

        if suffix == ".py":
            try:
                compile(content, file_path, "exec")
                return True, None
            except SyntaxError as e:
                return False, f"Python syntax error at line {e.lineno}: {e.msg}"

        # For other files, we can't easily validate syntax
        return True, None

    def validate_issue(
        self,
        file_path: str,
        line: int | None,
        current_code: str | None,
        check_git: bool = True,
    ) -> ValidationResult:
        """
        Validate that an issue is still applicable.

        Checks:
        1. File is not binary
        2. File exists
        3. File has no uncommitted local changes (if check_git=True)
        4. If current_code is provided, it still exists in the file
        5. If line is provided, the code is near that line
        6. File syntax is valid (for Python files)

        Args:
            file_path: Relative path to the file
            line: Line number where issue was found
            current_code: Code snippet that was flagged
            check_git: Whether to check git status (default True)

        Returns:
            ValidationResult with details
        """
        warnings_list: list[str] = []
        full_path = self.repo_path / file_path

        # Check 1: Binary files can't be fixed
        if self._is_binary_file(file_path):
            logger.warning(f"Binary file cannot be fixed: {file_path}")
            return ValidationResult(
                is_valid=False,
                file_exists=True,
                code_matches=False,
                is_binary=True,
                error=f"Binary file cannot be fixed: {file_path}",
            )

        # Check 2: File exists
        if not full_path.exists():
            logger.warning(f"File not found: {file_path}")
            return ValidationResult(
                is_valid=False,
                file_exists=False,
                code_matches=False,
                error=f"File not found: {file_path}",
            )

        # Check 2b: Path is a file (not a directory)
        if full_path.is_dir():
            logger.warning(f"Path is a directory, not a file: {file_path}")
            return ValidationResult(
                is_valid=False,
                file_exists=True,
                code_matches=False,
                error=f"Cannot fix directory-level issues automatically: {file_path}",
            )

        # Check 3: Git status (uncommitted changes)
        has_uncommitted = False
        if check_git:
            has_changes, is_tracked = self._check_git_status(file_path)
            if has_changes:
                has_uncommitted = True
                warnings_list.append(
                    "File has uncommitted changes - fix may conflict with local modifications"
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
                has_uncommitted_changes=has_uncommitted,
                warnings=warnings_list,
            )

        # Check 4: Validate existing file syntax (for Python)
        syntax_valid, syntax_error = self._check_syntax_valid(file_path, file_content)
        if not syntax_valid:
            warnings_list.append(f"Original file has syntax issues: {syntax_error}")

        # If no current_code provided, consider valid (can't verify)
        if not current_code:
            warnings_list.append("No code snippet to verify - assuming issue is still valid")
            return ValidationResult(
                is_valid=True,
                file_exists=True,
                code_matches=True,
                file_content=file_content,
                warning=warnings_list[0] if warnings_list else None,
                warnings=warnings_list,
                has_uncommitted_changes=has_uncommitted,
            )

        # Check 5: Check if current_code exists in file
        # Normalize whitespace for comparison
        normalized_code = self._normalize_code(current_code)
        normalized_content = self._normalize_code(file_content)

        if normalized_code not in normalized_content:
            # Try fuzzy match - code might have minor changes
            if self._fuzzy_match(current_code, file_content):
                warnings_list.append("Code partially matches - issue may have been modified")
                return ValidationResult(
                    is_valid=True,
                    file_exists=True,
                    code_matches=True,
                    file_content=file_content,
                    warning=warnings_list[0] if warnings_list else None,
                    warnings=warnings_list,
                    has_uncommitted_changes=has_uncommitted,
                )

            logger.warning(f"Code snippet not found in {file_path}")
            return ValidationResult(
                is_valid=False,
                file_exists=True,
                code_matches=False,
                file_content=file_content,
                error="Code snippet not found in file - issue may have been fixed or code changed",
                warnings=warnings_list,
                has_uncommitted_changes=has_uncommitted,
            )

        # Check 6: Optionally verify line number
        if line:
            actual_line = self._find_code_line(file_content, current_code)
            if actual_line and abs(actual_line - line) > 20:
                warnings_list.append(f"Code found but at line {actual_line} (expected {line})")

        return ValidationResult(
            is_valid=True,
            file_exists=True,
            code_matches=True,
            file_content=file_content,
            warning=warnings_list[0] if warnings_list else None,
            warnings=warnings_list,
            has_uncommitted_changes=has_uncommitted,
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
        haystack_lines = [line.strip() for line in haystack.strip().split("\n") if line.strip()]

        if not needle_lines:
            return False

        # Count how many needle lines appear in haystack
        matches = sum(1 for line in needle_lines if line in haystack_lines)
        match_ratio = matches / len(needle_lines)

        return match_ratio >= threshold

    def _find_code_line(self, file_content: str, code_snippet: str) -> int | None:
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
    line: int | None,
    current_code: str | None,
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
