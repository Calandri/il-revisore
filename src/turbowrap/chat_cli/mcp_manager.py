"""MCP Server Configuration Manager.

Gestisce la configurazione dei server MCP per Claude CLI.
Supporta:
- CRUD dei server MCP
- Configurazione per-sessione (enable/disable)
- Generazione config per --mcp-config
"""

import json
import logging
from pathlib import Path
from typing import TypedDict

logger = logging.getLogger(__name__)


class MCPServerConfig(TypedDict):
    """Configurazione singolo server MCP."""

    command: str
    args: list[str]
    env: dict[str, str] | None


class MCPServer(TypedDict):
    """Server MCP con metadata."""

    name: str
    command: str
    args: list[str]
    env: dict[str, str] | None
    enabled: bool  # Default enabled status


# Server MCP predefiniti disponibili
DEFAULT_MCP_SERVERS: dict[str, MCPServerConfig] = {
    "linear": {
        "command": "npx",
        "args": ["-y", "@anthropic/linear-mcp"],
        "env": None,
    },
    "github": {
        "command": "npx",
        "args": ["-y", "@anthropic/github-mcp"],
        "env": None,
    },
    "filesystem": {
        "command": "npx",
        "args": ["-y", "@anthropic/filesystem-mcp"],
        "env": None,
    },
    "fetch": {
        "command": "npx",
        "args": ["-y", "@anthropic/fetch-mcp"],
        "env": None,
    },
}


