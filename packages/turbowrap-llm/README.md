# turbowrap-llm

Async Python wrappers for Claude, Gemini, and Grok CLI tools.

## Installation

```bash
# From git
pip install "git+https://github.com/user/ultraWrap.git#subdirectory=packages/turbowrap-llm"

# With extras
pip install "git+https://github.com/user/ultraWrap.git#subdirectory=packages/turbowrap-llm[gemini,s3]"
```

## Quick Start

```python
from turbowrap_llm import ClaudeCLI, GeminiCLI, GrokCLI
from pathlib import Path

# Claude CLI
cli = ClaudeCLI(model="opus", working_dir=Path("./myrepo"))
result = await cli.run("Analyze this code...")
print(result.output)
print(f"Tokens: {result.input_tokens} in, {result.output_tokens} out")

# Gemini CLI
cli = GeminiCLI(model="flash", auto_accept=True)
result = await cli.run("Review this PR...")

# Grok CLI
cli = GrokCLI(model="grok-4-1-fast-reasoning")
result = await cli.run("Explain this function...")
```

## Features

- **Async streaming** - Real-time output with callbacks
- **Session resume** - Continue previous Claude CLI sessions
- **S3 artifacts** - Save prompts/outputs to S3 (optional)
- **Operation tracking** - Inject custom tracker via Protocol
- **Token counting** - Track usage and costs

## ID Management

| ID | Description |
|----|-------------|
| `operation_id` | For tracking operations (generated if not provided) |
| `session_id` | Unique per CLI run (generated if not provided) |
| `resume_id` | Resume a previous Claude session |

```python
# First call
result = await cli.run("Fix this bug...")
print(result.operation_id)  # For tracking
print(result.session_id)    # Save for resume

# Resume later
result = await cli.run(
    "Continue...",
    operation_id=result.operation_id,  # Same tracking
    resume_id=result.session_id,       # Resume session
)
```

## S3 Artifacts (Optional)

```python
from turbowrap_llm.hooks import S3ArtifactSaver

saver = S3ArtifactSaver(bucket="my-bucket", region="us-east-1")
cli = ClaudeCLI(model="sonnet", artifact_saver=saver)

result = await cli.run("Fix this bug...")
print(result.s3_prompt_url)
print(result.s3_output_url)
```

## Operation Tracking (Optional)

```python
from turbowrap_llm.hooks import OperationTracker

class MyTracker(OperationTracker):
    async def progress(
        self,
        operation_id: str,
        status: str,
        session_id: str | None = None,
        details: dict | None = None,
        publish_delay_ms: int = 0,
    ) -> None:
        # Save to your database, publish SSE, etc.
        await my_db.upsert(operation_id, status, details)

cli = ClaudeCLI(model="opus", tracker=MyTracker())
```

## License

MIT
