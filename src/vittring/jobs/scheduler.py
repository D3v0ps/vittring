"""APScheduler wiring.

All cron expressions are ``Europe/Stockholm`` per CLAUDE.md. The scheduler
runs in its own systemd unit (``vittring-scheduler.service``) — separate
from the API process so a slow/failing API does not back up jobs.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import structlog
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from vittring.config import get_settings
from vittring.ingest.base import run_ingest
from vittring.ingest.bolagsverket import BolagsverketAdapter
from vittring.ingest.jobtech import JobTechAdapter
from vittring.ingest.scrapers.eavrop import EavropScraper
from vittring.ingest.scrapers.kommers import KommersScraper
from vittring.ingest.scrapers.mercell import MercellScraper
from vittring.ingest.scrapers.tendsign import TendSignScraper
from vittring.ingest.ted import TedAdapter
from vittring.jobs.digest import run_daily_digest
from vittring.jobs.gdpr import purge_deleted_users, scrub_personal_data

logger = structlog.get_logger(__name__)


def _yesterday() -> datetime:
    return datetime.now(timezone.utc) - timedelta(hours=26)


async def _run_jobtech() -> None:
    await run_ingest(JobTechAdapter(), since=_yesterday())


async def _run_ted() -> None:
    await run_ingest(TedAdapter(), since=_yesterday())


async def _run_bolagsverket() -> None:
    await run_ingest(BolagsverketAdapter(), since=_yesterday())


async def _run_eavrop() -> None:
    await run_ingest(EavropScraper(), since=_yesterday())


async def _run_kommers() -> None:
    await run_ingest(KommersScraper(), since=_yesterday())


async def _run_tendsign() -> None:
    await run_ingest(TendSignScraper(), since=_yesterday())


async def _run_mercell() -> None:
    await run_ingest(MercellScraper(), since=_yesterday())


def build_scheduler() -> AsyncIOScheduler:
    # Pass a real ZoneInfo object — APScheduler 3.x interprets a bare
    # string as the timezone *name* on some backends but silently falls
    # back to the host clock on others, which DST-shifts every cron job
    # twice a year. ZoneInfo locks behaviour to Europe/Stockholm
    # regardless of host TZ.
    tz_name = get_settings().tz
    return AsyncIOScheduler(timezone=ZoneInfo(tz_name))


def register_jobs(scheduler: AsyncIOScheduler) -> None:
    """Wire all production cron jobs onto the scheduler."""
    scheduler.add_job(
        _run_jobtech,
        CronTrigger(hour=6, minute=0),
        id="ingest_jobtech",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    scheduler.add_job(
        _run_bolagsverket,
        CronTrigger(hour=7, minute=0),
        id="ingest_bolagsverket",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    scheduler.add_job(
        _run_ted,
        CronTrigger(hour=8, minute=0),
        id="ingest_ted",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    for scraper_id, fn, minute in (
        ("scrape_eavrop", _run_eavrop, 30),
        ("scrape_kommers", _run_kommers, 35),
        ("scrape_tendsign", _run_tendsign, 40),
        ("scrape_mercell", _run_mercell, 45),
    ):
        scheduler.add_job(
            fn,
            CronTrigger(hour=7, minute=minute),
            id=scraper_id,
            replace_existing=True,
            max_instances=1,
            coalesce=True,
        )
    scheduler.add_job(
        run_daily_digest,
        CronTrigger(hour=6, minute=30),
        id="daily_digest",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    scheduler.add_job(
        scrub_personal_data,
        CronTrigger(hour=3, minute=0),
        id="scrub_personal_data",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    scheduler.add_job(
        purge_deleted_users,
        CronTrigger(hour=3, minute=15),
        id="purge_deleted_users",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    logger.info("scheduler_jobs_registered", jobs=[j.id for j in scheduler.get_jobs()])
