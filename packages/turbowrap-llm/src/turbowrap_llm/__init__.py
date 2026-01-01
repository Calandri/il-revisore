"""turbowrap-llm: Async Python wrappers for Claude, Gemini, and Grok CLI tools.

Usage:
    from turbowrap_llm import ClaudeCLI, GeminiCLI, GrokCLI

    # Claude
    cli = ClaudeCLI(model="opus")
    result = await cli.run("Analyze this code...")
    print(result.output)
    print(result.session_id)  # For resume

    # Gemini
    cli = GeminiCLI(model="flash")
    result = await cli.run("Review this PR...")

    # Grok
    cli = GrokCLI()
    result = await cli.run("Explain this function...")

With S3 artifacts:
    from turbowrap_llm.hooks import S3ArtifactSaver

    saver = S3ArtifactSaver(bucket="my-bucket")
    cli = ClaudeCLI(model="sonnet", artifact_saver=saver)
    result = await cli.run("Fix this bug...")
    print(result.s3_output_url)

With operation tracking:
    from turbowrap_llm.hooks import OperationTracker

    class MyTracker(OperationTracker):
        async def progress(self, operation_id, status, **kwargs):
            await my_db.upsert(operation_id, status, kwargs)

    cli = ClaudeCLI(tracker=MyTracker())
"""

__version__ = "0.1.0"

# Claude
# Base
from .base import AgentResponse, BaseAgent
from .claude import ClaudeCLI, ClaudeCLIResult, ModelUsage

# Exceptions
from .exceptions import (
    ClaudeError,
    ConfigurationError,
    GeminiError,
    GrokError,
    LLMCLIError,
)

# Gemini
from .gemini import (
    GeminiCLI,
    GeminiClient,
    GeminiCLIResult,
    GeminiProClient,
    GeminiSessionStats,
)

# Grok
from .grok import GrokCLI, GrokCLIResult, GrokSessionStats

__all__ = [
    # Version
    "__version__",
    # Claude
    "ClaudeCLI",
    "ClaudeCLIResult",
    "ModelUsage",
    # Gemini
    "GeminiCLI",
    "GeminiCLIResult",
    "GeminiClient",
    "GeminiProClient",
    "GeminiSessionStats",
    # Grok
    "GrokCLI",
    "GrokCLIResult",
    "GrokSessionStats",
    # Base
    "AgentResponse",
    "BaseAgent",
    # Exceptions
    "LLMCLIError",
    "ClaudeError",
    "GeminiError",
    "GrokError",
    "ConfigurationError",
]
