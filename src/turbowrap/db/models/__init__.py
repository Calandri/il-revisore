"""TurboWrap database models.

This package organizes all SQLAlchemy ORM models by domain:
- base.py: Mixins, enums, and utility functions
- repository.py: Repository and link models
- task.py: Task and AgentRun models
- chat.py: SDK-based chat models
- settings.py: Application settings
- issue.py: Issue and checkpoint models
- linear.py: Linear integration models
- cli_chat.py: CLI-based chat models
- endpoint.py: API endpoint detection
- database_connection.py: External database connections
- operation.py: Operation tracking
- mockup.py: UI mockup models
"""

# Base classes and utilities
from .base import (
    DatabaseType,
    EndpointVisibility,
    ExternalLinkType,
    IssueSeverity,
    IssueStatus,
    LinkType,
    OperationStatus,
    OperationType,
    SoftDeleteMixin,
    generate_uuid,
)

# Chat models (SDK-based)
from .chat import ChatMessage, ChatSession

# CLI chat models
from .cli_chat import CLIChatMessage, CLIChatSession

# Database connection models
from .database_connection import DatabaseConnection

# Endpoint models
from .endpoint import Endpoint

# Issue models
from .issue import Issue, ReviewCheckpoint

# Linear integration models
from .linear import LinearIssue, LinearIssueRepositoryLink

# Mockup models
from .mockup import Mockup, MockupProject

# Operation models
from .operation import Operation

# Repository models
from .repository import Repository, RepositoryExternalLink, RepositoryLink

# Settings model
from .settings import Setting

# Task models
from .task import AgentRun, Task

__all__ = [
    # Base
    "SoftDeleteMixin",
    "generate_uuid",
    # Enums
    "LinkType",
    "ExternalLinkType",
    "IssueSeverity",
    "IssueStatus",
    "EndpointVisibility",
    "DatabaseType",
    "OperationStatus",
    "OperationType",
    # Repository
    "Repository",
    "RepositoryLink",
    "RepositoryExternalLink",
    # Task
    "Task",
    "AgentRun",
    # Chat (SDK)
    "ChatSession",
    "ChatMessage",
    # Settings
    "Setting",
    # Issue
    "Issue",
    "ReviewCheckpoint",
    # Linear
    "LinearIssue",
    "LinearIssueRepositoryLink",
    # CLI Chat
    "CLIChatSession",
    "CLIChatMessage",
    # Endpoint
    "Endpoint",
    # Database Connection
    "DatabaseConnection",
    # Operation
    "Operation",
    # Mockup
    "MockupProject",
    "Mockup",
]
