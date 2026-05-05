"""Account dashboard, profile, GDPR export and deletion."""

from __future__ import annotations

import csv
import io
import json
from datetime import datetime, timezone
from typing import Annotated, Any

from fastapi import APIRouter, Form, Request, status
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from sqlalchemy import delete, select

from vittring.api.deps import CurrentVerifiedUser, request_meta
from vittring.api.templates import templates
from vittring.audit.log import AuditAction, audit
from vittring.db import SessionDep
from vittring.models.audit import AuditLog
from vittring.models.saved import SavedSignal
from vittring.models.subscription import DeliveredAlert, Subscription

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
) -> HTMLResponse:
    subs_rows = (
        await session.execute(
            select(Subscription).where(
                Subscription.user_id == user.id,
                Subscription.active.is_(True),
            ).order_by(Subscription.created_at.desc())
        )
    ).scalars().all()

    # Counts per subscription — placeholder until DeliveredAlert join is wired
    subs = [
        {"name": s.name, "signal_count": None}
        for s in subs_rows
    ]

    priority_signals, other_signals = _example_signals()
    if q:
        priority_signals = _filter_signals(priority_signals, q)
        other_signals = _filter_signals(other_signals, q)
    digest_count = len(priority_signals) + len(other_signals)

    now = datetime.now(timezone.utc)
    today_weekday = SWEDISH_WEEKDAYS[now.weekday()].capitalize()
    today_date = f"{now.day} {SWEDISH_MONTHS[now.month - 1]} {now.year}"
    week_num = now.isocalendar().week

    name_for_initials = user.full_name or user.email.split("@")[0]

    context = {
        "title": "Dashboard",
        "user": user,
        "subscriptions": subs,
        "initials": _initials(name_for_initials),
        "plan_label": PLAN_LABELS.get(user.plan, user.plan.capitalize()),

        "today_weekday": today_weekday,
        "today_date": today_date,
        "last_sync_time": "06:30",
        "next_sync_time": "06:30",

        "digest_count": digest_count,
        "digest_focus": "Lager & logistik · Storstockholm",
        "priority_count": len(priority_signals),
        "other_count": len(other_signals),
        "saved_count": 2,

        "stat_week_count": "214",
        "stat_week_delta": "+18%",
        "stat_noise_pct": "99,5%",
        "stat_noise_total": "4 982",
        "stat_week_num": week_num,
        "stat_conversions": "7",
        "stat_conversions_delta": "+2",

        "active_filters": ["Storstockholm", "SNI 53.* / 52.*"],
        "count_upph": sum(1 for s in priority_signals + other_signals if s["kind_class"] == "upph"),
        "count_jobb": sum(1 for s in priority_signals + other_signals if s["kind_class"] == "jobb"),
        "count_bolag": sum(1 for s in priority_signals + other_signals if s["kind_class"] == "bolag"),

        "priority_signals": priority_signals,
        "other_signals": other_signals,
        "search_query": q,
    }
    return templates.TemplateResponse(request, "app/dashboard.html.j2", context)


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
async def calendar_stub(request: Request, user: CurrentVerifiedUser) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        "app/_stub.html.j2",
        _stub_context(
            user,
            active="calendar",
            title="Kalender",
            description=(
                "Här samlas kommande deadlines för upphandlingar och slutdatum för "
                "provperioder, så att du aldrig missar ett anbud eller en uppföljning."
            ),
        ),
    )


@router.get("/saved", response_class=HTMLResponse, include_in_schema=False)
async def saved_stub(request: Request, user: CurrentVerifiedUser) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        "app/_stub.html.j2",
        _stub_context(
            user,
            active="saved",
            title="Sparade signaler",
            description=(
                "Signaler du stjärnmarkerat hamnar här — så att du kan återvända till "
                "uppslag som väntar på uppföljning utan att leta bland dagens digest."
            ),
        ),
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

    return Response(
        content=buf.getvalue(),
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
    request: Request, user: CurrentVerifiedUser
) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        "app/account.html.j2",
        {"title": "Inställningar", "user": user},
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
