# TurboWrap Errors

Intelligent error handling for FastAPI with frontend integration.

## Installation

```bash
pip install turbowrap-errors
```

## Quick Start

### 1. Add Middleware (Recommended)

```python
from fastapi import FastAPI
from turbowrap_errors import TurboWrapMiddleware

app = FastAPI()
app.add_middleware(TurboWrapMiddleware)
```

All unhandled exceptions will now be formatted as structured JSON:

```json
{
  "turbo_error": true,
  "command": "GET /api/users/123",
  "severity": "error",
  "error": {
    "message": "User not found",
    "code": "NOT_FOUND",
    "type": "NotFoundError"
  },
  "context": {
    "method": "GET",
    "path": "/api/users/123"
  },
  "timestamp": "2024-12-30T12:00:00Z"
}
```

### 2. Use Decorator

```python
from turbowrap_errors import turbo_wrap, TurboWrapError

@router.get("/users/{user_id}")
@turbo_wrap("Fetch User")
async def get_user(user_id: str):
    user = await db.get_user(user_id)
    if not user:
        raise TurboWrapError(
            "User not found",
            code="USER_404",
            http_status=404
        )
    return user
```

### 3. Use Context Manager

```python
from turbowrap_errors import turbo_wrap

async def complex_operation():
    async with turbo_wrap.context("Complex Operation") as ctx:
        ctx.add_context(step="initialization")
        await step1()

        ctx.add_context(step="processing")
        await step2()
```

## Error Severity

Errors have three severity levels that determine frontend display:

| Severity | Frontend Display | Use Case |
|----------|------------------|----------|
| `warning` | Toast notification | Recoverable errors (validation, not found) |
| `error` | Modal dialog | User action needed (auth, permission) |
| `critical` | Modal + monitoring | System errors (database, connection) |

```python
from turbowrap_errors import TurboWrapError, ErrorSeverity

# Warning - shows toast
raise TurboWrapError(
    "Email format invalid",
    severity=ErrorSeverity.WARNING
)

# Error - shows modal
raise TurboWrapError(
    "Please login first",
    severity=ErrorSeverity.ERROR
)

# Critical - shows modal + logs
raise TurboWrapError(
    "Database connection failed",
    severity=ErrorSeverity.CRITICAL
)
```

## Convenience Exceptions

```python
from turbowrap_errors import (
    NotFoundError,
    ValidationError,
    AuthenticationError,
    AuthorizationError,
    DatabaseError,
)

# 404 Not Found (warning severity)
raise NotFoundError("User not found")

# 422 Validation Error (warning severity)
raise ValidationError("Invalid email format")

# 401 Unauthorized (error severity)
raise AuthenticationError("Token expired")

# 403 Forbidden (error severity)
raise AuthorizationError("Admin access required")

# 500 Database Error (critical severity)
raise DatabaseError("Connection pool exhausted")
```

## Middleware Options

```python
from turbowrap_errors import TurboWrapMiddleware

app.add_middleware(
    TurboWrapMiddleware,
    log_errors=True,           # Log to console (default: True)
    include_traceback=False,   # Include stack trace in response (default: False)
    on_error=my_error_handler, # Custom callback for monitoring
)

# Custom error handler
def my_error_handler(error: TurboWrapError, request: Request):
    # Send to Sentry, DataDog, etc.
    sentry_sdk.capture_exception(error)
```

## Frontend Integration

The error response format is designed to work with the TurboWrap frontend error handler:

```javascript
// Frontend (already included in TurboWrap)
document.body.addEventListener('htmx:responseError', function(evt) {
    const response = JSON.parse(evt.detail.xhr.responseText);
    if (response.turbo_error) {
        TurboWrapError.handle(response.command, response.error, response.context);
    }
});
```

## License

MIT
