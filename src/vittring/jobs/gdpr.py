"""GDPR-driven scheduled jobs.

Two responsibilities:

1. Scrub Bolagsverket personal data (officer names) from ``company_changes``
   rows older than the retention window unless they have been surfaced in a
   delivered alert (in which case retention extends ``delivered_at + 30d``).
2. Hard-delete users whose ``deletion_requested_at`` is older than the
   30-day grace period.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import structlog
from sqlalchemy import delete, exists, select, update

from vittring.db import session_scope
from vittring.models.signals import CompanyChange
from vittring.models.subscription import DeliveredAlert
from vittring.models.user import User

logger = structlog.get_logger(__name__)

PERSONAL_DATA_RETENTION_DAYS = 30
USER_DELETION_GRACE_DAYS = 30


async def scrub_personal_data() -> int:
    """Null out ``old_value``/``new_value`` on expired company_change rows.

    Returns the number of rows scrubbed.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=PERSONAL_DATA_RETENTION_DAYS)
    log = logger.bind(job="scrub_personal_data", cutoff=cutoff.isoformat())

    # Subquery: was this change ever delivered to a user, and the latest
    # delivery is still inside the extended retention window?
    delivered_recent = (
        select(DeliveredAlert.signal_id)
        .where(
            DeliveredAlert.signal_type == "company_change",
            DeliveredAlert.delivered_at >= cutoff,
        )
        .scalar_subquery()
    )

    async with session_scope() as session:
        stmt = (
            update(CompanyChange)
            .where(
                CompanyChange.ingested_at < cutoff,
                CompanyChange.personal_data_purged_at.is_(None),
                ~CompanyChange.id.in_(delivered_recent),
            )
            .values(
                old_value=None,
                new_value=None,
                personal_data_purged_at=datetime.now(timezone.utc),
            )
        )
        result = await session.execute(stmt)
        scrubbed = result.rowcount or 0
        log.info("scrub_completed", rows=scrubbed)
        return scrubbed


async def purge_deleted_users() -> int:
    """Hard-delete users past their grace period."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=USER_DELETION_GRACE_DAYS)
    log = logger.bind(job="purge_deleted_users", cutoff=cutoff.isoformat())

    async with session_scope() as session:
        rows = (
            await session.execute(
                select(User.id).where(
                    User.deletion_requested_at.is_not(None),
                    User.deletion_requested_at < cutoff,
                )
            )
        ).all()
        ids = [row[0] for row in rows]
        if not ids:
            return 0
        await session.execute(delete(User).where(User.id.in_(ids)))
        log.info("users_purged", count=len(ids))
        return len(ids)
