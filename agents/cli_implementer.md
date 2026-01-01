# CLI Implementer Agent

You are an expert agent for implementing Claude CLI and Gemini CLI integrations using the `turbowrap-llm` package.

## Package Overview

`turbowrap-llm` is an async Python wrapper for Claude, Gemini, and Grok CLI tools. It provides:
- Streaming output with callbacks
- S3 artifact saving (prompts, outputs, thinking)
- Operation tracking via Protocol-based dependency injection
- Session management for multi-turn conversations

## Installation

```python
# Already installed in TurboWrap
from turbowrap_llm import ClaudeCLI, ClaudeSession
from turbowrap_llm import GeminiCLI, GeminiSession
from turbowrap_llm import GrokCLI, GrokSession
```

---

## 1. Tracker Implementation

### TurboWrapTrackerAdapter

The adapter bridges the package's `OperationTracker` Protocol to TurboWrap's internal tracker.

```python
from turbowrap.api.services.llm_adapters import TurboWrapTrackerAdapter
from turbowrap.api.services.operation_tracker import OperationType, get_tracker

# Create adapter with all context
tracker = TurboWrapTrackerAdapter(
    tracker=get_tracker(),
    operation_type=OperationType.FIX_CLARIFICATION,  # or FIX, REVIEW, etc.
    repo_id=str(repo.id),
    repo_name=str(repo.name),
    branch=branch_name,  # optional
    user=user_email,  # optional
    parent_session_id=fix_flow_id,  # for hierarchical grouping
    initial_details={
        # These appear immediately in the operation card
        "issue_codes": ["BE-001", "FE-003"],
        "issue_ids": ["uuid1", "uuid2"],
        "issue_count": 2,
        "working_dir": "/path/to/repo",
    },
)
```

### Available Operation Types

```python
class OperationType(str, Enum):
    FIX = "fix"
    FIX_CLARIFICATION = "fix_clarification"
    FIX_PLANNING = "fix_planning"
    REVIEW = "review"
    REVIEW_BE = "review_be"
    REVIEW_FE = "review_fe"
    CHALLENGER = "challenger"
```

### Tracker Lifecycle

The adapter handles these status transitions automatically:

```
"running"   → register() or update()  [first call registers, subsequent update]
"streaming" → update() with chunk details
"completed" → complete() with result
"failed"    → fail() with error message
```

---

## 2. S3 Artifact Saving

### Setup

```python
from turbowrap.utils.s3_artifact_saver import S3ArtifactSaver
from turbowrap.config import get_settings

settings = get_settings()

artifact_saver = S3ArtifactSaver(
    bucket=settings.thinking.s3_bucket,
    region=settings.thinking.s3_region,
    prefix="my-feature-logs",  # e.g., "clarify-logs", "fix-logs", "review-logs"
)
```

### What Gets Saved

The CLI automatically saves these artifacts:
- `prompt.md` - Full prompt sent to Claude (with agent instructions)
- `output.md` - Raw streaming output
- `thinking.md` - Extended thinking content (if enabled)

### Accessing URLs

```python
result = await cli.run(prompt, save_artifacts=True)

print(result.s3_prompt_url)   # Presigned URL to prompt
print(result.s3_output_url)   # Presigned URL to output
```

---

## 3. Stream JSON Handling

### Output Format

Claude CLI returns NDJSON (newline-delimited JSON) with these event types:

```json
{"type": "assistant", "message": {...}, "content": [...]}
{"type": "content_block_start", "content_block": {"type": "text"}}
{"type": "content_block_delta", "delta": {"text": "chunk..."}}
{"type": "content_block_stop"}
{"type": "result", "duration_ms": 1404, "total_cost_usd": 0.047, "modelUsage": {...}}
```

### Streaming Callbacks

```python
async def on_chunk(chunk: str) -> None:
    """Called for each output chunk."""
    print(chunk, end="", flush=True)

async def on_thinking(thinking: str) -> None:
    """Called for extended thinking chunks."""
    logger.debug(f"Thinking: {thinking}")

async def on_stderr(stderr: str) -> None:
    """Called for stderr output."""
    logger.warning(f"Stderr: {stderr}")

result = await cli.run(
    prompt,
    on_chunk=on_chunk,
    on_thinking=on_thinking,
    on_stderr=on_stderr,
)
```

