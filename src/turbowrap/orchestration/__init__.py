"""
Shared orchestration utilities for TurboWrap.

This package provides common patterns and utilities used across
the review, fix, and auto-update orchestrators:

- report_utils: Issue deduplication, prioritization, scoring
- checkpoint: Generic checkpoint management (S3 + local)
- progress: Unified progress callback types
- cli_runner: Claude and Gemini CLI wrappers
- base: BaseOrchestrator abstract class
"""

# Report utilities
# Base orchestrator
from turbowrap.orchestration.base import BaseOrchestrator

# Checkpoint management
from turbowrap.orchestration.checkpoint import CheckpointManager

# CLI runners
from turbowrap.orchestration.cli_runner import (
    ClaudeCLI,
    ClaudeCLIResult,
    CLIRunner,
    GeminiCLI,
    GeminiCLIResult,
    ModelUsage,
)

# Progress types
from turbowrap.orchestration.progress import (
    BaseProgressEvent,
    ProgressCallback,
    ProgressEmitter,
)
from turbowrap.orchestration.report_utils import (
    CATEGORY_MULTIPLIERS,
    SEVERITY_DEDUCTIONS,
    SEVERITY_RANKS,
    build_next_steps,
    calculate_overall_score,
    calculate_priority_score,
    calculate_recommendation,
    count_by_severity,
    deduplicate_issues,
    get_severity_rank,
    prioritize_issues,
    process_issues,
)

__all__ = [
    # report_utils
    "SEVERITY_RANKS",
    "SEVERITY_DEDUCTIONS",
    "CATEGORY_MULTIPLIERS",
    "get_severity_rank",
    "deduplicate_issues",
    "calculate_priority_score",
    "prioritize_issues",
    "calculate_overall_score",
    "count_by_severity",
    "calculate_recommendation",
    "build_next_steps",
    "process_issues",
    # checkpoint
    "CheckpointManager",
    # progress
    "BaseProgressEvent",
    "ProgressCallback",
    "ProgressEmitter",
    # cli_runner
    "CLIRunner",
    "ClaudeCLI",
    "ClaudeCLIResult",
    "GeminiCLI",
    "GeminiCLIResult",
    "ModelUsage",
    # base
    "BaseOrchestrator",
]
