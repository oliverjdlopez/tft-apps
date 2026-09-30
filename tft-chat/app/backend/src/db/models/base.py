"""Shared SQLAlchemy declarative foundations for database models."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import String
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import DeclarativeBase


def utc_now() -> datetime:
    """Return the current timezone-aware UTC timestamp for ORM defaults."""
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    """Base class whose metadata registry contains every persisted entity."""


metadata = Base.metadata
TextArray = ARRAY(String)


__all__ = ["Base", "TextArray", "metadata", "utc_now"]
