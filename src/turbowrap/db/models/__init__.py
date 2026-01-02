"""TurboWrap database models.

This package organizes all SQLAlchemy ORM models by domain:
- base.py: Mixins, enums, and utility functions
- repository.py: Repository and link models
- task.py: Task and AgentRun models
- chat.py: SDK-based chat models
- settings.py: Application settings
- issue.py: Issue and checkpoint models (with Linear integration)
- feature.py: Feature models (multi-repo support)
- linear.py: Linear integration models (legacy, being replaced)
- cli_chat.py: CLI-based chat models
- endpoint.py: API endpoint detection
- database_connection.py: External database connections
- operation.py: Operation tracking
- mockup.py: UI mockup models
"""

# Base classes and utilities
from .base import (
    # Feature enums
    FEATURE_STATUS_TRANSITIONS,
    # Issue enums
    ISSUE_STATUS_TRANSITIONS,
    # Other enums
    DatabaseType,
    EndpointVisibility,
    ExternalLinkType,
    FeatureRepositoryRole,
    FeatureStatus,
    IssueSeverity,
    IssueStatus,
    LinkType,
    OperationStatus,
    OperationType,
    # Mixins and utilities
    SoftDeleteMixin,
    # Test enums
    TestCaseStatus,
    TestFramework,
    TestRunStatus,
    TestSuiteType,
    generate_uuid,
    is_valid_feature_transition,
    is_valid_issue_transition,
)

# Chat models (SDK-based)
from .chat import ChatMessage, ChatSession

# CLI chat models
from .cli_chat import CLIChatMessage, CLIChatSession

# Database connection models
from .database_connection import DatabaseConnection, RepositoryDatabaseConnection

# Diagram models
from .diagram import MermaidDiagram

# Endpoint models
from .endpoint import Endpoint

# Feature models (new architecture)
from .feature import Feature, FeatureRepository

# Issue models (with Linear integration)
from .issue import Issue, ReviewCheckpoint

# Linear integration models (legacy, to be migrated to Feature)
from .linear import LinearIssue, LinearIssueRepositoryLink

# Live View models
from .live_view import LiveViewScreenshot

# Mockup models
from .mockup import Mockup, MockupProject, MockupStatus

# Operation models
from .operation import Operation

# Repository models
from .repository import Repository, RepositoryExternalLink, RepositoryLink

# Settings model
from .settings import Setting

# Task models
from .task import AgentRun, Task

# Test models
from .test import TestCase, TestRun, TestSuite

# User models (RBAC)
from .user import User, UserRepository, UserRole

__all__ = [
    # Base
    "SoftDeleteMixin",
    "generate_uuid",
    # Issue Enums
    "IssueSeverity",
    "IssueStatus",
    "ISSUE_STATUS_TRANSITIONS",
    "is_valid_issue_transition",
    # Feature Enums
    "FeatureStatus",
    "FEATURE_STATUS_TRANSITIONS",
    "is_valid_feature_transition",
    "FeatureRepositoryRole",
    # Test Enums
    "TestSuiteType",
    "TestRunStatus",
    "TestCaseStatus",
    "TestFramework",
    # Other Enums
    "LinkType",
    "ExternalLinkType",
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
    # Issue (with Linear integration)
    "Issue",
    "ReviewCheckpoint",
    # Feature (multi-repo support)
    "Feature",
    "FeatureRepository",
    # Linear (legacy, to be migrated)
    "LinearIssue",
    "LinearIssueRepositoryLink",
    # CLI Chat
    "CLIChatSession",
    "CLIChatMessage",
    # Endpoint
    "Endpoint",
    # Database Connection
    "DatabaseConnection",
    "RepositoryDatabaseConnection",
    # Operation
    "Operation",
    # Live View
    "LiveViewScreenshot",
    # Mockup
    "MockupProject",
    "Mockup",
    "MockupStatus",
    # Test
    "TestSuite",
    "TestRun",
    "TestCase",
    # Diagram
    "MermaidDiagram",
    # User (RBAC)
    "User",
    "UserRepository",
    "UserRole",
]
