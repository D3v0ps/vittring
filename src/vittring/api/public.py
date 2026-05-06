"""Public-facing pages: landing, pricing, legal, demo."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse

from vittring.api.account import (
    SWEDISH_MONTHS,
    SWEDISH_WEEKDAYS,
    _example_signals,
)
from vittring.api.deps import OptionalUser
from vittring.api.templates import templates

router = APIRouter()


@router.get("/", response_class=HTMLResponse, include_in_schema=False)
async def landing(request: Request, user: OptionalUser) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        "public/landing.html.j2",
        {"user": user, "title": "Vittring"},
    )


@router.get("/pricing", response_class=HTMLResponse, include_in_schema=False)
async def pricing(request: Request, user: OptionalUser) -> HTMLResponse:
    return templates.TemplateResponse(
        request, "public/pricing.html.j2", {"user": user, "title": "Priser"}
    )


@router.get("/demo", response_class=HTMLResponse, include_in_schema=False)
async def demo(request: Request) -> HTMLResponse:
    """Public, no-auth dashboard preview.

    Renders a dashboard-shaped page using the same sample feed as the real
    ``/app`` view so visitors who click "Se exempel på signaler" see what the
    product looks like populated. All write actions (star, HubSpot) are
    redirected to ``/auth/signup`` instead of being wired up.
    """
    priority_signals, other_signals = _example_signals()
    digest_count = len(priority_signals) + len(other_signals)

    now = datetime.now(timezone.utc)
    today_weekday = SWEDISH_WEEKDAYS[now.weekday()].capitalize()
    today_date = f"{now.day} {SWEDISH_MONTHS[now.month - 1]} {now.year}"
    week_num = now.isocalendar().week

    sample_subscriptions = [
        {"name": "Lagerarbetare Storstockholm", "signal_count": 5},
        {"name": "Konsultchefer norra Sverige", "signal_count": 2},
        {"name": "Truckförare Skåne län", "signal_count": 7},
    ]

    context = {
        "title": "Demo — Vittring",
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
        "count_upph": sum(
            1 for s in priority_signals + other_signals if s["kind_class"] == "upph"
        ),
        "count_jobb": sum(
            1 for s in priority_signals + other_signals if s["kind_class"] == "jobb"
        ),
        "count_bolag": sum(
            1 for s in priority_signals + other_signals if s["kind_class"] == "bolag"
        ),
        "priority_signals": priority_signals,
        "other_signals": other_signals,
        "subscriptions": sample_subscriptions,
    }
    return templates.TemplateResponse(request, "public/demo.html.j2", context)


_DOMAIN_RE = re.compile(r"^(?=.{1,253}$)([a-z0-9](?:[a-z0-9\-]{0,61}[a-z0-9])?\.)+[a-z]{2,}$")


@router.get("/bot", response_class=HTMLResponse, include_in_schema=False)
async def bot(request: Request) -> HTMLResponse:
    """Public crawler-disclosure page (CLAUDE.md §24.7).

    Describes VittringBot, lists scraped sources with their domains and rate
    limits, and tells site owners how to opt out. Linked from every
    request's ``User-Agent`` header.
    """
    return templates.TemplateResponse(
        request,
        "public/bot.html.j2",
        {
            "title": "VittringBot",
            "last_updated": "2026-05-05",
            "submitted": False,
            "submitted_domain": None,
            "error": None,
        },
    )


@router.post("/bot/opt-out", response_class=HTMLResponse, include_in_schema=False)
async def bot_opt_out(
    request: Request,
    domain: Annotated[str, Form()],
    contact: Annotated[str, Form()] = "",
) -> HTMLResponse:
    """Receive a site-owner opt-out request (CLAUDE.md §24.7).

    Validates the domain shape, audit-logs the request, and renders the
    same /bot page with a success banner. Removal from the active scraper
    blocklist is a manual operator step (mailbox alert + commit to
    BLOCKED_DOMAINS) — keeping a human in the loop guards against
    griefing where a competitor opts a third-party domain out of the
    crawl. Audit log entry is the durable receipt.
    """
    from vittring.audit.log import AuditAction, audit
    from vittring.api.deps import request_meta
    from vittring.db import session_scope

    normalised = (domain or "").strip().lower().lstrip("@").removeprefix("http://").removeprefix("https://").split("/", 1)[0]
    if not _DOMAIN_RE.match(normalised):
        return templates.TemplateResponse(
            request,
            "public/bot.html.j2",
            {
                "title": "VittringBot",
                "last_updated": "2026-05-05",
                "submitted": False,
                "submitted_domain": None,
                "error": "Ogiltigt domännamn. Använd formen exempel.se (utan https://, utan sökväg).",
            },
            status_code=400,
        )

    meta = request_meta(request)
    async with session_scope() as session:
        await audit(
            session,
            action=AuditAction.SCRAPER_OPT_OUT_RECEIVED,
            user_id=None,
            ip=meta["ip"],
            user_agent=meta["user_agent"],
            metadata={"domain": normalised, "contact": contact[:254] if contact else ""},
        )

    return templates.TemplateResponse(
        request,
        "public/bot.html.j2",
        {
            "title": "VittringBot",
            "last_updated": "2026-05-05",
            "submitted": True,
            "submitted_domain": normalised,
            "error": None,
        },
    )


@router.get("/legal/privacy", response_class=HTMLResponse, include_in_schema=False)
async def privacy(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        request, "public/legal_privacy.html.j2", {"title": "Integritetspolicy"}
    )


@router.get("/legal/terms", response_class=HTMLResponse, include_in_schema=False)
async def terms(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        request, "public/legal_terms.html.j2", {"title": "Användarvillkor"}
    )


@router.get("/legal/cookies", response_class=HTMLResponse, include_in_schema=False)
async def cookies(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        request, "public/legal_cookies.html.j2", {"title": "Cookiepolicy"}
    )


@router.get("/legal/dpa", response_class=HTMLResponse, include_in_schema=False)
async def dpa(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        request, "public/legal_dpa.html.j2", {"title": "Personuppgiftsbiträdesavtal (DPA)"}
    )
