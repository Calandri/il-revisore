# API Routes Structure

Defines the FastAPI application's routing layer, separating HTML web views from RESTful API endpoints.

## Files
- **`__init__.py`**: Exports all sub-module routers for centralized inclusion in the main app.
- **`chat.py`**: REST endpoints for managing AI chat sessions, message history, and user interactions.
- **`repos.py`**: REST endpoints for repository lifecycle operations (clone, sync, delete, status).
- **`status.py`**: Health check and diagnostic routes for system uptime and LLM provider connectivity.
- **`tasks.py`**: REST endpoints for creating, queuing, and monitoring background processing tasks.
- **`web.py`**: Frontend routes that render Jinja2 HTML templates for the dashboard and UI pages.

## Key Exports
- `web_router`: Handles UI navigation and template rendering.
- `repos_router`: Manages the `/repos` API namespace.
- `tasks_router`: Manages the `/tasks` API namespace and background execution.
- `chat_router`: Manages the `/chat` API namespace.
- `status_router`: Provides system and service monitoring endpoints.

## Dependencies
- **`..deps`**: Database dependency injection (`get_db`).
- **`..schemas`**: Pydantic models for API request validation and response serialization.
- **`...core`**: Logic for repository management (`RepoManager`) and task queuing (`TaskQueue`).
- **`...db.models`**: SQLAlchemy models for database persistence.
- **`...tasks`**: Task registry and execution context.
- **`...llm`**: LLM clients (Claude/Gemini) used for connectivity health checks.