"""Account dashboard, profile, GDPR export and deletion."""

from __future__ import annotations

import csv
import io
import json
from datetime import datetime, timedelta, timezone
from typing import Annotated, Any

from fastapi import APIRouter, Form, Query, Request, status
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from pydantic import ValidationError
from sqlalchemy import delete, func, select

from vittring.api.deps import CurrentVerifiedUser, request_meta
from vittring.api.templates import templates
from vittring.audit.log import AuditAction, audit
from vittring.db import SessionDep
from vittring.matching.criteria import Criteria
from vittring.matching.engine import (
    match_company_change,
    match_job_posting,
    match_procurement,
)
from vittring.models.audit import AuditLog
from vittring.models.company import Company
from vittring.models.saved import SavedSignal
from vittring.models.signals import CompanyChange, JobPosting, Procurement
from vittring.models.subscription import DeliveredAlert, Subscription
from vittring.schemas.ingest import (
    CompanyChangeItem,
    JobPostingItem,
    ProcurementItem,
)

router = APIRouter(prefix="/app", tags=["account"])

SWEDISH_WEEKDAYS = ["måndag", "tisdag", "onsdag", "torsdag", "fredag", "lördag", "söndag"]
SWEDISH_MONTHS = [
    "januari", "februari", "mars", "april", "maj", "juni",
    "juli", "augusti", "september", "oktober", "november", "december",
]
PLAN_LABELS = {"trial": "Provperiod", "solo": "Solo", "team": "Team", "pro": "Pro"}


def _initials(name: str) -> str:
    parts = [p for p in name.replace(".", " ").split() if p]
    if len(parts) >= 2:
        return (parts[0][0] + parts[1][0]).upper()
    if parts:
        return parts[0][:2].upper()
    return "—"


