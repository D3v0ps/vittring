"""TED (Tenders Electronic Daily) ingest adapter.

Fetches Swedish public-sector procurement notices filtered to staffing-relevant
CPV codes. The TED API returns notices with multilingual fields; we prefer
Swedish text where available and fall back to English.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import datetime
from typing import Any

import structlog

from vittring.config import get_settings
from vittring.ingest._http import get_json_with_retry, http_client
from vittring.ingest._persist import insert_ignore
from vittring.ingest.base import IngestAdapter
from vittring.models.signals import Procurement
from vittring.schemas.ingest import ProcurementItem

logger = structlog.get_logger(__name__)

# CPV codes covering staffing, recruitment, and adjacent personnel-supply
# services. See CLAUDE.md §9.3 for the source-of-truth list.
TED_CPV_CODES: tuple[str, ...] = (
    "79600000",
    "79610000",
    "79620000",
    "79621000",
    "79624000",
    "79625000",
    "85000000",
)

PAGE_SIZE = 100


def _localized(field: dict[str, Any] | None, *, prefer: str = "swe") -> str | None:
    """Pick a Swedish or English value from a TED multilingual field."""
    if not field:
        return None
    if prefer in field:
        return field[prefer]
    if "eng" in field:
        return field["eng"]
    if isinstance(field, dict) and field:
        return next(iter(field.values()))
    return None


def _parse_notice(notice: dict[str, Any]) -> ProcurementItem | None:
    notice_id = notice.get("publication-number") or notice.get("ND")
    if not notice_id:
        return None

    buyer = (notice.get("organisations") or {}).get("organization") or {}
    deadline_raw = notice.get("deadline-receipt-tender-date") or notice.get(
        "deadline-receipt-request"
    )
    deadline = (
        datetime.fromisoformat(deadline_raw.replace("Z", "+00:00"))
        if isinstance(deadline_raw, str)
        else None
    )

    estimated_value = notice.get("total-value")
    sek_value: int | None = None
    if isinstance(estimated_value, dict):
        amount = estimated_value.get("amount")
        currency = estimated_value.get("currency")
        if currency == "SEK" and isinstance(amount, (int, float)):
            sek_value = int(amount)

    return ProcurementItem(
        external_id=str(notice_id),
        buyer_orgnr=buyer.get("national-id"),
        buyer_name=_localized(buyer.get("name")) or "Okänd köpare",
        title=_localized(notice.get("title")) or "Upphandling",
        description=_localized(notice.get("description")),
        cpv_codes=list(notice.get("classification-cpv") or []),
        estimated_value_sek=sek_value,
        procedure_type=notice.get("procedure-type"),
        deadline=deadline,
        source_url=notice.get("links", {}).get("html", {}).get("ENG")
        or notice.get("links", {}).get("html", {}).get("SWE"),
        source="ted",
    )


class TedAdapter(IngestAdapter[ProcurementItem]):
    name = "ted"

    async def fetch_since(self, since: datetime) -> AsyncIterator[ProcurementItem]:
        settings = get_settings()
        query = (
            "country=SE AND ("
            + " OR ".join(f"classification-cpv={code}" for code in TED_CPV_CODES)
            + f") AND publication-date>={since.date().isoformat()}"
        )
        params: dict[str, Any] = {
            "query": query,
            "fields": ",".join(
                [
                    "publication-number",
                    "title",
                    "description",
                    "classification-cpv",
                    "deadline-receipt-tender-date",
                    "deadline-receipt-request",
                    "total-value",
                    "procedure-type",
                    "organisations",
                    "links",
                ]
            ),
            "limit": PAGE_SIZE,
            "page": 1,
        }
        async with http_client(base_url=str(settings.ted_base_url)) as client:
            while True:
                payload = await get_json_with_retry(
                    client, "/notices/search", params=dict(params)
                )
                notices: list[dict[str, Any]] = payload.get("notices", [])
                if not notices:
                    break
                for notice in notices:
                    item = _parse_notice(notice)
                    if item is not None:
                        yield item
                if len(notices) < PAGE_SIZE:
                    break
                params["page"] += 1

    async def persist(self, items: list[ProcurementItem]) -> int:
        if not items:
            return 0
        rows = [
            {
                "external_id": item.external_id,
                "buyer_orgnr": item.buyer_orgnr,
                "buyer_name": item.buyer_name,
                "title": item.title,
                "description": item.description,
                "cpv_codes": item.cpv_codes,
                "estimated_value_sek": item.estimated_value_sek,
                "procedure_type": item.procedure_type,
                "deadline": item.deadline,
                "source_url": item.source_url,
                "source": item.source,
            }
            for item in items
        ]
        return await insert_ignore(Procurement, rows, conflict_cols=["external_id"])
