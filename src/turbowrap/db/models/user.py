"""User models for RBAC (Role-Based Access Control)."""

from enum import Enum

from sqlalchemy import Column, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.orm import relationship

from turbowrap.db.base import Base

from .base import TZDateTime, generate_uuid, now_utc


class UserRole(str, Enum):
    """User roles for RBAC.

    Hierarchy:
    - ADMIN: Full access to everything
    - CODER: Can fix issues, review code, commit. Limited to assigned repos.
    - MOCKUPPER: Can create mockups, view issues. Limited to assigned repos.
    """

    ADMIN = "admin"
    CODER = "coder"
    MOCKUPPER = "mockupper"


class User(Base):
    """TurboWrap user with role assignment.

    Links to AWS Cognito via cognito_sub (the 'sub' claim from JWT).
    Stores local role information since Cognito doesn't handle roles.

    Users are auto-provisioned on first login with default role (CODER).
    """

    __tablename__ = "users"

    id = Column(String(36), primary_key=True, default=generate_uuid)

    # Link to Cognito
    cognito_sub = Column(String(255), nullable=False, unique=True, index=True)
    email = Column(String(255), nullable=True, index=True)

    # Role assignment
    role = Column(String(20), nullable=False, default=UserRole.CODER.value)

    # Timestamps
    created_at = Column(TZDateTime(), default=now_utc)
    updated_at = Column(TZDateTime(), default=now_utc, onupdate=now_utc)

    # Relationships
    repository_access = relationship(
        "UserRepository",
        back_populates="user",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        Index("idx_users_email", "email"),
        Index("idx_users_role", "role"),
        {"extend_existing": True},
    )

    def __repr__(self) -> str:
        return f"<User {self.email or self.cognito_sub[:8]} ({self.role})>"

    @property
    def is_admin(self) -> bool:
        """Check if user has admin role."""
        return self.role == UserRole.ADMIN.value


class UserRepository(Base):
    """Links Users to Repositories for access control.

    Only applies to Coder and Mockupper roles.
    Admins have implicit access to all repositories.

    This is a many-to-many join table between User and Repository.
    """

    __tablename__ = "user_repositories"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    user_id = Column(
        String(36),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    repository_id = Column(
        String(36),
        ForeignKey("repositories.id", ondelete="CASCADE"),
        nullable=False,
    )

    # Timestamps
    created_at = Column(TZDateTime(), default=now_utc)

    # Relationships
    user = relationship("User", back_populates="repository_access")
    repository = relationship("Repository")

    __table_args__ = (
        Index("idx_user_repos_user", "user_id"),
        Index("idx_user_repos_repo", "repository_id"),
        UniqueConstraint("user_id", "repository_id", name="uq_user_repository"),
        {"extend_existing": True},
    )

    def __repr__(self) -> str:
        return f"<UserRepository user={self.user_id[:8]} repo={self.repository_id[:8]}>"
