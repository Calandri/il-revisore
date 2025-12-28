"""Endpoint detection model."""

from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship

from turbowrap.db.base import Base

from .base import EndpointVisibility, generate_uuid


class Endpoint(Base):
    """API endpoint detected in a repository.

    Stores endpoint metadata with unique constraint on (repository_id, method, path).
    Running detection multiple times will update existing endpoints, not duplicate.
    """

    __tablename__ = "endpoints"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    repository_id = Column(String(36), ForeignKey("repositories.id"), nullable=False)

    # Endpoint identification (unique per repo)
    method = Column(String(10), nullable=False)  # GET, POST, PUT, DELETE, PATCH
    path = Column(String(500), nullable=False)  # /api/v1/users

    # Source location
    file = Column(String(500), nullable=True)  # src/routes/users.py
    line = Column(Integer, nullable=True)  # Line number in file

    # Documentation
    description = Column(Text, nullable=True)  # What the endpoint does
    response_type = Column(String(255), nullable=True)  # List[User], UserResponse, etc.
    tags = Column(JSON, nullable=True)  # ["users", "admin"]

    # Parameters stored as JSON array
    parameters = Column(
        JSON, nullable=True
    )  # [{name, param_type, data_type, required, description}]

    # Authentication & Visibility
    requires_auth = Column(Boolean, default=False, index=True)  # True if auth required
    visibility = Column(
        String(20), default=EndpointVisibility.PRIVATE.value, index=True
    )  # public, private, internal
    auth_type = Column(String(50), nullable=True)  # Bearer, Basic, API-Key, OAuth2, etc.

    # Detection metadata
    detected_at = Column(DateTime, nullable=True)  # When this endpoint was detected
    detection_confidence = Column(Float, nullable=True)  # 0-100 confidence score
    framework = Column(String(50), nullable=True)  # fastapi, flask, express, etc.

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    repository = relationship("Repository", backref="endpoints")

    __table_args__ = (
        # Unique constraint: one entry per method+path per repository
        UniqueConstraint("repository_id", "method", "path", name="uq_repo_method_path"),
        Index("idx_endpoints_repository", "repository_id"),
        Index("idx_endpoints_auth", "requires_auth"),
        Index("idx_endpoints_visibility", "visibility"),
        Index("idx_endpoints_path", "path"),
    )

    def __repr__(self) -> str:
        auth = "🔒" if self.requires_auth else "🔓"
        return f"<Endpoint {auth} {self.method} {self.path}>"
