"""Entry point for ``python -m vittring.jobs`` (used by systemd unit).

Boots the async scheduler and blocks forever.
"""

from __future__ import annotations

import asyncio
import signal

import sentry_sdk
from sentry_sdk.integrations.asyncio import AsyncioIntegration

from vittring.config import get_settings
from vittring.jobs.scheduler import build_scheduler, register_jobs
from vittring.logging import configure_logging, get_logger


async def _run() -> None:
    configure_logging()
    settings = get_settings()
    if settings.sentry_dsn:
        sentry_sdk.init(
            dsn=settings.sentry_dsn.get_secret_value(),
            environment=settings.sentry_environment,
            traces_sample_rate=settings.sentry_traces_sample_rate,
            integrations=[AsyncioIntegration()],
        )

    log = get_logger(__name__)
    scheduler = build_scheduler()
    register_jobs(scheduler)
    scheduler.start()
    log.info("scheduler_started")

    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()

    def _shutdown() -> None:
        log.info("scheduler_shutdown_signal")
        stop_event.set()

    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, _shutdown)

    try:
        await stop_event.wait()
    finally:
        scheduler.shutdown(wait=True)


def main() -> None:
    asyncio.run(_run())


if __name__ == "__main__":
    main()
