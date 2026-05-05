"""Health and readiness endpoints.

``/health`` is cheap and always-on (used by Caddy and UptimeRobot).
``/ready`` checks DB connectivity and that ingest has run within the
expected window — used by deploy verification.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, status
from fastapi.responses import JSONResponse
from sqlalchemy import func, select

from vittring.db import SessionDep
from vittring.models.signals import JobPosting

router = APIRouter()

INGEST_FRESHNESS_LIMIT = timedelta(hours=25)


@router.get("/health", include_in_schema=False)
async def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/ready", include_in_schema=False)
async def ready(session: SessionDep) -> JSONResponse:
    try:
        await session.execute(select(1))
    except Exception as exc:  # pragma: no cover
        return JSONResponse(
            {"status": "db_unavailable", "error": str(exc)},
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        )

    last_ingest_row = await session.execute(select(func.max(JobPosting.ingested_at)))
    last_ingest = last_ingest_row.scalar()

    payload = {
        "status": "ok",
        "db": "ok",
        "last_jobtech_ingest": last_ingest.isoformat() if last_ingest else None,
    }

    if last_ingest is None:
        payload["status"] = "no_ingest_yet"
        return JSONResponse(payload, status_code=status.HTTP_200_OK)

    if datetime.now(timezone.utc) - last_ingest > INGEST_FRESHNESS_LIMIT:
        payload["status"] = "ingest_stale"
        return JSONResponse(payload, status_code=status.HTTP_503_SERVICE_UNAVAILABLE)

    return JSONResponse(payload, status_code=status.HTTP_200_OK)
