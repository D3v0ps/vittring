"""Shared persistence helpers used by adapters.

Wraps SQLAlchemy ``INSERT ... ON CONFLICT DO NOTHING`` so each adapter only
needs to map its parsed item to a row dict.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from vittring.db import session_scope
from vittring.models.company import Company


async def upsert_companies(rows: Sequence[dict[str, Any]]) -> dict[str, int]:
    """Insert (or touch ``last_seen_at`` of) companies, return orgnr→id map.

    Used by adapters that surface a company alongside their primary signal,
    so we can attach ``company_id`` foreign keys without a second round-trip.
    Empty input returns an empty map.
    """
    if not rows:
        return {}
    now = datetime.now(timezone.utc)
    payload = [{**row, "last_seen_at": now} for row in rows]
    async with session_scope() as session:
        stmt = (
            pg_insert(Company)
            .values(payload)
            .on_conflict_do_update(
                index_elements=[Company.orgnr],
                set_={"last_seen_at": now, "name": pg_insert(Company).excluded.name},
            )
        )
        await session.execute(stmt)
        orgnrs = [row["orgnr"] for row in rows]
        result = await session.execute(
            select(Company.orgnr, Company.id).where(Company.orgnr.in_(orgnrs))
        )
        return dict(result.all())  # type: ignore[arg-type]


async def insert_ignore(model: type, rows: Sequence[dict[str, Any]], *, conflict_cols: list[str]) -> int:
    """Insert rows ignoring conflicts. Returns count of newly inserted rows."""
    if not rows:
        return 0
    async with session_scope() as session:
        stmt = (
            pg_insert(model)
            .values(list(rows))
            .on_conflict_do_nothing(index_elements=conflict_cols)
            .returning(getattr(model, "id"))
        )
        result = await session.execute(stmt)
        return len(result.all())
