"""Mercell scraper skeleton.

TendSign and Mercell share the same legal entity (Mercell Group) but operate
on distinct public domains; we treat them as independent technical endpoints
and apply opt-out / take-down requests to both at the same time.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import datetime

import structlog

from vittring.ingest._persist import insert_ignore
from vittring.ingest.scrapers.base import BaseScraper
from vittring.models.signals import Procurement
from vittring.schemas.ingest import ProcurementItem

logger = structlog.get_logger(__name__)


class MercellScraper(BaseScraper[ProcurementItem]):
    name = "mercell"
    base_url = "https://www.mercell.com"
    domain = "www.mercell.com"
    source_value = "mercell"

    async def list_urls(self) -> list[str]:
        # TODO: enumerate active-tender listing pages.
        return []

    def parse(self, body: str, url: str) -> ProcurementItem:
        # TODO: implement HTML extraction (public fields only).
        raise NotImplementedError("MercellScraper.parse is not yet implemented")

    async def fetch_since(self, since: datetime) -> AsyncIterator[ProcurementItem]:
        urls = await self.list_urls()
        for url in urls:
            body, _meta = await self.fetch(url)
            if body is None:
                continue
            try:
                item = self.parse(body, url)
            except NotImplementedError:
                return
            except Exception as exc:
                logger.warning("mercell_parse_failed", url=url, error=str(exc))
                continue
            yield item

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
                "source": self.source_value,
            }
            for item in items
        ]
        return await insert_ignore(Procurement, rows, conflict_cols=["external_id"])
