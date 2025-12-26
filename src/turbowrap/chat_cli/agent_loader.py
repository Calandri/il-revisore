"""
Agent Loader - Carica agenti Claude da /agents/ directory.

Gli agenti sono file Markdown con frontmatter YAML:

```yaml
---
name: fixer
version: "2025-12-25"
tokens: 800
description: |
  Code fixer agent description...
model: claude-opus-4-5-20251101
color: green
---

Agent instructions in markdown...
```
"""

import logging
import re
from pathlib import Path
from typing import NamedTuple

import yaml

from .models import AgentInfo

logger = logging.getLogger(__name__)

# Default agents directory (relative to project root)
DEFAULT_AGENTS_DIR = "agents"


class AgentContent(NamedTuple):
    """Agent content with metadata and instructions."""

    info: AgentInfo
    instructions: str  # Markdown content after frontmatter


class AgentLoader:
    """Carica e gestisce agenti Claude da directory.

    Usage:
        loader = AgentLoader()
        agents = loader.list_agents()
        agent = loader.get_agent("fixer")
        path = loader.get_agent_path("fixer")
    """

    def __init__(self, agents_dir: Path | str | None = None):
        """Initialize loader.

        Args:
            agents_dir: Path to agents directory. If None, uses project root /agents/
        """
        if agents_dir is None:
            # Find project root (where pyproject.toml is)
            current = Path(__file__).resolve()
            for parent in current.parents:
                if (parent / "pyproject.toml").exists():
                    agents_dir = parent / DEFAULT_AGENTS_DIR
                    break
            else:
                agents_dir = Path.cwd() / DEFAULT_AGENTS_DIR

        self.agents_dir = Path(agents_dir)
        self._cache: dict[str, AgentContent] = {}

    def _parse_frontmatter(self, content: str) -> tuple[dict, str]:
        """Parse YAML frontmatter from markdown content.

        Args:
            content: Full markdown content with frontmatter

        Returns:
            Tuple of (metadata dict, remaining content)
        """
        # Match YAML frontmatter between --- delimiters
        pattern = r"^---\s*\n(.*?)\n---\s*\n(.*)$"
        match = re.match(pattern, content, re.DOTALL)

        if not match:
            return {}, content

        try:
            metadata = yaml.safe_load(match.group(1)) or {}
            instructions = match.group(2).strip()
            return metadata, instructions
        except yaml.YAMLError as e:
            logger.warning(f"Failed to parse YAML frontmatter: {e}")
            return {}, content

    def _load_agent(self, path: Path) -> AgentContent | None:
        """Load single agent from file.

        Args:
            path: Path to agent markdown file

        Returns:
            AgentContent or None if invalid
        """
        try:
            content = path.read_text(encoding="utf-8")
            metadata, instructions = self._parse_frontmatter(content)

            # Validate required fields
            name = metadata.get("name")
            if not name:
                name = path.stem  # Use filename as fallback

            info: AgentInfo = {
                "name": name,
                "version": str(metadata.get("version", "unknown")),
                "tokens": int(metadata.get("tokens", 0)),
                "description": metadata.get("description", "").strip(),
                "model": metadata.get("model", "claude-opus-4-5-20251101"),
                "color": metadata.get("color", "blue"),
                "path": str(path.absolute()),
            }

            return AgentContent(info=info, instructions=instructions)

        except Exception as e:
            logger.error(f"Failed to load agent {path}: {e}")
            return None

    def list_agents(self, reload: bool = False) -> list[AgentInfo]:
        """List all available agents.

        Args:
            reload: Force reload from disk

        Returns:
            List of AgentInfo dicts
        """
        if reload:
            self._cache.clear()

        if not self.agents_dir.exists():
            logger.warning(f"Agents directory not found: {self.agents_dir}")
            return []

        agents: list[AgentInfo] = []

        for path in sorted(self.agents_dir.glob("*.md")):
            # Skip symlinks (legacy agents)
            if path.is_symlink():
                continue

            name = path.stem
            if name not in self._cache:
                agent = self._load_agent(path)
                if agent:
                    self._cache[name] = agent

            if name in self._cache:
                agents.append(self._cache[name].info)

        return agents

    def get_agent(self, name: str) -> AgentContent | None:
        """Get agent by name.

        Args:
            name: Agent name (without .md extension)

        Returns:
            AgentContent or None if not found
        """
        # Try cache first
        if name in self._cache:
            return self._cache[name]

        # Try loading from disk
        path = self.agents_dir / f"{name}.md"
        if not path.exists():
            logger.warning(f"Agent not found: {name}")
            return None

        agent = self._load_agent(path)
        if agent:
            self._cache[name] = agent
        return agent

    def get_agent_path(self, name: str) -> Path | None:
        """Get absolute path to agent file.

        Args:
            name: Agent name (without .md extension)

        Returns:
            Path or None if not found
        """
        path = self.agents_dir / f"{name}.md"
        if path.exists():
            return path.absolute()
        return None

    def get_agent_instructions(self, name: str) -> str | None:
        """Get agent instructions (markdown content after frontmatter).

        Args:
            name: Agent name

        Returns:
            Markdown instructions or None
        """
        agent = self.get_agent(name)
        if agent:
            return agent.instructions
        return None


# Singleton instance
_loader: AgentLoader | None = None


def get_agent_loader() -> AgentLoader:
    """Get singleton AgentLoader instance."""
    global _loader
    if _loader is None:
        _loader = AgentLoader()
    return _loader
