"""File discovery and filtering utilities."""

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Literal

import tiktoken

# File extensions by type
BE_EXTENSIONS = {".py"}
FE_EXTENSIONS = {".tsx", ".ts", ".jsx", ".js"}


@lru_cache(maxsize=1)
def _get_tokenizer() -> tiktoken.Encoding:
    """Get cached tiktoken encoder.

    Uses cl100k_base encoding (GPT-4/Claude compatible).
    Claude's tokenizer is ~70% similar to cl100k_base.

    Returns:
        tiktoken Encoding instance.
    """
    return tiktoken.get_encoding("cl100k_base")

# Directories to ignore
IGNORE_DIRS = {
    "node_modules", ".git", "__pycache__", ".venv", "venv",
    "dist", "build", ".next", "coverage", ".pytest_cache",
    "eggs", "*.egg-info", ".tox", ".mypy_cache", ".reviews",
    ".turbowrap", "STRUCTURE.md"
}

# Files to ignore
IGNORE_FILES = {"package-lock.json", "pnpm-lock.yaml", "yarn.lock"}


@dataclass
class FileInfo:
    """Information about a discovered file."""
    path: Path
    type: Literal["be", "fe"]
    content: str = ""
    chars: int = 0
    lines: int = 0
    tokens: int = 0


def calculate_tokens(content: str) -> dict[str, int]:
    """Calculate real token count using tiktoken BPE tokenizer.

    Uses cl100k_base encoding which is compatible with GPT-4 and
    approximately 70% similar to Claude's tokenizer.

    Args:
        content: Text content to analyze.

    Returns:
        Dictionary with chars, lines, words, and real token count.
    """
    if not content:
        return {"chars": 0, "lines": 0, "words": 0, "tokens": 0}

    chars = len(content)
    lines = content.count("\n") + 1
    words = len(content.split())

    # Real BPE tokenization
    encoder = _get_tokenizer()
    tokens = len(encoder.encode(content))

    return {
        "chars": chars,
        "lines": lines,
        "words": words,
        "tokens": tokens,
    }


def calculate_tokens_for_file(file_path: Path) -> dict[str, int]:
    """Calculate real token count for a file using tiktoken.

    Args:
        file_path: Path to file.

    Returns:
        Dictionary with file stats and real token count.
    """
    try:
        content = file_path.read_text(encoding="utf-8", errors="ignore")
        return calculate_tokens(content)
    except Exception:
        return {"chars": 0, "lines": 0, "words": 0, "tokens": 0}


def should_ignore(path: Path) -> bool:
    """Check if path should be ignored.

    Args:
        path: Path to check.

    Returns:
        True if path should be ignored.
    """
    for part in path.parts:
        if part in IGNORE_DIRS or part.startswith("."):
            return True
    return path.name in IGNORE_FILES


def discover_files(repo_path: Path) -> tuple[list[FileInfo], list[FileInfo]]:
    """Discover BE and FE files in repository.

    Args:
        repo_path: Path to repository root.

    Returns:
        Tuple of (backend_files, frontend_files).
    """
    be_files: list[FileInfo] = []
    fe_files: list[FileInfo] = []

    for file_path in repo_path.rglob("*"):
        if not file_path.is_file() or should_ignore(file_path):
            continue

        suffix = file_path.suffix.lower()
        rel_path = file_path.relative_to(repo_path)

        if suffix in BE_EXTENSIONS:
            be_files.append(FileInfo(path=rel_path, type="be"))
        elif suffix in FE_EXTENSIONS:
            fe_files.append(FileInfo(path=rel_path, type="fe"))

    return be_files, fe_files


def load_file_content(repo_path: Path, file_info: FileInfo, max_size: int = 8000) -> FileInfo:
    """Load file content into FileInfo with real token calculation.

    Uses tiktoken BPE tokenizer for accurate token counts.

    Args:
        repo_path: Repository root path.
        file_info: FileInfo to populate.
        max_size: Maximum content size in characters.

    Returns:
        FileInfo with content and real token stats populated.
    """
    full_path = repo_path / file_info.path
    try:
        content = full_path.read_text(encoding="utf-8", errors="ignore")

        # Calculate real tokens on full content before truncation
        stats = calculate_tokens(content)
        file_info.chars = stats["chars"]
        file_info.lines = stats["lines"]
        file_info.tokens = stats["tokens"]

        # Store truncated content for context
        file_info.content = content[:max_size]
    except Exception as e:
        file_info.content = f"# Error reading file: {e}"
        file_info.chars = 0
        file_info.lines = 0
        file_info.tokens = 0
    return file_info


def detect_repo_type(be_count: int, fe_count: int) -> str:
    """Detect repository type based on file counts.

    Args:
        be_count: Number of backend files.
        fe_count: Number of frontend files.

    Returns:
        Repository type: "backend", "frontend", or "fullstack".
    """
    if be_count > 0 and fe_count > 0:
        return "fullstack"
    if be_count > 0:
        return "backend"
    if fe_count > 0:
        return "frontend"
    return "unknown"
