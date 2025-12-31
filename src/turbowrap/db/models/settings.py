"""Application settings model."""

from sqlalchemy import Column, String, Text

from turbowrap.db.base import Base

from .base import TZDateTime, now_utc


class Setting(Base):
    """Application settings stored in database."""

    __tablename__ = "settings"

    key = Column(String(100), primary_key=True)
    value = Column(Text, nullable=True)
    is_secret = Column(String(1), default="N")  # Y = encrypted/masked in API responses
    description = Column(String(255), nullable=True)
    updated_at = Column(TZDateTime(), default=now_utc, onupdate=now_utc)

    def __repr__(self) -> str:
        return f"<Setting {self.key}>"