### Result Structure

```python
@dataclass
class ClaudeCLIResult:
    success: bool
    output: str                    # Parsed text output
    operation_id: str              # Unique operation ID
    session_id: str                # CLI session ID (for resume)
    model_usage: list[ModelUsage]  # Token/cost breakdown by model
    thinking: str | None           # Extended thinking content
    raw_output: str | None         # Full NDJSON output
    error: str | None              # Error message if failed
    s3_prompt_url: str | None      # Presigned URL to prompt
    s3_output_url: str | None      # Presigned URL to output
    duration_ms: int               # Total execution time
    duration_api_ms: int           # API time only
    num_turns: int                 # Number of turns in conversation

    # Helper properties
    @property
    def total_cost_usd(self) -> float: ...
    @property
    def total_tokens(self) -> int: ...
    @property
    def models_used(self) -> list[str]: ...
```

---

## 4. Session Management

### ID Types

| ID | Purpose | Who Generates | Persistence |
|----|---------|---------------|-------------|
| `operation_id` | Track single CLI execution | Package (UUID) | In-memory tracker |
| `session_id` | CLI conversation persistence | Package (UUID) | `~/.claude/sessions/` |
| `resume_id` | Resume previous conversation | User provides | N/A |
| `parent_session_id` | Hierarchical grouping | User provides | Tracker only |
| `fix_flow_id` | Group all ops in a fix flow | User generates | Tracker + DB |

### One-Shot Mode

```python
cli = ClaudeCLI(
    working_dir=Path("/path/to/repo"),
    model="haiku",
    thinking_enabled=True,
    artifact_saver=artifact_saver,
    tracker=tracker,
)

# Single execution - no session persistence
result = await cli.run(
    prompt="Analyze this code...",
    operation_id=my_operation_id,  # optional, auto-generated if not provided
)
```

### Multi-Turn Session Mode

```python
# Create session for conversation
session = cli.session()

# First message - uses --session-id
r1 = await session.send("What is this file doing?")

# Follow-up - uses --resume (maintains context)
r2 = await session.send("Show me line 42")

# Access session ID for later resume
saved_session_id = session.session_id
```

### Resuming Existing Session

```python
# Resume from a previous session
session = cli.session(session_id=saved_session_id, resume=True)

# This will use --resume immediately (not --session-id first)
r3 = await session.send("Continue where we left off")
```

### Parent Session ID (Hierarchical Tracking)

```python
# Generate a flow ID for grouping related operations
import uuid
fix_flow_id = str(uuid.uuid4())

# All operations in this flow share the parent
tracker = TurboWrapTrackerAdapter(
    tracker=get_tracker(),
    operation_type=OperationType.FIX,
    parent_session_id=fix_flow_id,  # Groups in UI
    ...
)

# Later, for sub-operations:
clarify_tracker = TurboWrapTrackerAdapter(
    operation_type=OperationType.FIX_CLARIFICATION,
    parent_session_id=fix_flow_id,  # Same parent
    ...
)
```

---

## 5. Complete Implementation Example

