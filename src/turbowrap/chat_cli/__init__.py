"""
TurboWrap Chat CLI Package.

Sistema di chat basato su CLI (claude/gemini) invece di SDK.
Supporta multi-chat parallele, agenti custom, MCP servers.
"""

from ..utils.hooks import HookRegistry, get_hook_registry, register_hook, trigger_hooks
from .agent_loader import AgentContent, AgentLoader, get_agent_loader
from .context_generator import (
    generate_context,
    get_cached_context,
    get_context_for_session,
    invalidate_context_cache,
    save_context_file,
)
from .hooks import ChatHooks
from .mcp_manager import MCPManager, MCPServer, get_mcp_manager
from .models import AgentInfo, CLIType, MessageRole, SessionStatus, StreamEventType
from .process_manager import CLIProcess, CLIProcessManager, get_process_manager

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
    # Context Generator
    "generate_context",
    "get_context_for_session",
    "get_cached_context",
    "save_context_file",
    "invalidate_context_cache",
]
