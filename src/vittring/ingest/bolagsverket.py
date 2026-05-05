"""Bolagsverket / PoIT ingest adapter.

Two backends behind the same interface:

* ``official`` — Bolagsverket's REST endpoints (when API access is granted).
* ``poit`` — scrape Post- och Inrikes Tidningar kungörelser as a fallback.

The adapter is selected via ``BOLAGSVERKET_BACKEND`` (default ``poit``).
Personal data (officer names) flows into ``CompanyChange.old_value`` /
``new_value`` and is purged by the nightly GDPR job after the retention
window — see ``src/vittring/jobs/gdpr.py``.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from datetime import datetime
from typing import Any

import structlog

from vittring.config import get_settings
from vittring.ingest._http import get_json_with_retry, http_client
from vittring.ingest._persist import insert_ignore, upsert_companies
from vittring.ingest.base import IngestAdapter
from vittring.models.signals import CompanyChange
from vittring.schemas.ingest import CompanyChangeItem

logger = structlog.get_logger(__name__)


class _Backend:
    """Mixin protocol for backend implementations."""

    async def fetch(self, since: datetime) -> AsyncIterator[CompanyChangeItem]:  # pragma: no cover
        raise NotImplementedError
        yield  # type: ignore[unreachable]


class _PoitBackend(_Backend):
    """Scrape PoIT kungörelser.

    PoIT publishes Bolagsverket's official notices (kungörelser) including
    changes to board, CEO, name, address, and liquidation. Implementation
    details live behind a stable interface so we can swap to the official
    Bolagsverket API later without touching the orchestrator.

    The actual scraping logic is intentionally minimal in this scaffold —
    the live endpoint and selectors must be confirmed against PoIT's current
    structure at integration time. ``docs/data-sources.md`` tracks that.
    """

    POIT_API_URL = "https://poit.bolagsverket.se/poit/api/kungorelse/sok"

    async def fetch(self, since: datetime) -> AsyncIterator[CompanyChangeItem]:
        params = {
            "publiceringsdatumFran": since.date().isoformat(),
            "size": 100,
            "page": 0,
        }
        async with http_client() as client:
            while True:
                try:
                    payload = await get_json_with_retry(
                        client, self.POIT_API_URL, params=dict(params)
                    )
                except (ValueError, json.JSONDecodeError) as exc:
                    # PoIT's public endpoint occasionally returns a stub HTML
                    # page or a 200 with empty body; treat as "no data right
                    # now" rather than crashing the ingest job.
                    logger.warning(
                        "bolagsverket_invalid_response",
                        page=params["page"],
                        error=str(exc),
                    )
                    return
                if not isinstance(payload, dict):
                    logger.warning(
                        "bolagsverket_unexpected_payload_type",
                        type=type(payload).__name__,
                    )
                    return
                rows: list[dict[str, Any]] = payload.get("kungorelser", [])
                if not rows:
                    break
                for row in rows:
                    item = self._parse_row(row)
                    if item is not None:
                        yield item
                if payload.get("last", True):
                    break
                params["page"] += 1

    @staticmethod
    def _parse_row(row: dict[str, Any]) -> CompanyChangeItem | None:
        orgnr = row.get("organisationsnummer")
        kind = row.get("arendetyp")
        changed_at_raw = row.get("publiceringsdatum")
        if not (orgnr and kind and changed_at_raw):
            return None

        change_type = _map_arendetyp(kind)
        if change_type is None:
            return None

        return CompanyChangeItem(
            orgnr=orgnr,
            company_name=row.get("foretagsnamn") or "Okänt företag",
            change_type=change_type,
            old_value=row.get("foreVarde"),
            new_value=row.get("efterVarde"),
            source_ref=row.get("kungorelseId"),
            changed_at=datetime.fromisoformat(changed_at_raw),
        )


def _map_arendetyp(arendetyp: str) -> str | None:
    """Map PoIT ``arendetyp`` values to our ``change_type`` taxonomy."""
    table: dict[str, str] = {
        "STYRELSE": "board_member",
        "STYRELSEORDFORANDE": "board_member",
        "VD": "ceo",
        "ADRESS": "address",
        "FIRMA": "name",
        "ANMARKNING": "remark",
        "LIKVIDATION": "liquidation",
        "VERKSAMHET": "sni",
    }
    return table.get(arendetyp.upper())


class _OfficialBackend(_Backend):
    """Placeholder for Bolagsverket's official open-data REST endpoints.

    Activate via ``BOLAGSVERKET_BACKEND=official`` once we have credentials
    and confirmed endpoint shape. Until then, calls raise NotImplementedError
    and the scheduler keeps using the PoIT backend.
    """

    async def fetch(self, since: datetime) -> AsyncIterator[CompanyChangeItem]:
        raise NotImplementedError(
            "Official Bolagsverket backend not yet wired — set BOLAGSVERKET_BACKEND=poit"
        )
        yield  # type: ignore[unreachable]


class BolagsverketAdapter(IngestAdapter[CompanyChangeItem]):
    name = "bolagsverket"

    def __init__(self) -> None:
        backend = get_settings().bolagsverket_backend
        self._backend: _Backend = _OfficialBackend() if backend == "official" else _PoitBackend()

    async def fetch_since(self, since: datetime) -> AsyncIterator[CompanyChangeItem]:
        async for item in self._backend.fetch(since):
            yield item

    async def persist(self, items: list[CompanyChangeItem]) -> int:
        if not items:
            return 0

        company_rows = [
            {"orgnr": item.orgnr, "name": item.company_name} for item in items
        ]
        orgnr_to_id = await upsert_companies(company_rows)

        rows: list[dict[str, Any]] = []
        for item in items:
            company_id = orgnr_to_id.get(item.orgnr)
            if company_id is None:
                continue
            rows.append(
                {
                    "company_id": company_id,
                    "change_type": item.change_type,
                    "old_value": item.old_value,
                    "new_value": item.new_value,
                    "source_ref": item.source_ref,
                    "changed_at": item.changed_at,
                }
            )
        # No natural unique key; the (source_ref, changed_at) pair is the
        # logical idempotency unit. We dedupe by (company_id, change_type,
        # changed_at, source_ref) at the application level for now — see
        # docs/data-sources.md for the upcoming partial unique index.
        from sqlalchemy.dialects.postgresql import insert as pg_insert

        from vittring.db import session_scope

        if not rows:
            return 0
        async with session_scope() as session:
            stmt = pg_insert(CompanyChange).values(rows).on_conflict_do_nothing()
            result = await session.execute(stmt)
            return result.rowcount or 0
