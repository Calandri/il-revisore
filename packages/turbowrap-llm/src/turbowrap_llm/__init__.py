"""turbowrap-llm: Async Python wrappers for Claude, Gemini, and Grok CLI tools.

Usage:
    from turbowrap_llm import ClaudeCLI, GeminiCLI, GrokCLI

    # Claude - One-shot mode
    cli = ClaudeCLI(model="opus")
    result = await cli.run("Analyze this code...")
    print(result.output)
    print(result.session_id)  # For resume

    # Claude - Conversational mode (multi-turn)
    async with cli.session() as session:
        r1 = await session.send("What is Python?")
        r2 = await session.send("Show me an example")  # Remembers context

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

# Base
from .base import AgentResponse, BaseAgent, ConversationMessage, ConversationSession

# Claude
from .claude import ClaudeCLI, ClaudeCLIResult, ClaudeSession, ModelUsage

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
    GeminiSession,
    GeminiSessionStats,
)

# Grok
from .grok import GrokCLI, GrokCLIResult, GrokSession, GrokSessionStats

__all__ = [
    # Version
    "__version__",
    # Claude
    "ClaudeCLI",
    "ClaudeCLIResult",
    "ClaudeSession",
    "ModelUsage",
    # Gemini
    "GeminiCLI",
    "GeminiCLIResult",
    "GeminiClient",
    "GeminiProClient",
    "GeminiSession",
    "GeminiSessionStats",
    # Grok
    "GrokCLI",
    "GrokCLIResult",
    "GrokSession",
    "GrokSessionStats",
    # Base
    "AgentResponse",
    "BaseAgent",
    "ConversationMessage",
    "ConversationSession",
    # Exceptions
    "LLMCLIError",
    "ClaudeError",
    "GeminiError",
    "GrokError",
    "ConfigurationError",
]
