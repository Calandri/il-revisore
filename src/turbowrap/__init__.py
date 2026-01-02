"""TurboWrap - AI-Powered Repository Orchestrator."""

__version__ = "0.9.364"
__author__ = "3Bee"

# LLM clients
from turbowrap.llm import AgentResponse, BaseAgent, ClaudeClient, GeminiClient, GeminiProClient

# Review system
from turbowrap.review import ChallengerLoop, Orchestrator, ReportGenerator

__all__ = [
    # Version
    "__version__",
    "__author__",
    # LLM
    "GeminiClient",
    "GeminiProClient",
    "ClaudeClient",
    "BaseAgent",
    "AgentResponse",
    # Review
    "Orchestrator",
    "ChallengerLoop",
    "ReportGenerator",
]
