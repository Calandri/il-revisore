"""API dependencies."""

from typing import Generator

from sqlalchemy.orm import Session

from ..db.session import get_db as _get_db


def get_db() -> Generator[Session, None, None]:
    """Database session dependency."""
    yield from _get_db()
