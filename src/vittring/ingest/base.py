"""IngestAdapter base class and the ``run_ingest`` orchestrator.

Each adapter is responsible for two things only:

1. ``fetch_since(since)`` — pull raw upstream payloads for a time window and
   yield them as parsed Pydantic models.
2. ``persist(items)`` — insert into Postgres, returning the count of *new*
   rows (after dedupe by external id).

The orchestrator (``run_ingest``) handles batching, error reporting,
duration metrics, and Sentry breadcrumbs. Adapters never log metrics
themselves so they remain pure.
"""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import sentry_sdk
import structlog

from vittring.utils.errors import IngestError

logger = structlog.get_logger(__name__)

# Items handled by adapters are validated Pydantic models (see schemas/ingest.py).
# Using ``Any`` here at the base avoids invariance issues with subclassed
# generics in mypy strict; concrete adapters narrow the type.

BATCH_SIZE = 500


@dataclass(frozen=True, slots=True)
class IngestResult:
    source: str
    fetched: int
    new_rows: int
    duration_seconds: float
    error: str | None = None

    @property
    def succeeded(self) -> bool:
        return self.error is None


class IngestAdapter[T](ABC):
    """Protocol all ingest adapters implement.

    Concrete subclasses set ``name`` (used in logs and metrics) and override
    the two abstract methods. Adapters MUST be safe to call on overlapping
    windows — dedupe is enforced at insert time via the unique external_id.
    """

    name: str

    @abstractmethod
    def fetch_since(self, since: datetime) -> AsyncIterator[T]:
        """Yield validated items published since the given timestamp."""

    @abstractmethod
    async def persist(self, items: list[T]) -> int:
        """Persist items, returning the count of newly inserted rows."""


async def run_ingest(adapter: IngestAdapter[Any], since: datetime) -> IngestResult:
    """Drive an adapter end-to-end and report metrics.

    Errors are caught, logged, reported to Sentry, and re-raised so
    APScheduler can retry on its normal cadence.
    """
    started_at = time.monotonic()
    fetched = 0
    new_rows = 0
    log = logger.bind(source=adapter.name, since=since.isoformat())

    log.info("ingest_started")

    try:
        with sentry_sdk.start_transaction(op="ingest", name=f"ingest.{adapter.name}"):
            batch: list[Any] = []
            async for item in adapter.fetch_since(since):
                batch.append(item)
                fetched += 1
                if len(batch) >= BATCH_SIZE:
                    new_rows += await adapter.persist(batch)
                    batch.clear()
            if batch:
                new_rows += await adapter.persist(batch)
    except Exception as exc:
        duration = time.monotonic() - started_at
        log.exception(
            "ingest_failed",
            fetched=fetched,
            new_rows=new_rows,
            duration_seconds=round(duration, 2),
        )
        sentry_sdk.capture_exception(exc)
        raise IngestError(f"{adapter.name} ingest failed: {exc}") from exc

    duration = time.monotonic() - started_at
    log.info(
        "ingest_completed",
        fetched=fetched,
        new_rows=new_rows,
        duration_seconds=round(duration, 2),
    )
    return IngestResult(
        source=adapter.name,
        fetched=fetched,
        new_rows=new_rows,
        duration_seconds=duration,
    )
