"""
TurboWrap Chat CLI Package.

Sistema di chat basato su CLI (claude/gemini) invece di SDK.
Supporta multi-chat parallele, agenti custom, MCP servers.
"""

from .models import CLIType, SessionStatus, StreamEventType, AgentInfo, MessageRole
from .agent_loader import AgentLoader, AgentContent, get_agent_loader
from .process_manager import CLIProcessManager, CLIProcess, get_process_manager
from .mcp_manager import MCPManager, MCPServer, get_mcp_manager
from .hooks import ChatHooks, HookRegistry, get_hook_registry, register_hook, trigger_hooks

__all__ = [
    # Models
    "CLIType",
    "SessionStatus",
    "StreamEventType",
    "MessageRole",
    "AgentInfo",
    # Agent Loader
    "AgentLoader",
    "AgentContent",
    "get_agent_loader",
    # Process Manager
    "CLIProcessManager",
    "CLIProcess",
    "get_process_manager",
    # MCP Manager
    "MCPManager",
    "MCPServer",
    "get_mcp_manager",
    # Hooks
    "ChatHooks",
    "HookRegistry",
    "get_hook_registry",
    "register_hook",
    "trigger_hooks",
]
