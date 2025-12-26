"""
Chat CLI Models - Tipi base e enum per il sistema chat CLI.

Questo modulo contiene le definizioni di tipo condivise tra tutti i
componenti del sistema chat CLI.
"""

from enum import Enum
from typing import TypedDict


class CLIType(str, Enum):
    """Tipi di CLI supportati."""

    CLAUDE = "claude"
    GEMINI = "gemini"


class SessionStatus(str, Enum):
    """Stati possibili di una sessione chat."""

    IDLE = "idle"  # Sessione creata, CLI non avviato
    STARTING = "starting"  # CLI in avvio
    RUNNING = "running"  # CLI attivo e pronto
    STREAMING = "streaming"  # CLI sta generando risposta
    STOPPING = "stopping"  # CLI in chiusura
    ERROR = "error"  # Errore nel CLI
    COMPLETED = "completed"  # Sessione completata


class StreamEventType(str, Enum):
    """Tipi di eventi SSE per lo streaming."""

    # Lifecycle events
    START = "start"  # Inizio stream
    DONE = "done"  # Fine stream
    ERROR = "error"  # Errore

    # Content events
    CHUNK = "chunk"  # Token di contenuto
    THINKING = "thinking"  # Token di extended thinking

    # Status events
    STATUS = "status"  # Cambio stato sessione
    TYPING = "typing"  # Indicatore di digitazione


class MessageRole(str, Enum):
    """Ruoli dei messaggi nella chat."""

    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"


class AgentInfo(TypedDict):
    """Informazioni su un agente Claude."""

    name: str
    version: str
    tokens: int
    description: str
    model: str
    color: str
    path: str


class MCPServerConfig(TypedDict):
    """Configurazione di un MCP server."""

    command: str
    args: list[str]
    env: dict[str, str] | None


class MCPServersDict(TypedDict):
    """Dizionario di MCP servers."""

    mcpServers: dict[str, MCPServerConfig]