def _example_signals() -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Sample feed used until the user has live signals delivered.

    Mirrors the Vittring design hand-off so the dashboard reads as populated
    on day one. Once ingest + matching produce real DeliveredAlert rows for
    the user, swap this for a query joining DeliveredAlert with the
    referenced signal tables.
    """
    priority = [
        {
            "id": 1,
            "date": "04 maj", "time": "16:42",
            "kind": "Upphandling", "kind_class": "upph",
            "title": "Region Stockholm — Ramavtal lagerbemanning",
            "meta": "CPV 79620000 · Volym ~12 mkr · Anbud senast 2026-06-12 · 3 leverantörer förväntade",
            "source": "Vittring",
            "url": None,
        },
        {
            "id": 2,
            "date": "04 maj", "time": "14:32",
            "kind": "Jobb", "kind_class": "jobb",
            "title": "Postnord Sverige AB söker 18 truckförare",
            "meta": "Rosersberg · SNI 53.100 · Heltid · Tredje volymrekrytering på sex månader",
            "source": "Vittring",
            "url": None,
        },
        {
            "id": 3,
            "date": "04 maj", "time": "09:15",
            "kind": "Bolag", "kind_class": "bolag",
            "title": "Ahlsell Logistik AB · Ny VD tillträder",
            "meta": "SE5567231223 · Hallsberg · Helena Berg, tidigare COO DB Schenker",
            "source": "Vittring",
            "url": None,
        },
        {
            "id": 4,
            "date": "04 maj", "time": "08:07",
            "kind": "Jobb", "kind_class": "jobb",
            "title": "Schenker AB — 6 lagermedarbetare, kvällsskift",
            "meta": "Jordbro · SNI 52.100 · Visstidsanställning",
            "source": "Vittring",
            "url": None,
        },
        {
            "id": 5,
            "date": "03 maj", "time": "22:11",
            "kind": "Bolag", "kind_class": "bolag",
            "title": "Norrlands Logistik AB · Nytt säte i Södertälje",
            "meta": "SE5566048812 · Tidigare Sundsvall · Indikerar utbyggnad i Mälardalen",
            "source": "Vittring",
            "url": None,
        },
    ]
    others = [
        {
            "id": 6,
            "date": "03 maj", "time": "17:44",
            "kind": "Upphandling", "kind_class": "upph",
            "title": "Trafikförvaltningen — Bemanningstjänster städ & logistik",
            "meta": "CPV 79620000 · ~8 mkr · Anbud 2026-05-30",
            "source": "Vittring",
            "url": None,
        },
        {
            "id": 7,
            "date": "03 maj", "time": "15:22",
            "kind": "Jobb", "kind_class": "jobb",
            "title": "DSV — 4 lagerarbetare, dagtid",
            "meta": "Arlanda · SNI 52.100 · Tillsvidare",
            "source": "Vittring",
            "url": None,
        },
        {
            "id": 8,
            "date": "03 maj", "time": "12:08",
            "kind": "Bolag", "kind_class": "bolag",
            "title": "Bring Frigoscandia AB — styrelseändring",
            "meta": "SE5567 · Två nya ledamöter, fokus tech",
            "source": "Vittring",
            "url": None,
        },
        {
            "id": 9,
            "date": "03 maj", "time": "10:55",
            "kind": "Jobb", "kind_class": "jobb",
            "title": "DHL Supply Chain — 12 plockare",
            "meta": "Brunna · SNI 52.100 · Heltid",
            "source": "Vittring",
            "url": None,
        },
        {
            "id": 10,
            "date": "03 maj", "time": "09:30",
            "kind": "Upphandling", "kind_class": "upph",
            "title": "Botkyrka kommun — Bemanning skola/förskola",
            "meta": "CPV 79620000 · ~3 mkr · Anbud 2026-05-25",
            "source": "Vittring",
            "url": None,
        },
    ]
    return priority, others


def _filter_signals(
    signals: list[dict[str, Any]], q: str
) -> list[dict[str, Any]]:
    """Case-insensitive substring filter over title and meta fields."""
    needle = q.strip().lower()
    if not needle:
        return signals
    return [
        s
        for s in signals
        if needle in s.get("title", "").lower()
        or needle in s.get("meta", "").lower()
    ]


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------

@router.get("", response_class=HTMLResponse, include_in_schema=False)
async def dashboard(
    request: Request,
    session: SessionDep,
    user: CurrentVerifiedUser,
    q: str = "",
    type: Annotated[str, Query()] = "",
) -> HTMLResponse:
    """Today's digest, rendered live from the DB.

    The user's active Subscription criteria filter every JobPosting,
    CompanyChange and Procurement from the last 26 hours through the
    matching engine. If the user has no subscriptions yet we fall back
    to a sample feed so the page reads as something rather than blank.

    Query params:
      ``q``    case-insensitive substring filter over title + meta
      ``type`` filter chip (one of ``upph``, ``jobb``, ``bolag``)
    """
    subs_rows = (
        await session.execute(
            select(Subscription).where(
                Subscription.user_id == user.id,
                Subscription.active.is_(True),
            ).order_by(Subscription.created_at.desc())
        )
    ).scalars().all()

    saved_count = (
        await session.execute(
            select(func.count())
            .select_from(SavedSignal)
            .where(SavedSignal.user_id == user.id)
        )
    ).scalar_one()

    now = datetime.now(timezone.utc)
    since = now - timedelta(hours=26)
    week_ago = now - timedelta(days=7)

    week_count = (
        await session.execute(
            select(func.count())
            .select_from(DeliveredAlert)
            .where(
                DeliveredAlert.user_id == user.id,
                DeliveredAlert.delivered_at >= week_ago,
            )
        )
    ).scalar_one()

    all_signals = await _load_dashboard_signals(session, subs_rows, since=since)
    has_real_data = bool(subs_rows) or bool(all_signals)
    if not has_real_data:
        priority_signals, other_signals = _example_signals()
        all_signals = priority_signals + other_signals

    if type and type in {"upph", "jobb", "bolag"}:
        all_signals = [s for s in all_signals if s["kind_class"] == type]
    if q:
        all_signals = _filter_signals(all_signals, q)

    # First five = priority strip, rest goes under "Övriga". With real
    # data the matching engine has already done the work; ranking by
    # recency keeps the most actionable items at the top.
    priority_signals = all_signals[:5]
    other_signals = all_signals[5:]
    digest_count = len(all_signals)

    today_weekday = SWEDISH_WEEKDAYS[now.weekday()].capitalize()
    today_date = f"{now.day} {SWEDISH_MONTHS[now.month - 1]} {now.year}"
    week_num = now.isocalendar().week

    subs = [{"name": s.name, "signal_count": None} for s in subs_rows]

    # Surface the criteria that are actually doing the filtering so the
    # user sees what's been selected (instead of a hardcoded list).
    active_filters: list[str] = []
    for s in subs_rows:
        crit = s.criteria or {}
        for muni in (crit.get("municipalities") or [])[:2]:
            if muni and muni not in active_filters:
                active_filters.append(muni)
        for code in (crit.get("sni_codes") or [])[:2]:
            label = f"SNI {code}"
            if label not in active_filters:
                active_filters.append(label)
        for cpv in (crit.get("cpv_codes") or [])[:2]:
            label = f"CPV {cpv}"
            if label not in active_filters:
                active_filters.append(label)
    active_filters = active_filters[:4]

    name_for_initials = user.full_name or user.email.split("@")[0]

    context = {
        "title": "Dashboard",
        "user": user,
        "subscriptions": subs,
        "initials": _initials(name_for_initials),
        "plan_label": PLAN_LABELS.get(user.plan, user.plan.capitalize()),
        "active": "overview",

        "today_weekday": today_weekday,
        "today_date": today_date,
        "last_sync_time": "06:30",
        "next_sync_time": "06:30",

        "digest_count": digest_count,
        "digest_focus": subs[0]["name"] if subs else "Konfigurera en prenumeration",
        "priority_count": len(priority_signals),
        "other_count": len(other_signals),
        "saved_count": saved_count,
        "is_sample_only": not has_real_data,

        "stat_week_count": str(week_count) if has_real_data else "214",
        "stat_week_delta": "" if has_real_data else "+18%",
        "stat_noise_pct": "" if has_real_data else "99,5%",
        "stat_noise_total": "" if has_real_data else "4 982",
        "stat_week_num": week_num,
        "stat_conversions": "" if has_real_data else "7",
        "stat_conversions_delta": "" if has_real_data else "+2",

        "active_filters": active_filters,
        "count_upph": sum(1 for s in priority_signals + other_signals if s["kind_class"] == "upph"),
        "count_jobb": sum(1 for s in priority_signals + other_signals if s["kind_class"] == "jobb"),
        "count_bolag": sum(1 for s in priority_signals + other_signals if s["kind_class"] == "bolag"),
        "active_type": type if type in {"upph", "jobb", "bolag"} else "",

        "priority_signals": priority_signals,
        "other_signals": other_signals,
        "search_query": q,
    }
    return templates.TemplateResponse(request, "app/dashboard.html.j2", context)


async def _load_dashboard_signals(
    session: Any,
    subs_rows: list[Subscription],
    *,
    since: datetime,
) -> list[dict[str, Any]]:
    """Return one unified, recency-sorted feed of signals matching subs.

    Pulls JobPosting / CompanyChange / Procurement rows from the last
    ``since``-window and runs each through the matching engine against
    every active Subscription. If no procurement-targeting subscription
    is active for a given signal type, that type isn't included — same
    contract as the daily digest.
    """
    proc_criteria: list[Criteria] = []
    job_criteria: list[Criteria] = []
    change_criteria: list[Criteria] = []
    for s in subs_rows:
        try:
            crit = Criteria.model_validate(s.criteria or {})
        except ValidationError:
            continue
        signal_types = s.signal_types or []
        if "procurement" in signal_types:
            proc_criteria.append(crit)
        if "job" in signal_types:
            job_criteria.append(crit)
        if "company_change" in signal_types:
            change_criteria.append(crit)

    out: list[dict[str, Any]] = []

    # ---- procurements ----------------------------------------------------
    if proc_criteria or not subs_rows:
        proc_rows = (
            await session.execute(
                select(Procurement)
                .where(Procurement.ingested_at >= since)
                .order_by(Procurement.ingested_at.desc())
                .limit(100)
            )
        ).scalars().all()

        if proc_rows:
            buyer_orgnrs = {r.buyer_orgnr for r in proc_rows if r.buyer_orgnr}
            municipality_by_orgnr: dict[str, str | None] = {}
            if buyer_orgnrs:
                rows = await session.execute(
                    select(Company.orgnr, Company.hq_municipality).where(
                        Company.orgnr.in_(buyer_orgnrs)
                    )
                )
                municipality_by_orgnr = dict(rows.all())

            for r in proc_rows:
                item = ProcurementItem(
                    external_id=r.external_id,
                    buyer_orgnr=r.buyer_orgnr,
                    buyer_name=r.buyer_name,
                    title=r.title,
                    description=r.description,
                    cpv_codes=list(r.cpv_codes or []),
                    estimated_value_sek=r.estimated_value_sek,
                    procedure_type=r.procedure_type,
                    deadline=r.deadline,
                    source_url=r.source_url,
                    source=r.source,
                )
                buyer_muni = (
                    municipality_by_orgnr.get(r.buyer_orgnr) if r.buyer_orgnr else None
                )
                if proc_criteria and not any(
                    match_procurement(item, c, buyer_municipality=buyer_muni)
                    for c in proc_criteria
                ):
                    continue
                out.append(_signal_dict_procurement(r))

    # ---- jobs ------------------------------------------------------------
    if job_criteria or not subs_rows:
        job_rows = (
            await session.execute(
                select(JobPosting)
                .where(JobPosting.published_at >= since)
                .order_by(JobPosting.published_at.desc())
                .limit(100)
            )
        ).scalars().all()

        if job_rows:
            company_ids = {r.company_id for r in job_rows if r.company_id is not None}
            orgnr_by_company_id: dict[int, str] = {}
            if company_ids:
                rows = await session.execute(
                    select(Company.id, Company.orgnr).where(Company.id.in_(company_ids))
                )
                orgnr_by_company_id = dict(rows.all())

            for r in job_rows:
                item = JobPostingItem(
                    external_id=r.external_id,
                    employer_orgnr=orgnr_by_company_id.get(r.company_id)
                    if r.company_id is not None
                    else None,
                    employer_name=r.employer_name,
                    headline=r.headline,
                    description=r.description,
                    occupation_label=r.occupation_label,
                    occupation_concept_id=r.occupation_concept_id,
                    workplace_municipality=r.workplace_municipality,
                    workplace_county=r.workplace_county,
                    employment_type=r.employment_type,
                    duration=r.duration,
                    published_at=r.published_at,
                    source_url=r.source_url,
                )
                if job_criteria and not any(match_job_posting(item, c) for c in job_criteria):
                    continue
                out.append(_signal_dict_job(r))

    # ---- company changes -------------------------------------------------
    if change_criteria or not subs_rows:
        change_rows = (
            await session.execute(
                select(CompanyChange, Company)
                .join(Company, CompanyChange.company_id == Company.id)
                .where(CompanyChange.changed_at >= since)
                .order_by(CompanyChange.changed_at.desc())
                .limit(100)
            )
        ).all()

        for change_row, company in change_rows:
            item = CompanyChangeItem(
                orgnr=company.orgnr,
                company_name=company.name,
                change_type=change_row.change_type,  # type: ignore[arg-type]
                old_value=change_row.old_value,
                new_value=change_row.new_value,
                source_ref=change_row.source_ref,
                changed_at=change_row.changed_at,
            )
            if change_criteria and not any(
                match_company_change(item, c, hq_municipality=company.hq_municipality)
                for c in change_criteria
            ):
                continue
            out.append(_signal_dict_change(change_row, company))

    out.sort(key=lambda s: s["sort_key"], reverse=True)
    return out[:50]


def _short_date(dt: datetime | None) -> tuple[str, str]:
    if dt is None:
        return "—", ""
    return f"{dt.day:02d} {SWEDISH_MONTHS[dt.month - 1][:3]}", dt.strftime("%H:%M")


def _signal_dict_procurement(r: Procurement) -> dict[str, Any]:
    date, time = _short_date(r.ingested_at)
    cpv = (r.cpv_codes or [None])[0]
    deadline_label = (
        f"Anbud {r.deadline.strftime('%Y-%m-%d')}" if r.deadline else "Ingen deadline"
    )
    parts: list[str] = []
    if cpv:
        parts.append(f"CPV {cpv}")
    if r.estimated_value_sek:
        parts.append(f"~{r.estimated_value_sek // 1_000_000} mkr")
    parts.append(deadline_label)
    return {
        "id": f"proc-{r.id}",
        "signal_id": r.id,
        "signal_type": "procurement",
        "date": date,
        "time": time,
        "kind": "Upphandling",
        "kind_class": "upph",
        "title": f"{r.buyer_name} — {r.title}",
        "meta": " · ".join(parts),
        "source": (r.source or "Vittring").capitalize(),
        "url": r.source_url,
        "sort_key": r.ingested_at,
    }


def _signal_dict_job(r: JobPosting) -> dict[str, Any]:
    date, time = _short_date(r.published_at)
    parts: list[str] = []
    if r.workplace_municipality:
        parts.append(r.workplace_municipality)
    if r.occupation_label:
        parts.append(r.occupation_label)
    if r.employment_type:
        parts.append(r.employment_type)
    return {
        "id": f"job-{r.id}",
        "signal_id": r.id,
        "signal_type": "job",
        "date": date,
        "time": time,
        "kind": "Jobb",
        "kind_class": "jobb",
        "title": f"{r.employer_name} — {r.headline}",
        "meta": " · ".join(parts) or "—",
        "source": "JobTech",
        "url": r.source_url,
        "sort_key": r.published_at,
    }


def _signal_dict_change(r: CompanyChange, company: Company) -> dict[str, Any]:
    date, time = _short_date(r.changed_at)
    label = {
        "ceo": "Ny VD",
        "board_member": "Styrelseändring",
        "address": "Adressändring",
        "name": "Namnändring",
        "remark": "Anmärkning",
        "liquidation": "Likvidation",
        "sni": "Verksamhetsändring",
    }.get(r.change_type, "Bolagsändring")
    parts = [company.orgnr]
    if company.hq_municipality:
        parts.append(company.hq_municipality)
    return {
        "id": f"change-{r.id}",
        "signal_id": r.id,
        "signal_type": "company_change",
        "date": date,
        "time": time,
        "kind": "Bolag",
        "kind_class": "bolag",
        "title": f"{company.name} · {label}",
        "meta": " · ".join(parts),
        "source": "Bolagsverket",
        "url": r.source_ref,
        "sort_key": r.changed_at,
    }


# ---------------------------------------------------------------------------
# Sidebar stubs ("Kommer snart")
# ---------------------------------------------------------------------------

def _stub_context(user: Any, active: str, title: str, description: str) -> dict[str, Any]:
    name_for_initials = user.full_name or user.email.split("@")[0]
    return {
        "title": title,
        "user": user,
        "initials": _initials(name_for_initials),
        "plan_label": PLAN_LABELS.get(user.plan, user.plan.capitalize()),
        "subscriptions": [],
        "active": active,
        "stub_title": title,
        "stub_description": description,
    }


@router.get("/calendar", response_class=HTMLResponse, include_in_schema=False)
async def calendar(
    request: Request,
    session: SessionDep,
    user: CurrentVerifiedUser,
    q: Annotated[str | None, Query(max_length=80)] = None,
) -> HTMLResponse:
    """Upcoming deadlines and dates relevant to this user.

    Procurements are filtered through the matching engine against the
    user's active subscriptions — same code path as the daily email
    digest. If the user has no active subscriptions, every recent
    procurement is shown so the page is useful before they configure
    anything.

    The ``q`` query param applies an additional case-insensitive
    substring filter over title + buyer + description, intended for
    quick ad-hoc lookups ("bemanning", "lager", "vårdpersonal").
    """
    from vittring.models.signals import Procurement

    now = datetime.now(timezone.utc)
    horizon = now + timedelta(days=90)
    q_norm = (q or "").strip()
    q_lower = q_norm.casefold() or None

    subs_rows = (
        await session.execute(
            select(Subscription).where(
                Subscription.user_id == user.id,
                Subscription.active.is_(True),
            )
        )
    ).scalars().all()

    # Parse each subscription's JSONB criteria into a typed Criteria.
    # Skip subscriptions that don't target procurements or whose stored
    # criteria fail validation (e.g. shape drift after a schema change) —
    # they shouldn't blow up the calendar render.
    proc_criteria: list[Criteria] = []
    for sub in subs_rows:
        if "procurement" not in (sub.signal_types or []):
            continue
        try:
            proc_criteria.append(Criteria.model_validate(sub.criteria or {}))
        except ValidationError:
            continue

    proc_rows = (
        await session.execute(
            select(Procurement)
            .where(
                Procurement.deadline.is_not(None),
                Procurement.deadline >= now,
                Procurement.deadline <= horizon,
            )
            .order_by(Procurement.deadline.asc())
            .limit(200)
        )
    ).scalars().all()

    def _matches_subscriptions(p: Procurement) -> bool:
        if not proc_criteria:
            return True  # no procurement-targeting subs -> show everything
        item = ProcurementItem(
            external_id=p.external_id,
            buyer_orgnr=p.buyer_orgnr,
            buyer_name=p.buyer_name,
            title=p.title,
            description=p.description,
            cpv_codes=list(p.cpv_codes or []),
            estimated_value_sek=p.estimated_value_sek,
            procedure_type=p.procedure_type,
            deadline=p.deadline,
            source_url=p.source_url,
            source=p.source,
        )
        return any(match_procurement(item, c) for c in proc_criteria)

    def _matches_q(p: Procurement) -> bool:
        if q_lower is None:
            return True
        haystack = " ".join(
            x for x in (p.title, p.buyer_name, p.description) if x
        ).casefold()
        return q_lower in haystack

    matched_procs = [
        p for p in proc_rows if _matches_subscriptions(p) and _matches_q(p)
    ][:25]

    events: list[dict[str, Any]] = []
    for p in matched_procs:
        events.append(
            {
                "kind": "Upphandling",
                "kind_class": "upph",
                "title": p.title,
                "detail": p.buyer_name,
                "date": p.deadline,
                "url": p.source_url,
            }
        )

    # The trial-expiration card is personal, not a procurement signal —
    # it shouldn't disappear when the user runs an ad-hoc keyword search.
    if user.trial_ends_at and user.trial_ends_at > now and q_lower is None:
        events.append(
            {
                "kind": "Provperiod",
                "kind_class": "trial",
                "title": "Provperiod löper ut",
                "detail": "Välj en plan innan dess för att fortsätta få digesten",
                "date": user.trial_ends_at,
                "url": "/pricing",
            }
        )

    # Show sample deadlines only if the procurements table is empty *and*
    # no filters are active — otherwise an empty result for "bemanning"
    # would lie to the user with fake bemanning hits.
    is_sample_only = (
        not proc_rows
        and not proc_criteria
        and q_lower is None
        and (not user.trial_ends_at or user.trial_ends_at <= now)
    )
    if not proc_rows and not proc_criteria and q_lower is None:
        sample_dates = [
            (now + timedelta(days=delta), title, buyer)
            for delta, title, buyer in (
                (8, "Region Stockholm — Ramavtal lagerbemanning", "Region Stockholm"),
                (15, "Trafikförvaltningen — Bemanningstjänster städ & logistik", "Trafikförvaltningen"),
                (24, "Botkyrka kommun — Bemanning skola/förskola", "Botkyrka kommun"),
                (38, "Göteborgs kommun — Vårdpersonal äldreomsorg", "Göteborgs kommun"),
            )
        ]
        for d, title, buyer in sample_dates:
            events.append(
                {
                    "kind": "Upphandling",
                    "kind_class": "upph",
                    "title": title,
                    "detail": buyer,
                    "date": d,
                    "url": None,
                    "is_sample": True,
                }
            )

    events.sort(key=lambda e: e["date"])

    grouped: dict[str, list[dict[str, Any]]] = {}
    for ev in events:
        key = ev["date"].strftime("%Y-%m-%d")
        grouped.setdefault(key, []).append(ev)

    name_for_initials = user.full_name or user.email.split("@")[0]

    return templates.TemplateResponse(
        request,
        "app/calendar.html.j2",
        {
            "title": "Kalender",
            "user": user,
            "subscriptions": [{"name": s.name} for s in subs_rows],
            "initials": _initials(name_for_initials),
            "plan_label": PLAN_LABELS.get(user.plan, user.plan.capitalize()),
            "active": "calendar",
            "grouped": grouped,
            "total_events": len(events),
            "is_sample_only": is_sample_only,
            "now_date": now.date(),
            "q": q_norm,
            "filter_active": bool(proc_criteria) or q_lower is not None,
            "subscription_filter_count": len(proc_criteria),
            "matched_procurements": len(matched_procs),
            "total_procurements": len(proc_rows),
        },
    )


@router.get("/saved", response_class=HTMLResponse, include_in_schema=False)
async def saved_signals(
    request: Request, session: SessionDep, user: CurrentVerifiedUser
) -> HTMLResponse:
    """List the user's starred signals.

    Joins SavedSignal with the matching sample-signal context so the page
    is meaningful even before live signals exist. Once real DeliveredAlert
    rows show up, swap the lookup to query the actual signal tables by
    (signal_type, signal_id).
    """
    saved_rows = (
        await session.execute(
            select(SavedSignal)
            .where(SavedSignal.user_id == user.id)
            .order_by(SavedSignal.saved_at.desc())
        )
    ).scalars().all()

    # Build a lookup over the dashboard's sample feed so we can show
    # meaningful titles for each saved id without hitting more tables.
    priority, others = _example_signals()
    sample_by_id: dict[int, dict[str, Any]] = {s["id"]: s for s in priority + others}

    items: list[dict[str, Any]] = []
    for r in saved_rows:
        sample = sample_by_id.get(r.signal_id)
        items.append(
            {
                "saved_at": r.saved_at,
                "signal_type": r.signal_type,
                "signal_id": r.signal_id,
                "kind": (sample or {}).get("kind", r.signal_type.title()),
                "kind_class": (sample or {}).get("kind_class", "neutral"),
                "title": (sample or {}).get("title", f"Signal #{r.signal_id}"),
                "meta": (sample or {}).get("meta", ""),
                "url": (sample or {}).get("url"),
            }
        )

    subs_rows = (
        await session.execute(
            select(Subscription).where(
                Subscription.user_id == user.id,
                Subscription.active.is_(True),
            )
        )
    ).scalars().all()
    name_for_initials = user.full_name or user.email.split("@")[0]

    return templates.TemplateResponse(
        request,
        "app/saved.html.j2",
        {
            "title": "Sparade signaler",
            "user": user,
            "subscriptions": [{"name": s.name} for s in subs_rows],
            "initials": _initials(name_for_initials),
            "plan_label": PLAN_LABELS.get(user.plan, user.plan.capitalize()),
            "active": "saved",
            "items": items,
        },
    )


@router.get("/archive", response_class=HTMLResponse, include_in_schema=False)
async def archive_stub(request: Request, user: CurrentVerifiedUser) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        "app/_stub.html.j2",
        _stub_context(
            user,
            active="archive",
            title="Arkiv",
            description=(
                "Signaler som är äldre än 30 dagar arkiveras automatiskt här. Använd "
                "arkivet för att leta upp historik på ett bolag eller en upphandling."
            ),
        ),
    )


@router.get("/tags", response_class=HTMLResponse, include_in_schema=False)
async def tags_stub(request: Request, user: CurrentVerifiedUser) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        "app/_stub.html.j2",
        _stub_context(
            user,
            active="tags",
            title="Taggar",
            description=(
                "Kategorisera signaler för uppföljning — t.ex. ”ringt”, ”möte bokat” "
                "eller egna kundsegment — och filtrera digesten på dina taggar."
            ),
        ),
    )


# ---------------------------------------------------------------------------
# CSV export of recent delivered alerts
# ---------------------------------------------------------------------------

@router.get("/export.csv", include_in_schema=False)
async def export_csv(
    session: SessionDep, user: CurrentVerifiedUser
) -> Response:
    """Stream a CSV of the user's most recent 1 000 delivered alerts.

    Header is always present even when no rows exist. Real DeliveredAlert
    rows take precedence; if the user has no delivered alerts yet the body
    contains only the header — empty digest is a valid state.
    """
    rows = (
        await session.execute(
            select(DeliveredAlert)
            .where(DeliveredAlert.user_id == user.id)
            .order_by(DeliveredAlert.delivered_at.desc())
            .limit(1000)
        )
    ).scalars().all()

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(
        [
            "delivered_at",
            "signal_type",
            "signal_id",
            "subscription_id",
            "opened_at",
            "clicked_at",
        ]
    )
    for r in rows:
        writer.writerow(
            [
                r.delivered_at.isoformat() if r.delivered_at else "",
                r.signal_type,
                r.signal_id,
                r.subscription_id,
                r.opened_at.isoformat() if r.opened_at else "",
                r.clicked_at.isoformat() if r.clicked_at else "",
            ]
        )

    # utf-8-sig prefixes a UTF-8 BOM so Excel renders Swedish characters
    # (å, ä, ö) correctly when the file is double-clicked. Plain utf-8
    # without BOM otherwise shows mojibake on Windows defaults.
    return Response(
        content=("﻿" + buf.getvalue()).encode("utf-8"),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": 'attachment; filename=vittring-export.csv'
        },
    )


# ---------------------------------------------------------------------------
# Save / unsave signal
# ---------------------------------------------------------------------------

@router.post("/signals/save", include_in_schema=False)
async def toggle_saved_signal(
    request: Request,
    session: SessionDep,
    user: CurrentVerifiedUser,
    signal_type: Annotated[str, Form()],
    signal_id: Annotated[int, Form()],
) -> RedirectResponse:
    """Toggle a row in ``saved_signals``: insert if missing, delete if present."""
    existing = (
        await session.execute(
            select(SavedSignal).where(
                SavedSignal.user_id == user.id,
                SavedSignal.signal_type == signal_type,
                SavedSignal.signal_id == signal_id,
            )
        )
    ).scalar_one_or_none()

    meta = request_meta(request)
    if existing is None:
        session.add(
            SavedSignal(
                user_id=user.id,
                signal_type=signal_type,
                signal_id=signal_id,
            )
        )
        await audit(
            session,
            action="signal_saved",
            user_id=user.id,
            ip=meta["ip"],
            user_agent=meta["user_agent"],
            metadata={"signal_type": signal_type, "signal_id": signal_id},
        )
    else:
        await session.execute(
            delete(SavedSignal).where(SavedSignal.id == existing.id)
        )
        await audit(
            session,
            action="signal_unsaved",
            user_id=user.id,
            ip=meta["ip"],
            user_agent=meta["user_agent"],
            metadata={"signal_type": signal_type, "signal_id": signal_id},
        )

    return RedirectResponse(
        f"/app#saved-{signal_id}", status_code=status.HTTP_303_SEE_OTHER
    )


# ---------------------------------------------------------------------------
# Account profile page
# ---------------------------------------------------------------------------

@router.get("/account", response_class=HTMLResponse, include_in_schema=False)
async def account_page(
    request: Request, session: SessionDep, user: CurrentVerifiedUser
) -> HTMLResponse:
    subs_rows = (
        await session.execute(
            select(Subscription).where(
                Subscription.user_id == user.id,
                Subscription.active.is_(True),
            ).order_by(Subscription.created_at.desc())
        )
    ).scalars().all()
    name_for_initials = user.full_name or user.email.split("@")[0]
    return templates.TemplateResponse(
        request,
        "app/account.html.j2",
        {
            "title": "Inställningar",
            "user": user,
            "subscriptions": [{"name": s.name} for s in subs_rows],
            "initials": _initials(name_for_initials),
            "plan_label": PLAN_LABELS.get(user.plan, user.plan.capitalize()),
            "active": "account",
        },
    )


# ---------------------------------------------------------------------------
# GDPR
# ---------------------------------------------------------------------------

@router.get("/account/export", include_in_schema=False)
async def gdpr_export(
    request: Request, session: SessionDep, user: CurrentVerifiedUser
) -> JSONResponse:
    subs = (
        await session.execute(select(Subscription).where(Subscription.user_id == user.id))
    ).scalars().all()
    alerts = (
        await session.execute(select(DeliveredAlert).where(DeliveredAlert.user_id == user.id))
    ).scalars().all()
    audit_rows = (
        await session.execute(select(AuditLog).where(AuditLog.user_id == user.id))
    ).scalars().all()

    payload = {
        "user": {
            "email": user.email,
            "full_name": user.full_name,
            "company_name": user.company_name,
            "plan": user.plan,
            "created_at": user.created_at.isoformat(),
            "is_verified": user.is_verified,
            "totp_enabled": user.totp_enabled_at is not None,
        },
        "subscriptions": [
            {
                "name": s.name,
                "signal_types": list(s.signal_types),
                "criteria": s.criteria,
                "active": s.active,
                "created_at": s.created_at.isoformat(),
            }
            for s in subs
        ],
        "delivered_alerts": [
            {
                "signal_type": a.signal_type,
                "signal_id": a.signal_id,
                "delivered_at": a.delivered_at.isoformat(),
                "opened_at": a.opened_at.isoformat() if a.opened_at else None,
            }
            for a in alerts
        ],
        "audit_log": [
            {
                "action": a.action,
                "ip": a.ip,
                "created_at": a.created_at.isoformat(),
                "metadata": a.audit_metadata,
            }
            for a in audit_rows
        ],
    }

    meta = request_meta(request)
    await audit(
        session,
        action=AuditAction.GDPR_EXPORT,
        user_id=user.id,
        ip=meta["ip"],
        user_agent=meta["user_agent"],
    )

    return JSONResponse(
        json.loads(json.dumps(payload, ensure_ascii=False)),
        headers={
            "Content-Disposition": f'attachment; filename="vittring-export-{user.id}.json"'
        },
    )


@router.post("/account/delete", include_in_schema=False)
async def gdpr_delete_request(
    request: Request, session: SessionDep, user: CurrentVerifiedUser
) -> RedirectResponse:
    user.deletion_requested_at = datetime.now(timezone.utc)
    user.is_active = False
    meta = request_meta(request)
    await audit(
        session,
        action=AuditAction.GDPR_DELETE_REQUESTED,
        user_id=user.id,
        ip=meta["ip"],
        user_agent=meta["user_agent"],
    )
    response = RedirectResponse("/", status_code=status.HTTP_303_SEE_OTHER)
    response.delete_cookie("vittring_session")
    return response
