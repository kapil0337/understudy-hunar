from __future__ import annotations

from datetime import UTC, datetime
from enum import Enum

from sqlalchemy import Enum as SAEnum


def utcnow() -> datetime:
    return datetime.now(UTC)


def pg_enum[E: Enum](enum_cls: type[E], name: str) -> SAEnum:
    """A native Postgres enum type, stored by `.value` rather than SQLAlchemy's default of
    `.name` — harmless here since every member's name and value are identical, but explicit
    so that stays true by construction rather than by accident."""
    return SAEnum(enum_cls, name=name, values_callable=lambda cls: [member.value for member in cls])