class MCPManager:
    """Manager per configurazione MCP servers.

    Gestisce il file .claude/mcp.json usato da Claude CLI.

    Usage:
        manager = MCPManager()
        manager.add_server("linear", "npx", ["-y", "@anthropic/linear-mcp"])
        config_path = manager.get_config_path()
        # Usa config_path con: claude --mcp-config <path>
    """

    def __init__(self, base_dir: Path | None = None):
        """Initialize MCP Manager.

        Args:
            base_dir: Base directory for .claude folder. Defaults to cwd.
        """
        self._base_dir = base_dir or Path.cwd()
        self._claude_dir = self._base_dir / ".claude"
        self._config_path = self._claude_dir / "mcp.json"
        self._cache: dict[str, MCPServerConfig] | None = None

    @property
    def config_path(self) -> Path:
        """Path to mcp.json config file."""
        return self._config_path

    def ensure_claude_dir(self) -> Path:
        """Ensure .claude directory exists."""
        self._claude_dir.mkdir(parents=True, exist_ok=True)
        return self._claude_dir

    def _load_config(self) -> dict[str, MCPServerConfig]:
        """Load MCP config from file.

        Returns:
            Dictionary of server name -> config
        """
        if self._cache is not None:
            return self._cache

        if not self._config_path.exists():
            self._cache = {}
            return self._cache

        try:
            with open(self._config_path) as f:
                data = json.load(f)

            # Handle both formats:
            # Format 1: {"mcpServers": {...}}
            # Format 2: {"servers": {...}} (our format)
            servers = data.get("mcpServers") or data.get("servers") or {}
            self._cache = servers
            return self._cache

        except (json.JSONDecodeError, OSError) as e:
            logger.error(f"Error loading MCP config: {e}")
            self._cache = {}
            return self._cache

    def _save_config(self, servers: dict[str, MCPServerConfig]) -> bool:
        """Save MCP config to file.

        Args:
            servers: Dictionary of server configurations

        Returns:
            True if saved successfully
        """
        try:
            self.ensure_claude_dir()

            # Use Claude's expected format
            data = {"mcpServers": servers}

            with open(self._config_path, "w") as f:
                json.dump(data, f, indent=2)

            self._cache = servers
            logger.info(f"Saved MCP config with {len(servers)} servers")
            return True

        except OSError as e:
            logger.error(f"Error saving MCP config: {e}")
            return False

    def list_servers(self, include_defaults: bool = True) -> list[MCPServer]:
        """List all configured MCP servers.

        Args:
            include_defaults: Include default servers not yet added

        Returns:
            List of MCPServer objects
        """
        servers = self._load_config()
        result: list[MCPServer] = []

        # Add configured servers
        for name, config in servers.items():
            result.append(
                MCPServer(
                    name=name,
                    command=config["command"],
                    args=config["args"],
                    env=config.get("env"),
                    enabled=True,
                )
            )

        # Add default servers not already configured
        if include_defaults:
            configured_names = set(servers.keys())
            for name, config in DEFAULT_MCP_SERVERS.items():
                if name not in configured_names:
                    result.append(
                        MCPServer(
                            name=name,
                            command=config["command"],
                            args=config["args"],
                            env=config.get("env"),
                            enabled=False,  # Not enabled until explicitly added
                        )
                    )

        return sorted(result, key=lambda s: s["name"])

    def get_server(self, name: str) -> MCPServer | None:
        """Get a specific MCP server config.

        Args:
            name: Server name

        Returns:
            MCPServer if found, None otherwise
        """
        servers = self._load_config()

        if name in servers:
            config = servers[name]
            return MCPServer(
                name=name,
                command=config["command"],
                args=config["args"],
                env=config.get("env"),
                enabled=True,
            )

        # Check defaults
        if name in DEFAULT_MCP_SERVERS:
            config = DEFAULT_MCP_SERVERS[name]
            return MCPServer(
                name=name,
                command=config["command"],
                args=config["args"],
                env=config.get("env"),
                enabled=False,
            )

        return None

    def add_server(
        self,
        name: str,
        command: str,
        args: list[str],
        env: dict[str, str] | None = None,
    ) -> bool:
        """Add or update an MCP server.

        Args:
            name: Server name (identifier)
            command: Command to run (e.g., "npx")
            args: Command arguments
            env: Environment variables (optional)

        Returns:
            True if added successfully
        """
        servers = self._load_config()

        servers[name] = MCPServerConfig(
            command=command,
            args=args,
            env=env,
        )

        return self._save_config(servers)

    def add_default_server(self, name: str) -> bool:
        """Add a default MCP server by name.

        Args:
            name: Name of default server (linear, github, etc.)

        Returns:
            True if added successfully
        """
        if name not in DEFAULT_MCP_SERVERS:
            logger.warning(f"Unknown default MCP server: {name}")
            return False

        config = DEFAULT_MCP_SERVERS[name]
        return self.add_server(
            name=name,
            command=config["command"],
            args=config["args"],
            env=config.get("env"),
        )

    def remove_server(self, name: str) -> bool:
        """Remove an MCP server.

        Args:
            name: Server name

        Returns:
            True if removed successfully
        """
        servers = self._load_config()

        if name not in servers:
            logger.warning(f"MCP server not found: {name}")
            return False

        del servers[name]
        return self._save_config(servers)

    def enable_servers(self, names: list[str]) -> bool:
        """Enable specific servers (add if from defaults).

        Args:
            names: List of server names to enable

        Returns:
            True if all enabled successfully
        """
        success = True
        servers = self._load_config()

        for name in names:
            if name not in servers:
                # Try to add from defaults
                if name in DEFAULT_MCP_SERVERS:
                    if not self.add_default_server(name):
                        success = False
                else:
                    logger.warning(f"Unknown MCP server: {name}")
                    success = False

        return success

    def get_config_path(self, enabled_servers: list[str] | None = None) -> Path | None:
        """Get path to MCP config file.

        If enabled_servers is provided, generates a temporary config
        with only those servers enabled.

        Args:
            enabled_servers: List of server names to include (None = all)

        Returns:
            Path to config file, or None if no servers configured
        """
        servers = self._load_config()

        if not servers:
            return None

        if enabled_servers is None:
            # Return main config path
            if self._config_path.exists():
                return self._config_path
            return None

        # Filter to only enabled servers
        filtered = {
            name: config for name, config in servers.items() if name in enabled_servers
        }

        if not filtered:
            return None

        # Generate temporary config file
        temp_config = self._claude_dir / f"mcp_session.json"
        self.ensure_claude_dir()

        try:
            with open(temp_config, "w") as f:
                json.dump({"mcpServers": filtered}, f, indent=2)
            return temp_config
        except OSError as e:
            logger.error(f"Error creating session MCP config: {e}")
            return None

    def get_available_defaults(self) -> list[str]:
        """Get list of available default MCP server names.

        Returns:
            List of default server names
        """
        return list(DEFAULT_MCP_SERVERS.keys())

    def invalidate_cache(self) -> None:
        """Invalidate cached config (force reload on next access)."""
        self._cache = None


# Singleton instance
_mcp_manager: MCPManager | None = None


def get_mcp_manager(base_dir: Path | None = None) -> MCPManager:
    """Get singleton MCP Manager instance.

    Args:
        base_dir: Base directory (only used on first call)

    Returns:
        MCPManager instance
    """
    global _mcp_manager
    if _mcp_manager is None:
        _mcp_manager = MCPManager(base_dir)
    return _mcp_manager


def reset_mcp_manager() -> None:
    """Reset singleton (for testing)."""
    global _mcp_manager
    _mcp_manager = None
