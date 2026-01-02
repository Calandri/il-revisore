"""Context generation utilities."""

import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def load_structure_documentation(
    repo_path: Path | str,
    workspace_path: str | None = None,
) -> str | None:
    """Load repository structure documentation for context injection.

    Only uses .llms/structure.xml (consolidated XML format, optimized for LLM).
    No fallback to STRUCTURE.md.

    Args:
        repo_path: Path to the repository root
        workspace_path: Optional monorepo workspace subfolder

    Returns:
        Structure documentation content, or None if not found
    """
    base = Path(repo_path)
    if workspace_path:
        workspace_base = base / workspace_path
        if workspace_base.exists():
            base = workspace_base

    # Load .llms/structure.xml (only supported format)
    xml_path = base / ".llms" / "structure.xml"
    if xml_path.exists():
        try:
            content = xml_path.read_text(encoding="utf-8")
            logger.info(f"Loaded structure from {xml_path} ({xml_path.stat().st_size:,} bytes)")
            return content
        except Exception as e:
            logger.warning(f"Failed to read {xml_path}: {e}")

    return None


__all__ = ["load_structure_documentation"]
