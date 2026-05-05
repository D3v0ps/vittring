"""Daily digest assembly and delivery.

For each active user with at least one active subscription, collect signals
matching their criteria that have not yet been delivered, render a single
multipart email, send via Resend, and persist a ``delivered_alerts`` row per
signal so the same item is never sent twice.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlencode

import structlog
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from vittring.config import get_settings
from vittring.db import session_scope
from vittring.delivery.email import render, send_email
from vittring.matching.criteria import Criteria
from vittring.matching.engine import (
    match_company_change,
    match_job_posting,
    match_procurement,
)
from vittring.models.company import Company
from vittring.models.signals import CompanyChange, JobPosting, Procurement
from vittring.models.subscription import DeliveredAlert, Subscription
from vittring.models.user import User
from vittring.schemas.ingest import (
    CompanyChangeItem,
    JobPostingItem,
    ProcurementItem,
)

logger = structlog.get_logger(__name__)

LOOKBACK_HOURS = 26
SWEDISH_WEEKDAYS = ["måndag", "tisdag", "onsdag", "torsdag", "fredag", "lördag", "söndag"]
SWEDISH_MONTHS = [
    "januari",
    "februari",
    "mars",
    "april",
    "maj",
    "juni",
    "juli",
    "augusti",
    "september",
    "oktober",
    "november",
    "december",
]


@dataclass(slots=True)
class _DigestItem:
    kind: str  # 'job' | 'company_change' | 'procurement'
    kind_label: str
    title: str
    detail: str | None
    source_url: str | None
    date_label: str
    signal_id: int


@dataclass(slots=True)
class _DigestSection:
    subscription_id: int
    subscription_name: str
    items: list[_DigestItem]


def _format_swedish_date(dt: datetime) -> str:
    weekday = SWEDISH_WEEKDAYS[dt.weekday()]
    return f"{weekday} {dt.day} {SWEDISH_MONTHS[dt.month - 1]}"


def _format_short(dt: datetime) -> str:
    return f"{dt.day:02d} {SWEDISH_MONTHS[dt.month - 1][:3]} {dt:%H:%M}"


async def _load_user_signals(
    session: AsyncSession, *, since: datetime
) -> tuple[
    list[tuple[JobPosting, JobPostingItem]],
    list[tuple[CompanyChange, CompanyChangeItem, Company]],
    list[tuple[Procurement, ProcurementItem]],
]:
    """Fetch all signals from the lookback window — once per digest run."""
    job_rows = (
        (await session.execute(select(JobPosting).where(JobPosting.published_at >= since)))
        .scalars()
        .all()
    )
    jobs = [(row, _job_to_item(row)) for row in job_rows]

    change_rows = (
        await session.execute(
            select(CompanyChange, Company)
            .join(Company, CompanyChange.company_id == Company.id)
            .where(CompanyChange.changed_at >= since)
        )
    ).all()
    changes = [(row, _change_to_item(row, company), company) for (row, company) in change_rows]

    proc_rows = (
        (
            await session.execute(
                select(Procurement).where(Procurement.ingested_at >= since)
            )
        )
        .scalars()
        .all()
    )
    procurements = [(row, _proc_to_item(row)) for row in proc_rows]

    return jobs, changes, procurements


def _job_to_item(row: JobPosting) -> JobPostingItem:
    return JobPostingItem(
        external_id=row.external_id,
        employer_orgnr=None,
        employer_name=row.employer_name,
        headline=row.headline,
        description=row.description,
        occupation_label=row.occupation_label,
        occupation_concept_id=row.occupation_concept_id,
        workplace_municipality=row.workplace_municipality,
        workplace_county=row.workplace_county,
        employment_type=row.employment_type,
        duration=row.duration,
        published_at=row.published_at,
        source_url=row.source_url,
    )


def _change_to_item(row: CompanyChange, company: Company) -> CompanyChangeItem:
    return CompanyChangeItem(
        orgnr=company.orgnr,
        company_name=company.name,
        change_type=row.change_type,  # type: ignore[arg-type]
        old_value=row.old_value,
        new_value=row.new_value,
        source_ref=row.source_ref,
        changed_at=row.changed_at,
    )


def _proc_to_item(row: Procurement) -> ProcurementItem:
    return ProcurementItem(
        external_id=row.external_id,
        buyer_orgnr=row.buyer_orgnr,
        buyer_name=row.buyer_name,
        title=row.title,
        description=row.description,
        cpv_codes=list(row.cpv_codes or []),
        estimated_value_sek=row.estimated_value_sek,
        procedure_type=row.procedure_type,
        deadline=row.deadline,
        source_url=row.source_url,
        source=row.source,
    )


CHANGE_LABELS = {
    "ceo": "Ny VD",
    "board_member": "Styrelseändring",
    "address": "Adressändring",
    "name": "Namnändring",
    "remark": "Anmärkning",
    "liquidation": "Likvidation",
    "sni": "Verksamhetsändring",
}


async def _already_delivered(
    session: AsyncSession,
    user_id: int,
    *,
    signal_type: str,
    signal_ids: Sequence[int],
) -> set[int]:
    if not signal_ids:
        return set()
    rows = await session.execute(
        select(DeliveredAlert.signal_id).where(
            DeliveredAlert.user_id == user_id,
            DeliveredAlert.signal_type == signal_type,
            DeliveredAlert.signal_id.in_(signal_ids),
        )
    )
    return {row[0] for row in rows.all()}


def _build_unsubscribe_url(base: str, token: str) -> str:
    return f"{base.rstrip('/')}/unsubscribe?{urlencode({'t': token})}"


async def assemble_user_digest(
    session: AsyncSession,
    user: User,
    subscriptions: list[Subscription],
    *,
    jobs: list[tuple[JobPosting, JobPostingItem]],
    changes: list[tuple[CompanyChange, CompanyChangeItem, Company]],
    procurements: list[tuple[Procurement, ProcurementItem]],
) -> list[_DigestSection]:
    """Filter the pre-loaded signals against each subscription for this user."""
    sections: list[_DigestSection] = []

    delivered_jobs = await _already_delivered(
        session, user.id, signal_type="job", signal_ids=[r.id for r, _ in jobs]
    )
    delivered_changes = await _already_delivered(
        session,
        user.id,
        signal_type="company_change",
        signal_ids=[r.id for r, _, _ in changes],
    )
    delivered_procs = await _already_delivered(
        session,
        user.id,
        signal_type="procurement",
        signal_ids=[r.id for r, _ in procurements],
    )

    for sub in subscriptions:
        if not sub.active:
            continue
        criteria = Criteria.model_validate(sub.criteria)
        items: list[_DigestItem] = []

        if "job" in sub.signal_types:
            for row, item in jobs:
                if row.id in delivered_jobs:
                    continue
                if not match_job_posting(item, criteria):
                    continue
                items.append(
                    _DigestItem(
                        kind="job",
                        kind_label="Jobb",
                        title=f"{row.employer_name} söker — {row.headline}",
                        detail=" · ".join(
                            filter(
                                None,
                                [
                                    row.workplace_municipality,
                                    row.employment_type,
                                    row.duration,
                                ],
                            )
                        )
                        or None,
                        source_url=row.source_url,
                        date_label=_format_short(row.published_at),
                        signal_id=row.id,
                    )
                )

        if "company_change" in sub.signal_types:
            for row, item, company in changes:
                if row.id in delivered_changes:
                    continue
                if not match_company_change(
                    item,
                    criteria,
                    company_municipality=company.hq_municipality,
                    company_county=company.hq_county,
                    company_sni=company.sni_code,
                ):
                    continue
                items.append(
                    _DigestItem(
                        kind="company_change",
                        kind_label=CHANGE_LABELS.get(row.change_type, "Bolagsändring"),
                        title=company.name,
                        detail=f"Org.nr {company.orgnr}",
                        source_url=row.source_ref,
                        date_label=_format_short(row.changed_at),
                        signal_id=row.id,
                    )
                )

        if "procurement" in sub.signal_types:
            for row, item in procurements:
                if row.id in delivered_procs:
                    continue
                if not match_procurement(item, criteria):
                    continue
                items.append(
                    _DigestItem(
                        kind="procurement",
                        kind_label="Upphandling",
                        title=row.title,
                        detail=row.buyer_name,
                        source_url=row.source_url,
                        date_label=_format_short(row.ingested_at),
                        signal_id=row.id,
                    )
                )

        if items:
            sections.append(
                _DigestSection(
                    subscription_id=sub.id, subscription_name=sub.name, items=items
                )
            )

    return sections


async def _record_deliveries(
    session: AsyncSession, user_id: int, sections: list[_DigestSection], message_id: str
) -> None:
    rows: list[dict[str, Any]] = []
    for section in sections:
        for item in section.items:
            rows.append(
                {
                    "user_id": user_id,
                    "subscription_id": section.subscription_id,
                    "signal_type": item.kind,
                    "signal_id": item.signal_id,
                    "resend_message_id": message_id,
                }
            )
    if not rows:
        return
    stmt = (
        pg_insert(DeliveredAlert)
        .values(rows)
        .on_conflict_do_nothing(
            index_elements=["user_id", "signal_type", "signal_id"]
        )
    )
    await session.execute(stmt)


async def run_daily_digest() -> None:
    """Top-level scheduler entry — runs once per day."""
    settings = get_settings()
    now = datetime.now(timezone.utc)
    since = now - timedelta(hours=LOOKBACK_HOURS)
    sent = 0
    skipped = 0
    log = logger.bind(job="daily_digest", since=since.isoformat())
    log.info("digest_started")

    async with session_scope() as session:
        jobs, changes, procurements = await _load_user_signals(session, since=since)
        users = (
            await session.execute(
                select(User).where(User.is_active.is_(True), User.is_verified.is_(True))
            )
        ).scalars().all()

        for user in users:
            subs = (
                await session.execute(
                    select(Subscription).where(
                        Subscription.user_id == user.id,
                        Subscription.active.is_(True),
                    )
                )
            ).scalars().all()
            if not subs:
                skipped += 1
                continue

            sections = await assemble_user_digest(
                session,
                user,
                list(subs),
                jobs=jobs,
                changes=changes,
                procurements=procurements,
            )
            total = sum(len(s.items) for s in sections)
            if total == 0:
                skipped += 1
                continue

            base_url = str(settings.app_base_url).rstrip("/")
            context = {
                "subject": f"Vittring — {total} nya signaler ({_format_swedish_date(now)})",
                "from_address": settings.email_from_address,
                "total": total,
                "digest_date": _format_swedish_date(now),
                "sections": [
                    {
                        "subscription_name": s.subscription_name,
                        "items": [
                            {
                                "kind_label": i.kind_label,
                                "title": i.title,
                                "detail": i.detail,
                                "source_url": i.source_url,
                                "date_label": i.date_label,
                            }
                            for i in s.items
                        ],
                    }
                    for s in sections
                ],
                "manage_url": f"{base_url}/app/subscriptions",
                "unsubscribe_url": _build_unsubscribe_url(base_url, str(user.id)),
                "contact_address": "Vittring c/o Karim Khalil, Sverige",
            }

            html = render("digest.html.j2", **context)
            text = render("digest.txt.j2", **context)
            email = await send_email(
                to=user.email,
                subject=context["subject"],
                html=html,
                text=text,
                tags={"kind": "digest"},
            )
            await _record_deliveries(session, user.id, sections, email.message_id)
            sent += 1

    log.info("digest_completed", emails_sent=sent, users_skipped=skipped)
