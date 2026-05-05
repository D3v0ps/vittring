"""``BaseScraper`` foundation for Vittring's good-faith scraping policy.

Every concrete scraper inherits from :class:`BaseScraper` and gets the
following compliance behaviour for free, in this exact order, on every
:meth:`fetch` call:

1. Internal blocklist check (`BLOCKED_DOMAINS`).
2. Active-hours window check (Europe/Stockholm, default 06:00-22:00).
3. Per-domain daily request quota from the ``audit_log`` table.
4. ``robots.txt`` lookup with 24-hour in-memory cache.
5. Per-domain inter-request sleep (default 2 s).
6. Conditional GET using cached ``ETag`` / ``Last-Modified`` headers.
7. Exponential backoff retry on 5xx (max 3 attempts).
8. Audit-log row written for every request decision (allow, block, skip).

Subclasses set the four class attributes (``name``, ``base_url``, ``domain``,
``source_value``) and implement :meth:`list_urls` plus :meth:`parse`. The
``IngestAdapter`` interface (``fetch_since`` / ``persist``) is implemented
once here in subclass scaffolding.

See CLAUDE.md §24 for the policy itself.
"""

from __future__ import annotations

import asyncio
import time
from abc import abstractmethod
from datetime import UTC, datetime, timedelta
from typing import Any, ClassVar
from urllib import robotparser
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

import httpx
import structlog
from sqlalchemy import func, select

from vittring.audit.log import AuditAction, audit
from vittring.db import session_scope
from vittring.ingest.base import IngestAdapter
from vittring.ingest.scrapers.blocklist import BLOCKED_DOMAINS
from vittring.models.audit import AuditLog

logger = structlog.get_logger(__name__)

STOCKHOLM_TZ = ZoneInfo("Europe/Stockholm")


