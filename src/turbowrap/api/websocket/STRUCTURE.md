# WebSocket API Module

**Purpose**: Manages real-time, bi-directional chat communication and LLM interaction via WebSockets.

**Files**:
- `__init__.py`: Package entry point that exports the primary chat handler.
- `chat_handler.py`: Implements WebSocket lifecycle management, message persistence, and AI response handling.

**Key Exports**:
- `ChatWebSocketHandler`: Class responsible for accepting connections, validating sessions, and processing messages.

**Dependencies**:
- `turbowrap.db.models`: Accesses `ChatSession` and `ChatMessage` for persistence.
- `turbowrap.llm`: Utilizes `ClaudeClient` for generating AI responses.
- `fastapi`: Provides `WebSocket` and connection management tools.
- `sqlalchemy`: Handles database session querying and commits.