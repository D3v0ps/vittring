"""Public-facing pages: landing, pricing, legal, demo."""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Request
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
        {"title": "VittringBot", "last_updated": "2026-05-05"},
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
