# API Schemas Structure

Data validation and serialization models for the Turbowrap API using Pydantic.

## Files
- **tasks.py**: Models for background task creation, progress tracking, and queue status.
- **repos.py**: Models for GitHub repository management, cloning requests, and status reporting.
- **chat.py**: Models for chat sessions, message history, and WebSocket communication.
- **__init__.py**: Module entry point exposing the public schema interface.

## Key Classes
- **Repository**: `RepoCreate`, `RepoResponse`, `RepoStatus`
- **Tasks**: `TaskCreate`, `TaskResponse`, `TaskQueueStatus`
- **Chat**: `ChatSessionResponse`, `ChatMessageCreate`, `WebSocketMessage`

## Dependencies
- **pydantic**: Base validation and settings management.
- **datetime**: Temporal fields for timestamps.
- **typing**: Type hinting and literals.