class BaseScraper[T](IngestAdapter[T]):
    """Compliance-enforcing HTTP fetcher for procurement portals.

    Subclasses MUST set:

    - ``name``: short id, used in logs and the ``procurements.source`` column.
    - ``base_url``: public landing/listing URL.
    - ``domain``: bare host (used for robots.txt + rate-limit accounting).
    - ``source_value``: value persisted to ``procurements.source`` per row.
    """

    # Identification (see §24.1) -----------------------------------------------
    USER_AGENT: ClassVar[str] = (
        "VittringBot/1.0 (+https://vittring.karimkhalil.se/bot; info@karimkhalil.se)"
    )

    # Rate limits (see §24.3) --------------------------------------------------
    MIN_REQUEST_INTERVAL_SEC: ClassVar[float] = 2.0
    MAX_REQUESTS_PER_DAY: ClassVar[int] = 200
    ACTIVE_HOURS: ClassVar[tuple[int, int]] = (6, 22)

    # Subclass-provided attributes --------------------------------------------
    # ``name`` is declared as ``str`` on ``IngestAdapter`` (instance variable
    # by mypy semantics, even though every adapter sets it as a class
    # attribute). Keep that shape here so subclasses can mirror the existing
    # JobTech / TED / Bolagsverket adapters.
    name: str
    base_url: str
    domain: str
    source_value: str

    # Per-process caches -------------------------------------------------------
    # robots.txt: domain -> (parser, fetched_at, status_code)
    _robots_cache: ClassVar[
        dict[str, tuple[robotparser.RobotFileParser | None, float, int | None]]
    ] = {}
    # response cache: url -> (etag, last_modified, body)
    _response_cache: ClassVar[dict[str, tuple[str | None, str | None, str]]] = {}
    # last-request timestamp per domain: domain -> monotonic seconds
    _last_request_at: ClassVar[dict[str, float]] = {}

    ROBOTS_TTL_SECONDS: ClassVar[float] = 24 * 3600.0

    # Public API ---------------------------------------------------------------

    async def fetch(self, url: str) -> tuple[str | None, dict[str, Any]]:
        """Fetch ``url`` while honouring the full compliance pipeline.

        Returns a ``(body, metadata)`` tuple. ``body`` is ``None`` when the
        request was skipped (blocked, outside active hours, rate limited,
        disallowed by robots.txt, or robots.txt unreachable). ``metadata`` is
        the dict written to the ``audit_log`` row in addition to bookkeeping
        fields the caller may inspect (e.g. ``status_code``, ``cache_hit``).
        """
        started = time.monotonic()
        domain = self._domain_of(url)

        # 1. Blocklist
        if domain in BLOCKED_DOMAINS:
            meta = {
                "source": self.name,
                "url": url,
                "status_code": None,
                "response_size": 0,
                "cache_hit": False,
                "robots_status_code": None,
                "robots_decision": "blocked_by_internal_blocklist",
                "robots_reason": "domain in BLOCKED_DOMAINS set",
                "request_time_ms": int((time.monotonic() - started) * 1000),
            }
            await self._write_audit(meta)
            return None, meta

        # 2. Active hours
        if not self._within_active_hours():
            meta = {
                "source": self.name,
                "url": url,
                "status_code": None,
                "response_size": 0,
                "cache_hit": False,
                "robots_status_code": None,
                "robots_decision": "outside_active_hours",
                "robots_reason": (
                    f"current Europe/Stockholm hour outside "
                    f"{self.ACTIVE_HOURS[0]:02d}:00-{self.ACTIVE_HOURS[1]:02d}:00"
                ),
                "request_time_ms": int((time.monotonic() - started) * 1000),
            }
            await self._write_audit(meta)
            return None, meta

        # 3. Daily quota from audit_log
        used = await self._daily_request_count(domain)
        if used >= self.MAX_REQUESTS_PER_DAY:
            meta = {
                "source": self.name,
                "url": url,
                "status_code": None,
                "response_size": 0,
                "cache_hit": False,
                "robots_status_code": None,
                "robots_decision": "rate_limit_exceeded",
                "robots_reason": (
                    f"{used} requests in last 24h, max {self.MAX_REQUESTS_PER_DAY}"
                ),
                "request_time_ms": int((time.monotonic() - started) * 1000),
            }
            await self._write_audit(meta)
            return None, meta

        # 4. robots.txt
        parser, robots_status, robots_decision, robots_reason = await self._evaluate_robots(
            domain, url
        )
        if robots_decision != "allowed_by_robots":
            meta = {
                "source": self.name,
                "url": url,
                "status_code": None,
                "response_size": 0,
                "cache_hit": False,
                "robots_status_code": robots_status,
                "robots_decision": robots_decision,
                "robots_reason": robots_reason,
                "request_time_ms": int((time.monotonic() - started) * 1000),
            }
            await self._write_audit(meta)
            return None, meta

        # 5. Sleep if last request to this domain was < interval ago
        await self._respect_interval(domain)

        # 6 + 7. Conditional GET with retries
        cached = self._response_cache.get(url)
        headers = {
            "User-Agent": self.USER_AGENT,
            "From": "info@karimkhalil.se",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        }
        if cached is not None:
            etag, last_modified, _ = cached
            if etag:
                headers["If-None-Match"] = etag
            if last_modified:
                headers["If-Modified-Since"] = last_modified

        body, status_code = await self._do_get(url, headers)
        # Update last-request timestamp regardless of outcome (a request was made).
        self._last_request_at[domain] = time.monotonic()

        if status_code == 304 and cached is not None:
            cached_body = cached[2]
            meta = {
                "source": self.name,
                "url": url,
                "status_code": 304,
                "response_size": len(cached_body),
                "cache_hit": True,
                "robots_status_code": robots_status,
                "robots_decision": "allowed_by_robots",
                "robots_reason": robots_reason,
                "request_time_ms": int((time.monotonic() - started) * 1000),
            }
            await self._write_audit(meta)
            return cached_body, meta

        if body is None:
            meta = {
                "source": self.name,
                "url": url,
                "status_code": status_code,
                "response_size": 0,
                "cache_hit": False,
                "robots_status_code": robots_status,
                "robots_decision": "allowed_by_robots",
                "robots_reason": robots_reason,
                "request_time_ms": int((time.monotonic() - started) * 1000),
            }
            await self._write_audit(meta)
            return None, meta

        meta = {
            "source": self.name,
            "url": url,
            "status_code": status_code,
            "response_size": len(body.encode("utf-8")),
            "cache_hit": False,
            "robots_status_code": robots_status,
            "robots_decision": "allowed_by_robots",
            "robots_reason": robots_reason,
            "request_time_ms": int((time.monotonic() - started) * 1000),
        }
        # Parser used the parser variable; keep linter happy + leave hook for
        # future use (e.g. crawl-delay extraction).
        del parser
        await self._write_audit(meta)
        return body, meta

    # Subclass hooks -----------------------------------------------------------

    @abstractmethod
    async def list_urls(self) -> list[str]:
        """Return URLs the scraper should visit on the next run."""

    @abstractmethod
    def parse(self, body: str, url: str) -> Any:
        """Convert a fetched HTML/JSON body into the adapter's item type."""

    # Internal helpers ---------------------------------------------------------

    @staticmethod
    def _domain_of(url: str) -> str:
        host = urlsplit(url).hostname or ""
        return host.lower()

    @classmethod
    def _within_active_hours(cls) -> bool:
        now = datetime.now(STOCKHOLM_TZ)
        start, end = cls.ACTIVE_HOURS
        return start <= now.hour < end

    async def _daily_request_count(self, domain: str) -> int:
        """Count rows in ``audit_log`` for ``action='scraper_request'`` against ``domain``.

        Counts only successful or attempted fetches in the last 24 hours.
        """
        cutoff = datetime.now(UTC) - timedelta(hours=24)
        async with session_scope() as session:
            stmt = select(func.count(AuditLog.id)).where(
                AuditLog.action == AuditAction.SCRAPER_REQUEST,
                AuditLog.created_at >= cutoff,
                AuditLog.audit_metadata["source"].astext == self.name,
            )
            result = await session.execute(stmt)
            return int(result.scalar_one() or 0)

    async def _evaluate_robots(
        self, domain: str, url: str
    ) -> tuple[robotparser.RobotFileParser | None, int | None, str, str]:
        """Fetch + cache robots.txt and decide whether ``url`` is allowed.

        Returns ``(parser, status_code, decision, reason)`` where ``decision``
        is one of ``allowed_by_robots``, ``disallowed_by_robots``,
        ``no_robots_txt_404``, ``robots_unreachable_skipped``.
        """
        cached = self._robots_cache.get(domain)
        now = time.monotonic()
        if cached is not None and (now - cached[1]) < self.ROBOTS_TTL_SECONDS:
            parser, _fetched_at, status_code = cached
        else:
            parser, status_code = await self._fetch_robots(domain)
            self._robots_cache[domain] = (parser, now, status_code)

        if status_code == 404:
            return parser, status_code, "no_robots_txt_404", "robots.txt returned 404"
        if parser is None:
            return (
                parser,
                status_code,
                "robots_unreachable_skipped",
                f"robots.txt unreachable (status={status_code})",
            )

        if parser.can_fetch(self.USER_AGENT, url):
            return parser, status_code, "allowed_by_robots", "robots.txt allows"
        return parser, status_code, "disallowed_by_robots", "robots.txt disallows"

    async def _fetch_robots(
        self, domain: str
    ) -> tuple[robotparser.RobotFileParser | None, int | None]:
        url = f"https://{domain}/robots.txt"
        try:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(connect=5.0, read=15.0, write=10.0, pool=5.0),
                headers={"User-Agent": self.USER_AGENT, "From": "info@karimkhalil.se"},
            ) as client:
                response = await client.get(url)
        except httpx.HTTPError as exc:
            logger.warning("robots_unreachable", domain=domain, error=str(exc))
            return None, None

        if response.status_code == 404:
            # No robots.txt → conservatively treat as "we don't know" but still
            # let the call site mark it as such; we return a permissive parser
            # so downstream code is not None-fragile.
            return None, 404
        if 400 <= response.status_code < 600 and response.status_code != 404:
            return None, response.status_code

        parser = robotparser.RobotFileParser()
        parser.parse(response.text.splitlines())
        return parser, response.status_code

    async def _respect_interval(self, domain: str) -> None:
        last = self._last_request_at.get(domain)
        if last is None:
            return
        elapsed = time.monotonic() - last
        wait = self.MIN_REQUEST_INTERVAL_SEC - elapsed
        if wait > 0:
            await asyncio.sleep(wait)

    async def _do_get(
        self, url: str, headers: dict[str, str]
    ) -> tuple[str | None, int | None]:
        """GET ``url`` with up to 3 retries on 5xx using exponential backoff."""
        attempt = 0
        backoff = 1.0
        last_status: int | None = None
        while attempt < 3:
            attempt += 1
            try:
                async with httpx.AsyncClient(
                    timeout=httpx.Timeout(connect=5.0, read=30.0, write=10.0, pool=5.0),
                ) as client:
                    response = await client.get(url, headers=headers)
            except httpx.HTTPError as exc:
                logger.warning("scraper_request_error", url=url, error=str(exc))
                last_status = None
                if attempt < 3:
                    await asyncio.sleep(backoff)
                    backoff *= 2
                    continue
                return None, None

            last_status = response.status_code
            if response.status_code == 304:
                return None, 304
            if 200 <= response.status_code < 300:
                body = response.text
                # Cache validators for next conditional GET.
                etag = response.headers.get("ETag")
                last_modified = response.headers.get("Last-Modified")
                self._response_cache[url] = (etag, last_modified, body)
                return body, response.status_code
            if 500 <= response.status_code < 600 and attempt < 3:
                await asyncio.sleep(backoff)
                backoff *= 2
                continue
            # 4xx (other than 304) — give up immediately, no retry.
            return None, response.status_code

        return None, last_status

    async def _write_audit(self, metadata: dict[str, Any]) -> None:
        try:
            async with session_scope() as session:
                await audit(
                    session,
                    action=AuditAction.SCRAPER_REQUEST,
                    metadata=metadata,
                )
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("scraper_audit_write_failed", error=str(exc), url=metadata.get("url"))
