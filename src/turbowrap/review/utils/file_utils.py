"""
File utilities for TurboWrap.
"""

import hashlib
from pathlib import Path
from typing import Optional


class FileUtils:
    """File utility functions."""

    @staticmethod
    def read_file(path: str | Path, encoding: str = "utf-8") -> str:
        """
        Read file content.

        Args:
            path: Path to file
            encoding: File encoding

        Returns:
            File content
        """
        return Path(path).read_text(encoding=encoding)

    @staticmethod
    def read_lines(
        path: str | Path,
        start_line: int = 1,
        end_line: Optional[int] = None,
    ) -> list[str]:
        """
        Read specific lines from a file.

        Args:
            path: Path to file
            start_line: Starting line (1-indexed)
            end_line: Ending line (inclusive, None for all)

        Returns:
            List of lines
        """
        content = FileUtils.read_file(path)
        lines = content.splitlines()

        start_idx = max(0, start_line - 1)
        end_idx = end_line if end_line else len(lines)

        return lines[start_idx:end_idx]

    @staticmethod
    def get_file_hash(path: str | Path) -> str:
        """
        Get SHA256 hash of file content.

        Args:
            path: Path to file

        Returns:
            Hex digest of hash
        """
        content = Path(path).read_bytes()
        return hashlib.sha256(content).hexdigest()

    @staticmethod
    def count_lines(path: str | Path) -> int:
        """
        Count lines in a file.

        Args:
            path: Path to file

        Returns:
            Line count
        """
        content = FileUtils.read_file(path)
        return len(content.splitlines())

    @staticmethod
    def get_extension(path: str | Path) -> str:
        """
        Get file extension.

        Args:
            path: Path to file

        Returns:
            Extension without dot
        """
        return Path(path).suffix.lstrip(".")

    @staticmethod
    def is_text_file(path: str | Path) -> bool:
        """
        Check if file is likely a text file.

        Args:
            path: Path to file

        Returns:
            True if likely text file
        """
        text_extensions = {
            "py",
            "js",
            "ts",
            "tsx",
            "jsx",
            "json",
            "yaml",
            "yml",
            "md",
            "txt",
            "html",
            "css",
            "scss",
            "sql",
            "sh",
            "bash",
            "zsh",
            "toml",
            "ini",
            "cfg",
            "env",
            "gitignore",
            "dockerignore",
            "dockerfile",
            "makefile",
            "rs",
            "go",
            "java",
            "kt",
            "swift",
            "c",
            "cpp",
            "h",
            "hpp",
            "rb",
            "php",
        }

        ext = FileUtils.get_extension(path).lower()
        if ext in text_extensions:
            return True

        # Check for files without extension
        name = Path(path).name.lower()
        if name in {"dockerfile", "makefile", "jenkinsfile", "vagrantfile"}:
            return True

        return False

    @staticmethod
    def get_language(path: str | Path) -> str:
        """
        Detect programming language from file extension.

        Args:
            path: Path to file

        Returns:
            Language name
        """
        ext_to_lang = {
            "py": "python",
            "js": "javascript",
            "ts": "typescript",
            "tsx": "typescript",
            "jsx": "javascript",
            "json": "json",
            "yaml": "yaml",
            "yml": "yaml",
            "md": "markdown",
            "html": "html",
            "css": "css",
            "scss": "scss",
            "sql": "sql",
            "sh": "bash",
            "bash": "bash",
            "zsh": "zsh",
            "toml": "toml",
            "rs": "rust",
            "go": "go",
            "java": "java",
            "kt": "kotlin",
            "swift": "swift",
            "c": "c",
            "cpp": "cpp",
            "h": "c",
            "hpp": "cpp",
            "rb": "ruby",
            "php": "php",
        }

        ext = FileUtils.get_extension(path).lower()
        return ext_to_lang.get(ext, "text")

    @staticmethod
    def create_code_snippet(
        path: str | Path,
        line: int,
        context_before: int = 3,
        context_after: int = 3,
        max_line_length: int = 100,
    ) -> str:
        """
        Create a code snippet with context around a specific line.

        Args:
            path: Path to file
            line: Target line number (1-indexed)
            context_before: Lines to show before target
            context_after: Lines to show after target
            max_line_length: Maximum characters per line

        Returns:
            Formatted code snippet
        """
        start = max(1, line - context_before)
        end = line + context_after

        lines = FileUtils.read_lines(path, start, end)
        language = FileUtils.get_language(path)

        snippet_lines = []
        for i, content in enumerate(lines, start=start):
            # Truncate long lines
            if len(content) > max_line_length:
                content = content[: max_line_length - 3] + "..."

            # Highlight the target line
            marker = ">>>" if i == line else "   "
            snippet_lines.append(f"{marker} {i:4d} | {content}")

        return f"```{language}\n" + "\n".join(snippet_lines) + "\n```"

    @staticmethod
    def find_files(
        directory: str | Path,
        pattern: str = "*",
        recursive: bool = True,
    ) -> list[Path]:
        """
        Find files matching a pattern.

        Args:
            directory: Directory to search
            pattern: Glob pattern
            recursive: Search recursively

        Returns:
            List of matching file paths
        """
        directory = Path(directory)
        if recursive:
            return list(directory.rglob(pattern))
        return list(directory.glob(pattern))
