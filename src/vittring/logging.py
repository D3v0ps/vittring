"""Structured logging with structlog.

JSON output to stdout in production (consumed by systemd-journald). Pretty
console output in development. Context vars (request_id, user_id) are bound
via middleware and propagate through the entire async task.
"""

from __future__ import annotations

import logging
import sys
from typing import Any

import structlog
from structlog.contextvars import merge_contextvars
from structlog.processors import (
    JSONRenderer,
    StackInfoRenderer,
    TimeStamper,
    add_log_level,
    format_exc_info,
)
from structlog.stdlib import BoundLogger

from vittring.config import get_settings


def configure_logging() -> None:
    """Configure structlog and stdlib logging once at process start."""
    settings = get_settings()
    is_prod = settings.is_production

    timestamper = TimeStamper(fmt="iso", utc=True)

    shared_processors: list[Any] = [
        merge_contextvars,
        add_log_level,
        timestamper,
        StackInfoRenderer(),
        format_exc_info,
    ]

    if is_prod:
        renderer: Any = JSONRenderer()
    else:
        renderer = structlog.dev.ConsoleRenderer(colors=True)

    structlog.configure(
        processors=[*shared_processors, renderer],
        wrapper_class=BoundLogger,
        logger_factory=structlog.PrintLoggerFactory(file=sys.stdout),
        cache_logger_on_first_use=True,
    )

    # Bridge stdlib logging to structlog so libraries (uvicorn, sqlalchemy,
    # apscheduler) emit through the same pipeline.
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        structlog.stdlib.ProcessorFormatter(
            foreign_pre_chain=shared_processors,
            processors=[
                structlog.stdlib.ProcessorFormatter.remove_processors_meta,
                renderer,
            ],
        )
    )

    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(logging.INFO if is_prod else logging.DEBUG)

    for noisy in ("uvicorn.access", "sqlalchemy.engine.Engine"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def get_logger(name: str | None = None) -> BoundLogger:
    """Return a bound logger. Pass ``__name__`` from call sites."""
    logger: BoundLogger = structlog.get_logger(name)
    return logger
