"""Auto-update module for TurboWrap.

This module provides a 4-step workflow to:
1. Analyze codebase functionalities
2. Research competitors and best practices
3. Evaluate and propose new features
4. Create Linear issues with human-in-the-loop questions
"""

from .config import AutoUpdateSettings, get_autoupdate_settings
from .models import (
    AutoUpdateRun,
    CreatedIssue,
    Functionality,
    ProposedFeature,
    RejectedFeature,
    ResearchResult,
    Step1Checkpoint,
    Step2Checkpoint,
    Step3Checkpoint,
    Step4Checkpoint,
    StepStatus,
)
from .orchestrator import AutoUpdateOrchestrator

__all__ = [
    # Orchestrator
    "AutoUpdateOrchestrator",
    # Config
    "AutoUpdateSettings",
    "get_autoupdate_settings",
    # Models
    "AutoUpdateRun",
    "StepStatus",
    "Functionality",
    "Step1Checkpoint",
    "ResearchResult",
    "Step2Checkpoint",
    "ProposedFeature",
    "RejectedFeature",
    "Step3Checkpoint",
    "CreatedIssue",
    "Step4Checkpoint",
]
