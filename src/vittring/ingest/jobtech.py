"""JobTech Dev (Arbetsförmedlingen) ingest adapter.

API docs: https://jobtechdev.se/sv/komponenter/jobsearch
The search endpoint returns ads with rich employer and workplace metadata.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from datetime import datetime
from typing import Any

import structlog

from vittring.config import get_settings
from vittring.ingest._http import get_json_with_retry, http_client
from vittring.ingest._persist import insert_ignore, upsert_companies
from vittring.ingest.base import IngestAdapter
from vittring.models.signals import JobPosting
from vittring.schemas.ingest import JobPostingItem

logger = structlog.get_logger(__name__)

PAGE_SIZE = 100
RATE_LIMIT_SLEEP_SECONDS = 0.25  # ≤ 4 req/s, well under the 5/s cap


def _parse_hit(hit: dict[str, Any]) -> JobPostingItem:
    employer = hit.get("employer") or {}
    occupation = hit.get("occupation") or {}
    workplace = hit.get("workplace_address") or {}
    employment = hit.get("employment_type") or {}
    duration = hit.get("duration") or {}
    source_links = hit.get("source_links") or []
    source_url = source_links[0]["url"] if source_links else None

    return JobPostingItem(
        external_id=str(hit["id"]),
        employer_orgnr=employer.get("organization_number"),
        employer_name=employer.get("name") or employer.get("workplace") or "Okänd arbetsgivare",
        headline=hit["headline"],
        description=(hit.get("description") or {}).get("text"),
        occupation_label=occupation.get("label"),
        occupation_concept_id=occupation.get("concept_id"),
        workplace_municipality=workplace.get("municipality"),
        workplace_county=workplace.get("region"),
        employment_type=employment.get("label"),
        duration=duration.get("label"),
        published_at=datetime.fromisoformat(hit["publication_date"]),
        source_url=source_url,
    )


class JobTechAdapter(IngestAdapter[JobPostingItem]):
    name = "jobtech"

    async def fetch_since(self, since: datetime) -> AsyncIterator[JobPostingItem]:
        settings = get_settings()
        params: dict[str, Any] = {
            "published-after": since.isoformat(),
            "limit": PAGE_SIZE,
            "offset": 0,
        }
        async with http_client(base_url=str(settings.jobtech_base_url)) as client:
            while True:
                payload = await get_json_with_retry(
                    client, "/search", params=dict(params)
                )
                hits: list[dict[str, Any]] = payload.get("hits", [])
                if not hits:
                    break
                for hit in hits:
                    try:
                        yield _parse_hit(hit)
                    except (KeyError, ValueError) as exc:
                        logger.warning(
                            "jobtech_parse_skip",
                            external_id=hit.get("id"),
                            error=str(exc),
                        )
                if len(hits) < PAGE_SIZE:
                    break
                params["offset"] += PAGE_SIZE
                await asyncio.sleep(RATE_LIMIT_SLEEP_SECONDS)

    async def persist(self, items: list[JobPostingItem]) -> int:
        if not items:
            return 0

        company_rows = [
            {"orgnr": item.employer_orgnr, "name": item.employer_name}
            for item in items
            if item.employer_orgnr
        ]
        orgnr_to_id = await upsert_companies(company_rows)

        rows: list[dict[str, Any]] = []
        for item in items:
            rows.append(
                {
                    "external_id": item.external_id,
                    "company_id": orgnr_to_id.get(item.employer_orgnr or ""),
                    "employer_name": item.employer_name,
                    "headline": item.headline,
                    "description": item.description,
                    "occupation_label": item.occupation_label,
                    "occupation_concept_id": item.occupation_concept_id,
                    "workplace_municipality": item.workplace_municipality,
                    "workplace_county": item.workplace_county,
                    "employment_type": item.employment_type,
                    "duration": item.duration,
                    "published_at": item.published_at,
                    "source_url": item.source_url,
                }
            )

        return await insert_ignore(JobPosting, rows, conflict_cols=["external_id"])
