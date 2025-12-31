"""Database session management."""

from collections.abc import Generator
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from ..config import get_settings
from .base import Base

# Module-level engine cache
_engine: Engine | None = None
_SessionLocal: sessionmaker[Session] | None = None


def get_engine() -> Engine:
    """Get or create the database engine."""
    global _engine

    if _engine is None:
        settings = get_settings()
        db_url = settings.database.url

        # Expand ~ in SQLite path
        if db_url.startswith("sqlite:///~"):
            db_path = Path(db_url.replace("sqlite:///", "")).expanduser()
            db_url = f"sqlite:///{db_path}"

        # Configure engine based on database type
        if db_url.startswith("sqlite"):
            _engine = create_engine(
                db_url,
                connect_args={"check_same_thread": False},
                echo=settings.database.echo,
            )
        else:
            # PostgreSQL
            _engine = create_engine(
                db_url,
                pool_pre_ping=True,
                pool_size=settings.database.pool_size,
                max_overflow=settings.database.max_overflow,
                pool_timeout=settings.database.pool_timeout,
                pool_recycle=settings.database.pool_recycle,
                echo=settings.database.echo,
            )

    return _engine


def get_session_local() -> sessionmaker[Session]:
    """Get or create the session factory."""
    global _SessionLocal

    if _SessionLocal is None:
        engine = get_engine()
        _SessionLocal = sessionmaker(
            autocommit=False,
            autoflush=False,
            bind=engine,
        )

    return _SessionLocal


def get_db() -> Generator[Session, None, None]:
    """Dependency for getting database session."""
    SessionLocal = get_session_local()
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    """Initialize database tables."""
    engine = get_engine()
    Base.metadata.create_all(bind=engine)


def drop_db() -> None:
    """Drop all database tables (use with caution!)."""
    engine = get_engine()
    Base.metadata.drop_all(bind=engine)


# Alias for compatibility
SessionLocal = get_session_local
