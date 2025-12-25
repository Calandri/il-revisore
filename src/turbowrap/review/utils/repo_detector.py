"""
Repository type detection utility.
"""

import fnmatch
from pathlib import Path

from turbowrap.review.models.report import RepoType

# Default indicators
DEFAULT_BACKEND_INDICATORS = [
    "*.py",
    "requirements.txt",
    "pyproject.toml",
    "setup.py",
    "Pipfile",
    "*.go",
    "go.mod",
    "*.java",
    "pom.xml",
    "build.gradle",
    "*.rs",
    "Cargo.toml",
    "*.rb",
    "Gemfile",
    "*.php",
    "composer.json",
]

DEFAULT_FRONTEND_INDICATORS = [
    "*.tsx",
    "*.jsx",
    "*.vue",
    "*.svelte",
    "package.json",
    "vite.config.*",
    "next.config.*",
    "nuxt.config.*",
    "angular.json",
    "tailwind.config.*",
    "postcss.config.*",
]


class RepoDetector:
    """
    Detects repository type based on file patterns and structure.
    """

    def __init__(
        self,
        backend_indicators: list[str] | None = None,
        frontend_indicators: list[str] | None = None,
    ):
        """
        Initialize detector with custom or default indicators.

        Args:
            backend_indicators: Patterns indicating backend code
            frontend_indicators: Patterns indicating frontend code
        """
        self.backend_indicators = backend_indicators or DEFAULT_BACKEND_INDICATORS
        self.frontend_indicators = frontend_indicators or DEFAULT_FRONTEND_INDICATORS

    def detect(self, files: list[str]) -> RepoType:
        """
        Detect repository type from a list of file paths.

        Args:
            files: List of file paths to analyze

        Returns:
            Detected RepoType
        """
        has_backend = self._has_indicators(files, self.backend_indicators)
        has_frontend = self._has_indicators(files, self.frontend_indicators)

        if has_backend and has_frontend:
            return RepoType.FULLSTACK
        if has_backend:
            return RepoType.BACKEND
        if has_frontend:
            return RepoType.FRONTEND
        return RepoType.UNKNOWN

    def detect_from_directory(self, directory: str | Path) -> RepoType:
        """
        Detect repository type by scanning a directory.

        Args:
            directory: Path to the directory to scan

        Returns:
            Detected RepoType
        """
        directory = Path(directory)
        if not directory.exists():
            return RepoType.UNKNOWN

        files = self._collect_files(directory)
        return self.detect(files)

    def _has_indicators(self, files: list[str], indicators: list[str]) -> bool:
        """Check if any file matches the indicators."""
        for file_path in files:
            file_name = Path(file_path).name
            for indicator in indicators:
                if indicator.startswith("*."):
                    # Extension pattern
                    if file_name.endswith(indicator[1:]):
                        return True
                elif fnmatch.fnmatch(file_name, indicator) or file_name == indicator:
                    return True
        return False

    def _collect_files(
        self,
        directory: Path,
        max_depth: int = 3,
        exclude_dirs: set[str] | None = None,
    ) -> list[str]:
        """
        Collect file paths from directory up to max depth.

        Args:
            directory: Root directory to scan
            max_depth: Maximum directory depth to scan
            exclude_dirs: Directory names to exclude

        Returns:
            List of relative file paths
        """
        if exclude_dirs is None:
            exclude_dirs = {
                ".git",
                "node_modules",
                "__pycache__",
                ".venv",
                "venv",
                ".mypy_cache",
                ".pytest_cache",
                "dist",
                "build",
                ".next",
                "coverage",
            }

        files = []
        self._scan_directory(directory, directory, files, max_depth, exclude_dirs, 0)
        return files

    def _scan_directory(
        self,
        root: Path,
        current: Path,
        files: list[str],
        max_depth: int,
        exclude_dirs: set[str],
        current_depth: int,
    ) -> None:
        """Recursively scan directory for files."""
        if current_depth > max_depth:
            return

        try:
            for item in current.iterdir():
                if item.is_file():
                    files.append(str(item.relative_to(root)))
                elif item.is_dir() and item.name not in exclude_dirs:
                    self._scan_directory(
                        root, item, files, max_depth, exclude_dirs, current_depth + 1
                    )
        except PermissionError:
            pass

    def get_analysis_summary(self, files: list[str]) -> dict:
        """
        Get detailed analysis of repository composition.

        Args:
            files: List of file paths

        Returns:
            Dictionary with analysis details
        """
        backend_files = []
        frontend_files = []
        other_files = []

        for file_path in files:
            file_name = Path(file_path).name

            is_backend = any(
                file_name.endswith(ind[1:]) if ind.startswith("*.") else file_name == ind
                for ind in self.backend_indicators
            )
            is_frontend = any(
                file_name.endswith(ind[1:]) if ind.startswith("*.") else file_name == ind
                for ind in self.frontend_indicators
            )

            if is_backend:
                backend_files.append(file_path)
            elif is_frontend:
                frontend_files.append(file_path)
            else:
                other_files.append(file_path)

        repo_type = self.detect(files)

        return {
            "repo_type": repo_type.value,
            "total_files": len(files),
            "backend_files": len(backend_files),
            "frontend_files": len(frontend_files),
            "other_files": len(other_files),
            "backend_percentage": (
                round(len(backend_files) / len(files) * 100, 1) if files else 0
            ),
            "frontend_percentage": (
                round(len(frontend_files) / len(files) * 100, 1) if files else 0
            ),
        }


def detect_repo_type(
    files: list[str] | None = None,
    directory: str | Path | None = None,
) -> RepoType:
    """
    Convenience function to detect repository type.

    Args:
        files: List of file paths, OR
        directory: Directory path to scan

    Returns:
        Detected RepoType
    """
    detector = RepoDetector()

    if files is not None:
        return detector.detect(files)
    if directory is not None:
        return detector.detect_from_directory(directory)
    # Default to current directory
    return detector.detect_from_directory(Path.cwd())