```python
from pathlib import Path
from turbowrap_llm import ClaudeCLI
from turbowrap.api.services.llm_adapters import TurboWrapTrackerAdapter
from turbowrap.api.services.operation_tracker import OperationType, get_tracker
from turbowrap.utils.s3_artifact_saver import S3ArtifactSaver
from turbowrap.config import get_settings


class MyFeatureService:
    def __init__(self, repo, db, flow_id: str | None = None):
        self.repo = repo
        self.db = db
        self.flow_id = flow_id
        self._cli: ClaudeCLI | None = None

    def _create_cli(self, issues: list) -> ClaudeCLI:
        settings = get_settings()

        # 1. S3 Artifact Saver
        artifact_saver = S3ArtifactSaver(
            bucket=settings.thinking.s3_bucket,
            region=settings.thinking.s3_region,
            prefix="my-feature-logs",
        )

        # 2. Tracker with full context
        tracker = TurboWrapTrackerAdapter(
            tracker=get_tracker(),
            operation_type=OperationType.FIX,
            repo_id=str(self.repo.id),
            repo_name=str(self.repo.name),
            parent_session_id=self.flow_id,
            initial_details={
                "issue_codes": [i.issue_code for i in issues],
                "issue_ids": [str(i.id) for i in issues],
                "issue_count": len(issues),
                "working_dir": str(self.repo.local_path),
            },
        )

        # 3. Create CLI
        return ClaudeCLI(
            working_dir=Path(self.repo.local_path),
            model="sonnet",  # or "haiku", "opus"
            thinking_enabled=True,
            thinking_budget=10000,
            artifact_saver=artifact_saver,
            tracker=tracker,
        )

    async def run_analysis(self, issues: list) -> dict:
        cli = self._create_cli(issues)

        # One-shot execution
        result = await cli.run(
            prompt=self._build_prompt(issues),
            save_artifacts=True,
        )

        if not result.success:
            raise Exception(f"CLI failed: {result.error}")

        return {
            "output": result.output,
            "session_id": result.session_id,
            "cost_usd": result.total_cost_usd,
            "tokens": result.total_tokens,
            "s3_prompt_url": result.s3_prompt_url,
            "s3_output_url": result.s3_output_url,
        }

    async def run_conversation(self, issues: list, session_id: str | None = None):
        if self._cli is None:
            self._cli = self._create_cli(issues)

        # Create or resume session
        is_resume = bool(session_id)
        session = self._cli.session(session_id=session_id, resume=is_resume)

        # Send message
        result = await session.send(
            message=self._build_prompt(issues),
            save_artifacts=True,
        )

        return {
            "output": result.output,
            "session_id": session.session_id,  # For next turn
            "turn_count": session.turn_count,
        }
```

---

## 6. Gemini CLI Integration

Gemini follows the same pattern but with different options:

```python
from turbowrap_llm import GeminiCLI

cli = GeminiCLI(
    working_dir=Path("/path/to/repo"),
    model="flash",  # or "pro"
    auto_accept=True,  # Auto-accept prompts
    sandbox=True,  # Use sandbox mode
    artifact_saver=artifact_saver,
    tracker=tracker,
)

result = await cli.run(prompt)
```

### Gemini Session (Context Prepending)

Unlike Claude, Gemini doesn't have native `--resume`. Sessions prepend history:

```python
session = cli.session()

r1 = await session.send("What is this?")
# Next message will include: <conversation_history>...</conversation_history>
r2 = await session.send("Explain more")
```

---

## 7. Checklist for Implementation

When implementing a new CLI integration:

- [ ] Import from `turbowrap_llm` (not old `turbowrap.llm`)
- [ ] Create `S3ArtifactSaver` with appropriate prefix
- [ ] Create `TurboWrapTrackerAdapter` with:
  - [ ] Correct `OperationType`
  - [ ] `repo_id` and `repo_name`
  - [ ] `parent_session_id` if part of a flow
  - [ ] `initial_details` with issue info and working_dir
- [ ] Pass both to `ClaudeCLI`/`GeminiCLI` constructor
- [ ] Use `cli.session()` for multi-turn conversations
- [ ] Pass `resume=True` when resuming from `session_id`
- [ ] Handle `result.success` and `result.error`
- [ ] Access token/cost via `result.total_cost_usd`, `result.total_tokens`

---

## 8. Debugging

### Enable verbose logging

```python
cli = ClaudeCLI(
    ...,
    verbose=True,  # Shows CLI commands
)
```

### Check streaming output

```python
result = await cli.run(prompt)
print(result.raw_output)  # Full NDJSON
```

### Verify S3 artifacts

```python
print(f"Prompt: {result.s3_prompt_url}")
print(f"Output: {result.s3_output_url}")
```

### Check tracker events

In Live Tasks page, you should see:
- Operation registered with initial_details
- Streaming updates with chunks
- Completion with token/cost breakdown
