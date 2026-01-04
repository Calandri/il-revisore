"""Widget API key model for widget authentication."""

from sqlalchemy import Boolean, Column, ForeignKey, Index, String
from sqlalchemy.dialects.sqlite import JSON
from sqlalchemy.orm import relationship

from turbowrap.db.base import Base

from .base import TZDateTime, generate_uuid, now_utc


class WidgetApiKey(Base):
    """API key for widget authentication.

    Supports multiple keys for different clients/websites.
    Keys are stored as SHA256 hashes for security - the raw key
    is only shown once at creation time.

    Key format: twk_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx (32 random chars)
    """

    __tablename__ = "widget_api_keys"
    __table_args__ = (
        Index("ix_widget_api_keys_key_hash", "key_hash"),
        {"extend_existing": True},
    )

    id = Column(String(36), primary_key=True, default=generate_uuid)
    key_hash = Column(String(64), unique=True, nullable=False)  # SHA256 hash
    key_prefix = Column(String(8), nullable=False)  # First 8 chars (twk_xxxx) for identification
    name = Column(String(100), nullable=False)  # "3Bee Website", "OASI Dashboard"
    allowed_origins = Column(JSON, nullable=True)  # ["https://3bee.com", "https://oasi.3bee.com"]
    repository_id = Column(
        String(36), ForeignKey("repositories.id", ondelete="SET NULL"), nullable=True
    )
    team_id = Column(String(50), nullable=True)  # Linear team ID default
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(TZDateTime(), default=now_utc, nullable=False)
    last_used_at = Column(TZDateTime(), nullable=True)
    expires_at = Column(TZDateTime(), nullable=True)

    # Relationship
    repository = relationship("Repository", backref="widget_api_keys")

    def __repr__(self) -> str:
        return f"<WidgetApiKey {self.key_prefix}... ({self.name})>"
