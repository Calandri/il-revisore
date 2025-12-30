"""Live View models for production site screenshots."""

from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Index, Integer, String
from sqlalchemy.orm import relationship

from ..session import Base  # type: ignore[attr-defined]
from .base import generate_uuid


class LiveViewScreenshot(Base):
    """Cached screenshot for live view when iframe is blocked."""

    __tablename__ = "live_view_screenshots"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    repository_id = Column(String(36), ForeignKey("repositories.id"), nullable=False)
    external_link_id = Column(
        String(36), ForeignKey("repository_external_links.id"), nullable=False
    )
    s3_url = Column(String(1024), nullable=False)
    captured_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    viewport_width = Column(Integer, default=1920)
    viewport_height = Column(Integer, default=1080)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    repository = relationship("Repository")
    external_link = relationship("RepositoryExternalLink")

    __table_args__ = (
        Index("idx_live_view_repo", "repository_id"),
        Index("idx_live_view_link", "external_link_id", unique=True),
    )

    def __repr__(self) -> str:
        return f"<LiveViewScreenshot repo={self.repository_id} captured={self.captured_at}>"
