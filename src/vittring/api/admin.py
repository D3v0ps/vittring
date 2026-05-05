"""Superadmin panel.

End-to-end admin surface at ``/admin/*`` for the platform owner. Every
endpoint requires ``CurrentSuperuser`` and writes an audit-log row for
sensitive mutations. The visual language matches ``app/dashboard.html.j2``
exactly — same dark surfaces, same fonts — except the active accent is
amber instead of signal-green so the operator can tell at a glance they
are in the admin area.
"""

from __future__ import annotations

import asyncio
import platform
from datetime import datetime, timedelta, timezone
from typing import Annotated, Any
from urllib.parse import urlencode

import structlog
from fastapi import APIRouter, Form, HTTPException, Query, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import EmailStr
from sqlalchemy import delete, distinct, func, or_, select

from vittring import __version__ as app_version
from vittring.api.deps import CurrentSuperuser, request_meta
from vittring.api.templates import templates
from vittring.audit.log import AuditAction, audit
from vittring.db import SessionDep
from vittring.delivery.domain_setup import (
    DomainStatus,
    ensure_domain_verified,
)
from vittring.ingest.base import run_ingest
from vittring.ingest.bolagsverket import BolagsverketAdapter
from vittring.ingest.jobtech import JobTechAdapter
from vittring.ingest.ted import TedAdapter
from vittring.jobs.digest import run_daily_digest
from vittring.jobs.gdpr import purge_deleted_users, scrub_personal_data
from vittring.models.audit import AuditLog
from vittring.models.company import Company
from vittring.models.signals import CompanyChange, JobPosting, Procurement
from vittring.models.subscription import DeliveredAlert, Subscription
from vittring.models.user import User
from vittring.security.passwords import (
    assert_strong_password,
    hash_password,
)
from vittring.utils.errors import DomainNotVerifiedError, WeakPasswordError

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/admin", tags=["admin"])

USERS_PAGE_SIZE = 50
SUBSCRIPTIONS_PAGE_SIZE = 50
SIGNALS_PAGE_SIZE = 50
AUDIT_PAGE_SIZE = 100
EMAIL_RECENT_LIMIT = 50

ALLOWED_PLANS = {"trial", "solo", "team", "pro"}
ALLOWED_SIGNAL_TYPES = {"job", "company_change", "procurement"}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _initials(value: str) -> str:
    parts = [p for p in value.replace(".", " ").split() if p]
    if len(parts) >= 2:
        return (parts[0][0] + parts[1][0]).upper()
    if parts:
        return parts[0][:2].upper()
    return "AD"


def _checkbox(value: str | None) -> bool:
    return value not in (None, "", "0", "false", "off")


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    cleaned = value.strip()
    if not cleaned:
        return None
    # Accept "YYYY-MM-DDTHH:MM" or "YYYY-MM-DDTHH:MM:SS"
    try:
        if "T" in cleaned and len(cleaned) <= 16:
            cleaned = cleaned + ":00"
        if cleaned.endswith("Z"):
            cleaned = cleaned[:-1] + "+00:00"
        if "+" not in cleaned and "-" not in cleaned[10:]:
            # naive — assume UTC
            dt = datetime.fromisoformat(cleaned)
            return dt.replace(tzinfo=timezone.utc)
        return datetime.fromisoformat(cleaned)
    except ValueError:
        return None


async def _user_email_map(
    session: SessionDep, ids: list[int]
) -> dict[int, str]:
    if not ids:
        return {}
    rows = await session.execute(
        select(User.id, User.email).where(User.id.in_(set(ids)))
    )
    return {row[0]: row[1] for row in rows.all()}


def _common_context(user: User) -> dict[str, Any]:
    """Shared template variables: admin's identity for the sidebar."""
    return {
        "user": user,
        "admin_initials": _initials(user.full_name or user.email),
    }


def _page_url(base: str, **params: Any) -> str:
    clean = {k: v for k, v in params.items() if v not in (None, "", "all")}
    return base if not clean else f"{base}?{urlencode(clean)}"


# ---------------------------------------------------------------------------
# /admin — Overview
# ---------------------------------------------------------------------------

@router.get("", response_class=HTMLResponse, include_in_schema=False)
async def overview(
    request: Request, session: SessionDep, user: CurrentSuperuser
) -> HTMLResponse:
    now = datetime.now(timezone.utc)
    week_ago = now - timedelta(days=7)
    month_ago = now - timedelta(days=30)
    day_ago = now - timedelta(hours=24)

    users_total = (
        await session.execute(select(func.count()).select_from(User))
    ).scalar_one()
    users_active = (
        await session.execute(
            select(func.count()).select_from(User).where(User.is_active.is_(True))
        )
    ).scalar_one()
    users_verified = (
        await session.execute(
            select(func.count()).select_from(User).where(User.is_verified.is_(True))
        )
    ).scalar_one()
    subscriptions_active = (
        await session.execute(
            select(func.count())
            .select_from(Subscription)
            .where(Subscription.active.is_(True))
        )
    ).scalar_one()
    subscriptions_total = (
        await session.execute(select(func.count()).select_from(Subscription))
    ).scalar_one()

    plan_rows = (
        await session.execute(
            select(User.plan, func.count(User.id)).group_by(User.plan)
        )
    ).all()
    plans = {p: c for (p, c) in plan_rows}

    signups_7d = (
        await session.execute(
            select(func.count())
            .select_from(User)
            .where(User.created_at >= week_ago)
        )
    ).scalar_one()
    signups_30d = (
        await session.execute(
            select(func.count())
            .select_from(User)
            .where(User.created_at >= month_ago)
        )
    ).scalar_one()
    digest_users_7d = (
        await session.execute(
            select(func.count(distinct(DeliveredAlert.user_id))).where(
                DeliveredAlert.delivered_at >= week_ago
            )
        )
    ).scalar_one()
    failed_logins_24h = (
        await session.execute(
            select(func.count())
            .select_from(AuditLog)
            .where(
                AuditLog.action == AuditAction.LOGIN_FAILED.value,
                AuditLog.created_at >= day_ago,
            )
        )
    ).scalar_one()

    recent_users = (
        await session.execute(
            select(User).order_by(User.created_at.desc()).limit(10)
        )
    ).scalars().all()

    audit_rows = (
        await session.execute(
            select(AuditLog).order_by(AuditLog.created_at.desc()).limit(15)
        )
    ).scalars().all()
    email_map = await _user_email_map(
        session, [a.user_id for a in audit_rows if a.user_id]
    )
    recent_audit = [
        {
            "created_at": a.created_at,
            "action": a.action,
            "user_id": a.user_id,
            "user_email": email_map.get(a.user_id) if a.user_id else None,
        }
        for a in audit_rows
    ]

    verified_pct = (
        round(users_verified * 100 / users_total) if users_total else 0
    )

    context = {
        **_common_context(user),
        "title": "Översikt",
        "stats": {
            "users_total": users_total,
            "users_active": users_active,
            "users_verified": users_verified,
            "users_verified_pct": verified_pct,
            "subscriptions_active": subscriptions_active,
            "subscriptions_total": subscriptions_total,
            "plan_trial": plans.get("trial", 0),
            "plan_solo": plans.get("solo", 0),
            "plan_team": plans.get("team", 0),
            "plan_pro": plans.get("pro", 0),
            "signups_7d": signups_7d,
            "signups_30d": signups_30d,
            "digest_users_7d": digest_users_7d,
            "failed_logins_24h": failed_logins_24h,
        },
        "recent_users": recent_users,
        "recent_audit": recent_audit,
    }
    return templates.TemplateResponse(request, "admin/overview.html.j2", context)


# ---------------------------------------------------------------------------
# /admin/users — list
# ---------------------------------------------------------------------------

@router.get("/users", response_class=HTMLResponse, include_in_schema=False)
async def users_list(
    request: Request,
    session: SessionDep,
    user: CurrentSuperuser,
    q: Annotated[str | None, Query()] = None,
    plan: Annotated[str, Query()] = "all",
    offset: Annotated[int, Query(ge=0)] = 0,
) -> HTMLResponse:
    stmt = select(User)
    if q:
        stmt = stmt.where(func.lower(User.email).contains(q.lower()))
    if plan and plan != "all" and plan in ALLOWED_PLANS:
        stmt = stmt.where(User.plan == plan)
    stmt = stmt.order_by(User.created_at.desc()).offset(offset).limit(USERS_PAGE_SIZE)

    rows = (await session.execute(stmt)).scalars().all()

    sub_counts = {}
    if rows:
        ids = [u.id for u in rows]
        cnt = await session.execute(
            select(Subscription.user_id, func.count(Subscription.id))
            .where(Subscription.user_id.in_(ids))
            .group_by(Subscription.user_id)
        )
        sub_counts = {row[0]: row[1] for row in cnt.all()}

    users_view = []
    for u in rows:
        users_view.append(
            {
                "id": u.id,
                "email": u.email,
                "full_name": u.full_name,
                "plan": u.plan,
                "is_verified": u.is_verified,
                "is_active": u.is_active,
                "is_superuser": u.is_superuser,
                "locked_until": u.locked_until,
                "deletion_requested_at": u.deletion_requested_at,
                "created_at": u.created_at,
                "last_login_at": u.last_login_at,
                "signal_count": sub_counts.get(u.id, 0),
            }
        )

    page_num = (offset // USERS_PAGE_SIZE) + 1
    base = "/admin/users"
    next_url = (
        _page_url(base, q=q, plan=plan, offset=offset + USERS_PAGE_SIZE)
        if len(rows) == USERS_PAGE_SIZE
        else None
    )
    prev_url = (
        _page_url(base, q=q, plan=plan, offset=max(0, offset - USERS_PAGE_SIZE))
        if offset > 0
        else None
    )

    total_label = f"~{len(rows) + offset}+" if len(rows) == USERS_PAGE_SIZE else str(len(rows) + offset)

    context = {
        **_common_context(user),
        "title": "Användare",
        "users": users_view,
        "q": q,
        "plan": plan,
        "page_num": page_num,
        "page_size": USERS_PAGE_SIZE,
        "next_url": next_url,
        "prev_url": prev_url,
        "total_label": total_label,
    }
    return templates.TemplateResponse(request, "admin/users.html.j2", context)


# ---------------------------------------------------------------------------
# /admin/users/new — create
# ---------------------------------------------------------------------------

@router.get("/users/new", response_class=HTMLResponse, include_in_schema=False)
async def users_new_page(
    request: Request, user: CurrentSuperuser
) -> HTMLResponse:
    context = {
        **_common_context(user),
        "title": "Skapa användare",
        "error": None,
        "form": {},
    }
    return templates.TemplateResponse(request, "admin/user_new.html.j2", context)


@router.post("/users/new", include_in_schema=False, response_model=None)
async def users_new(
    request: Request,
    session: SessionDep,
    user: CurrentSuperuser,
    email: Annotated[EmailStr, Form()],
    password: Annotated[str, Form()],
    plan: Annotated[str, Form()] = "trial",
    full_name: Annotated[str, Form()] = "",
    company_name: Annotated[str, Form()] = "",
    is_verified: Annotated[str | None, Form()] = None,
    is_superuser: Annotated[str | None, Form()] = None,
) -> HTMLResponse | RedirectResponse:
    form = {
        "email": str(email),
        "full_name": full_name,
        "company_name": company_name,
        "plan": plan,
        "is_verified": _checkbox(is_verified),
        "is_superuser": _checkbox(is_superuser),
    }

    if plan not in ALLOWED_PLANS:
        return templates.TemplateResponse(
            request,
            "admin/user_new.html.j2",
            {
                **_common_context(user),
                "title": "Skapa användare",
                "error": "Ogiltig plan.",
                "form": form,
            },
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    try:
        assert_strong_password(password)
    except WeakPasswordError as exc:
        return templates.TemplateResponse(
            request,
            "admin/user_new.html.j2",
            {
                **_common_context(user),
                "title": "Skapa användare",
                "error": str(exc),
                "form": form,
            },
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    existing = (
        await session.execute(select(User).where(User.email == str(email)))
    ).scalar_one_or_none()
    if existing is not None:
        return templates.TemplateResponse(
            request,
            "admin/user_new.html.j2",
            {
                **_common_context(user),
                "title": "Skapa användare",
                "error": "En användare med den e-postadressen finns redan.",
                "form": form,
            },
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    new_user = User(
        email=str(email),
        password_hash=hash_password(password),
        full_name=full_name or None,
        company_name=company_name or None,
        plan=plan,
        is_verified=_checkbox(is_verified),
        is_superuser=_checkbox(is_superuser),
        trial_ends_at=datetime.now(timezone.utc) + timedelta(days=14)
        if plan == "trial"
        else None,
    )
    session.add(new_user)
    await session.flush()

    meta = request_meta(request)
    await audit(
        session,
        action=AuditAction.ADMIN_USER_CREATE,
        user_id=new_user.id,
        ip=meta["ip"],
        user_agent=meta["user_agent"],
        metadata={
            "by_admin_id": user.id,
            "by_admin_email": user.email,
            "plan": plan,
            "is_verified": form["is_verified"],
            "is_superuser": form["is_superuser"],
        },
    )

    return RedirectResponse(
        f"/admin/users/{new_user.id}", status_code=status.HTTP_303_SEE_OTHER
    )


# ---------------------------------------------------------------------------
# /admin/users/{id} — detail
# ---------------------------------------------------------------------------

async def _load_user_or_404(session: SessionDep, user_id: int) -> User:
    target = (
        await session.execute(select(User).where(User.id == user_id))
    ).scalar_one_or_none()
    if target is None:
        raise HTTPException(status_code=404, detail="user_not_found")
    return target


@router.get(
    "/users/{user_id}", response_class=HTMLResponse, include_in_schema=False
)
async def user_detail(
    user_id: int,
    request: Request,
    session: SessionDep,
    user: CurrentSuperuser,
    flash: Annotated[str | None, Query()] = None,
    flash_kind: Annotated[str, Query()] = "ok",
) -> HTMLResponse:
    target = await _load_user_or_404(session, user_id)

    subs = (
        await session.execute(
            select(Subscription)
            .where(Subscription.user_id == target.id)
            .order_by(Subscription.created_at.desc())
        )
    ).scalars().all()

    audit_rows = (
        await session.execute(
            select(AuditLog)
            .where(AuditLog.user_id == target.id)
            .order_by(AuditLog.created_at.desc())
            .limit(25)
        )
    ).scalars().all()

    delivered = (
        await session.execute(
            select(DeliveredAlert)
            .where(DeliveredAlert.user_id == target.id)
            .order_by(DeliveredAlert.delivered_at.desc())
            .limit(25)
        )
    ).scalars().all()

    context = {
        **_common_context(user),
        "title": target.email,
        "subject": target,
        "subscriptions": subs,
        "audit_rows": audit_rows,
        "delivered": delivered,
        "flash": flash,
        "flash_kind": flash_kind,
    }
    return templates.TemplateResponse(
        request, "admin/user_detail.html.j2", context
    )


# ---------------------------------------------------------------------------
# /admin/users/{id}/edit
# ---------------------------------------------------------------------------

@router.post("/users/{user_id}/edit", include_in_schema=False)
async def user_edit(
    user_id: int,
    request: Request,
    session: SessionDep,
    user: CurrentSuperuser,
    plan: Annotated[str, Form()],
    trial_ends_at: Annotated[str, Form()] = "",
    locked_until: Annotated[str, Form()] = "",
    is_active: Annotated[str | None, Form()] = None,
    is_verified: Annotated[str | None, Form()] = None,
    is_superuser: Annotated[str | None, Form()] = None,
) -> RedirectResponse:
    target = await _load_user_or_404(session, user_id)

    if plan not in ALLOWED_PLANS:
        flash = urlencode({"flash": "Ogiltig plan.", "flash_kind": "error"})
        return RedirectResponse(
            f"/admin/users/{user_id}?{flash}",
            status_code=status.HTTP_303_SEE_OTHER,
        )

    changes: dict[str, Any] = {}

    if target.plan != plan:
        changes["plan"] = {"from": target.plan, "to": plan}
        target.plan = plan

    parsed_trial = _parse_dt(trial_ends_at)
    if (target.trial_ends_at != parsed_trial) and not (
        target.trial_ends_at is None and parsed_trial is None
    ):
        changes["trial_ends_at"] = {
            "from": target.trial_ends_at.isoformat() if target.trial_ends_at else None,
            "to": parsed_trial.isoformat() if parsed_trial else None,
        }
        target.trial_ends_at = parsed_trial

    parsed_lock = _parse_dt(locked_until)
    if target.locked_until != parsed_lock and not (
        target.locked_until is None and parsed_lock is None
    ):
        changes["locked_until"] = {
            "from": target.locked_until.isoformat() if target.locked_until else None,
            "to": parsed_lock.isoformat() if parsed_lock else None,
        }
        target.locked_until = parsed_lock
        if parsed_lock is None:
            target.failed_login_count = 0

    new_active = _checkbox(is_active)
    if target.is_active != new_active:
        changes["is_active"] = {"from": target.is_active, "to": new_active}
        target.is_active = new_active

    new_verified = _checkbox(is_verified)
    if target.is_verified != new_verified:
        changes["is_verified"] = {"from": target.is_verified, "to": new_verified}
        target.is_verified = new_verified

    new_super = _checkbox(is_superuser)
    if target.is_superuser != new_super:
        changes["is_superuser"] = {"from": target.is_superuser, "to": new_super}
        target.is_superuser = new_super

    meta = request_meta(request)
    await audit(
        session,
        action=AuditAction.ADMIN_USER_EDIT,
        user_id=target.id,
        ip=meta["ip"],
        user_agent=meta["user_agent"],
        metadata={
            "by_admin_id": user.id,
            "by_admin_email": user.email,
            "changes": changes,
        },
    )

    if "plan" in changes:
        await audit(
            session,
            action=AuditAction.ADMIN_PLAN_CHANGE,
            user_id=target.id,
            ip=meta["ip"],
            user_agent=meta["user_agent"],
            metadata={
                "by_admin_id": user.id,
                "from": changes["plan"]["from"],
                "to": changes["plan"]["to"],
            },
        )

    flash = urlencode({"flash": "Användare uppdaterad.", "flash_kind": "ok"})
    return RedirectResponse(
        f"/admin/users/{user_id}?{flash}",
        status_code=status.HTTP_303_SEE_OTHER,
    )


# ---------------------------------------------------------------------------
# Quick-action POST handlers
# ---------------------------------------------------------------------------

def _flash_redirect(user_id: int, message: str, kind: str = "ok") -> RedirectResponse:
    flash = urlencode({"flash": message, "flash_kind": kind})
    return RedirectResponse(
        f"/admin/users/{user_id}?{flash}",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.post("/users/{user_id}/promote", include_in_schema=False)
async def user_promote(
    user_id: int,
    request: Request,
    session: SessionDep,
    user: CurrentSuperuser,
) -> RedirectResponse:
    target = await _load_user_or_404(session, user_id)
    target.plan = "pro"
    target.is_verified = True
    meta = request_meta(request)
    await audit(
        session,
        action=AuditAction.ADMIN_USER_PROMOTE,
        user_id=target.id,
        ip=meta["ip"],
        user_agent=meta["user_agent"],
        metadata={"by_admin_id": user.id, "by_admin_email": user.email},
    )
    return _flash_redirect(user_id, "Användaren satt till Pro och verifierad.")


@router.post("/users/{user_id}/unlock", include_in_schema=False)
async def user_unlock(
    user_id: int,
    request: Request,
    session: SessionDep,
    user: CurrentSuperuser,
) -> RedirectResponse:
    target = await _load_user_or_404(session, user_id)
    target.failed_login_count = 0
    target.locked_until = None
    meta = request_meta(request)
    await audit(
        session,
        action=AuditAction.ADMIN_USER_UNLOCK,
        user_id=target.id,
        ip=meta["ip"],
        user_agent=meta["user_agent"],
        metadata={"by_admin_id": user.id},
    )
    return _flash_redirect(user_id, "Kontot upplåst.")


@router.post("/users/{user_id}/resend-verify", include_in_schema=False)
async def user_resend_verify(
    user_id: int,
    request: Request,
    session: SessionDep,
    user: CurrentSuperuser,
) -> RedirectResponse:
    target = await _load_user_or_404(session, user_id)
    meta = request_meta(request)
    await audit(
        session,
        action=AuditAction.ADMIN_USER_VERIFICATION_RESEND,
        user_id=target.id,
        ip=meta["ip"],
        user_agent=meta["user_agent"],
        metadata={"by_admin_id": user.id, "note": "no email sent (placeholder)"},
    )
    return _flash_redirect(
        user_id,
        "Loggat — verifieringslänk skickas inte automatiskt än.",
        "warn",
    )


@router.post("/users/{user_id}/schedule-delete", include_in_schema=False)
async def user_schedule_delete(
    user_id: int,
    request: Request,
    session: SessionDep,
    user: CurrentSuperuser,
) -> RedirectResponse:
    target = await _load_user_or_404(session, user_id)
    target.deletion_requested_at = datetime.now(timezone.utc)
    target.is_active = False
    meta = request_meta(request)
    await audit(
        session,
        action=AuditAction.ADMIN_USER_DELETE_REQUEST,
        user_id=target.id,
        ip=meta["ip"],
        user_agent=meta["user_agent"],
        metadata={"by_admin_id": user.id},
    )
    return _flash_redirect(user_id, "Radering schemalagd om 30 dagar.")


@router.post("/users/{user_id}/cancel-delete", include_in_schema=False)
async def user_cancel_delete(
    user_id: int,
    request: Request,
    session: SessionDep,
    user: CurrentSuperuser,
) -> RedirectResponse:
    target = await _load_user_or_404(session, user_id)
    target.deletion_requested_at = None
    target.is_active = True
    meta = request_meta(request)
    await audit(
        session,
        action=AuditAction.ADMIN_USER_DELETE_CANCEL,
        user_id=target.id,
        ip=meta["ip"],
        user_agent=meta["user_agent"],
        metadata={"by_admin_id": user.id},
    )
    return _flash_redirect(user_id, "Schemalagd radering avbruten.")


@router.post("/users/{user_id}/hard-delete", include_in_schema=False)
async def user_hard_delete(
    user_id: int,
    request: Request,
    session: SessionDep,
    user: CurrentSuperuser,
) -> RedirectResponse:
    target = await _load_user_or_404(session, user_id)
    if target.id == user.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="cannot_delete_self",
        )
    deleted_email = target.email
    meta = request_meta(request)
    await audit(
        session,
        action=AuditAction.ADMIN_USER_DELETE,
        user_id=None,  # FK SET NULL once row is gone
        ip=meta["ip"],
        user_agent=meta["user_agent"],
        metadata={
            "by_admin_id": user.id,
            "by_admin_email": user.email,
            "deleted_user_id": target.id,
            "deleted_email": deleted_email,
        },
    )
    await session.delete(target)
    await session.flush()

    flash = urlencode(
        {"flash": f"Användare {deleted_email} hård-raderad.", "flash_kind": "warn"}
    )
    return RedirectResponse(
        f"/admin/users?{flash}", status_code=status.HTTP_303_SEE_OTHER
    )


# ---------------------------------------------------------------------------
# /admin/subscriptions
# ---------------------------------------------------------------------------

@router.get(
    "/subscriptions", response_class=HTMLResponse, include_in_schema=False
)
async def subscriptions_list(
    request: Request,
    session: SessionDep,
    user: CurrentSuperuser,
    signal_type: Annotated[str, Query()] = "all",
    offset: Annotated[int, Query(ge=0)] = 0,
) -> HTMLResponse:
    stmt = select(Subscription, User.email).join(User, Subscription.user_id == User.id)
    if signal_type and signal_type in ALLOWED_SIGNAL_TYPES:
        stmt = stmt.where(Subscription.signal_types.any(signal_type))
    stmt = (
        stmt.order_by(Subscription.created_at.desc())
        .offset(offset)
        .limit(SUBSCRIPTIONS_PAGE_SIZE)
    )
    rows = (await session.execute(stmt)).all()

    items = [
        {
            "id": s.id,
            "user_id": s.user_id,
            "user_email": email,
            "name": s.name,
            "signal_types": list(s.signal_types or []),
            "criteria": s.criteria,
            "active": s.active,
            "created_at": s.created_at,
        }
        for (s, email) in rows
    ]

    page_num = (offset // SUBSCRIPTIONS_PAGE_SIZE) + 1
    base = "/admin/subscriptions"
    next_url = (
        _page_url(base, signal_type=signal_type, offset=offset + SUBSCRIPTIONS_PAGE_SIZE)
        if len(rows) == SUBSCRIPTIONS_PAGE_SIZE
        else None
    )
    prev_url = (
        _page_url(base, signal_type=signal_type, offset=max(0, offset - SUBSCRIPTIONS_PAGE_SIZE))
        if offset > 0
        else None
    )

    context = {
        **_common_context(user),
        "title": "Prenumerationer",
        "subscriptions": items,
        "signal_type": signal_type,
        "page_num": page_num,
        "next_url": next_url,
        "prev_url": prev_url,
    }
    return templates.TemplateResponse(
        request, "admin/subscriptions.html.j2", context
    )


@router.post("/subscriptions/{subscription_id}/toggle", include_in_schema=False)
async def subscription_toggle(
    subscription_id: int,
    request: Request,
    session: SessionDep,
    user: CurrentSuperuser,
    redirect_to: Annotated[str, Form()] = "/admin/subscriptions",
) -> RedirectResponse:
    sub = (
        await session.execute(
            select(Subscription).where(Subscription.id == subscription_id)
        )
    ).scalar_one_or_none()
    if sub is None:
        raise HTTPException(status_code=404, detail="subscription_not_found")
    sub.active = not sub.active
    meta = request_meta(request)
    await audit(
        session,
        action=AuditAction.ADMIN_SUBSCRIPTION_TOGGLE,
        user_id=sub.user_id,
        ip=meta["ip"],
        user_agent=meta["user_agent"],
        metadata={
            "by_admin_id": user.id,
            "subscription_id": sub.id,
            "active": sub.active,
        },
    )
    target = redirect_to or "/admin/subscriptions"
    if not target.startswith("/admin"):
        target = "/admin/subscriptions"
    return RedirectResponse(target, status_code=status.HTTP_303_SEE_OTHER)


# ---------------------------------------------------------------------------
# /admin/signals
# ---------------------------------------------------------------------------

@router.get("/signals", response_class=HTMLResponse, include_in_schema=False)
async def signals_explorer(
    request: Request,
    session: SessionDep,
    user: CurrentSuperuser,
    tab: Annotated[str, Query()] = "jobs",
    q: Annotated[str | None, Query()] = None,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> HTMLResponse:
    if tab not in {"jobs", "changes", "procurements"}:
        tab = "jobs"

    rows: list[Any] = []
    day_ago = datetime.now(timezone.utc) - timedelta(hours=24)

    counts_24h = {
        "jobs": (
            await session.execute(
                select(func.count())
                .select_from(JobPosting)
                .where(JobPosting.ingested_at >= day_ago)
            )
        ).scalar_one(),
        "changes": (
            await session.execute(
                select(func.count())
                .select_from(CompanyChange)
                .where(CompanyChange.ingested_at >= day_ago)
            )
        ).scalar_one(),
        "procurements": (
            await session.execute(
                select(func.count())
                .select_from(Procurement)
                .where(Procurement.ingested_at >= day_ago)
            )
        ).scalar_one(),
    }

    if tab == "jobs":
        stmt = select(JobPosting)
        if q:
            like = f"%{q.lower()}%"
            stmt = stmt.where(
                or_(
                    func.lower(JobPosting.headline).like(like),
                    func.lower(JobPosting.employer_name).like(like),
                    func.lower(JobPosting.workplace_municipality).like(like),
                )
            )
        stmt = stmt.order_by(JobPosting.published_at.desc()).offset(offset).limit(SIGNALS_PAGE_SIZE)
        rows = list((await session.execute(stmt)).scalars().all())
    elif tab == "changes":
        stmt = select(CompanyChange, Company).join(
            Company, CompanyChange.company_id == Company.id
        )
        if q:
            like = f"%{q.lower()}%"
            stmt = stmt.where(
                or_(
                    func.lower(Company.name).like(like),
                    func.lower(Company.orgnr).like(like),
                    func.lower(CompanyChange.change_type).like(like),
                )
            )
        stmt = stmt.order_by(CompanyChange.changed_at.desc()).offset(offset).limit(SIGNALS_PAGE_SIZE)
        results = (await session.execute(stmt)).all()
        rows = [
            type(
                "ChangeRow",
                (),
                {
                    "id": c.id,
                    "orgnr": comp.orgnr,
                    "company_name": comp.name,
                    "change_type": c.change_type,
                    "old_value": c.old_value,
                    "new_value": c.new_value,
                    "changed_at": c.changed_at,
                    "ingested_at": c.ingested_at,
                    "personal_data_purged_at": c.personal_data_purged_at,
                },
            )
            for (c, comp) in results
        ]
    else:
        stmt = select(Procurement)
        if q:
            like = f"%{q.lower()}%"
            stmt = stmt.where(
                or_(
                    func.lower(Procurement.title).like(like),
                    func.lower(Procurement.buyer_name).like(like),
                )
            )
        stmt = stmt.order_by(Procurement.ingested_at.desc()).offset(offset).limit(SIGNALS_PAGE_SIZE)
        rows = list((await session.execute(stmt)).scalars().all())

    page_num = (offset // SIGNALS_PAGE_SIZE) + 1
    base = "/admin/signals"
    next_url = (
        _page_url(base, tab=tab, q=q, offset=offset + SIGNALS_PAGE_SIZE)
        if len(rows) == SIGNALS_PAGE_SIZE
        else None
    )
    prev_url = (
        _page_url(base, tab=tab, q=q, offset=max(0, offset - SIGNALS_PAGE_SIZE))
        if offset > 0
        else None
    )

    context = {
        **_common_context(user),
        "title": "Signaler",
        "tab": tab,
        "q": q,
        "rows": rows,
        "counts_24h": counts_24h,
        "page_num": page_num,
        "next_url": next_url,
        "prev_url": prev_url,
    }
    return templates.TemplateResponse(request, "admin/signals.html.j2", context)


# ---------------------------------------------------------------------------
# /admin/audit
# ---------------------------------------------------------------------------

@router.get("/audit", response_class=HTMLResponse, include_in_schema=False)
async def audit_view(
    request: Request,
    session: SessionDep,
    user: CurrentSuperuser,
    action: Annotated[str, Query()] = "all",
    user_id: Annotated[int | None, Query()] = None,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> HTMLResponse:
    stmt = select(AuditLog)
    if action and action != "all":
        stmt = stmt.where(AuditLog.action == action)
    if user_id is not None:
        stmt = stmt.where(AuditLog.user_id == user_id)
    stmt = stmt.order_by(AuditLog.created_at.desc()).offset(offset).limit(AUDIT_PAGE_SIZE)
    rows = (await session.execute(stmt)).scalars().all()

    email_map = await _user_email_map(
        session, [r.user_id for r in rows if r.user_id]
    )
    items = [
        {
            "created_at": r.created_at,
            "action": r.action,
            "ip": r.ip,
            "user_id": r.user_id,
            "user_email": email_map.get(r.user_id) if r.user_id else None,
            "audit_metadata": r.audit_metadata,
        }
        for r in rows
    ]

    available_actions = sorted({a.value for a in AuditAction})

    page_num = (offset // AUDIT_PAGE_SIZE) + 1
    base = "/admin/audit"
    next_url = (
        _page_url(base, action=action, user_id=user_id, offset=offset + AUDIT_PAGE_SIZE)
        if len(rows) == AUDIT_PAGE_SIZE
        else None
    )
    prev_url = (
        _page_url(base, action=action, user_id=user_id, offset=max(0, offset - AUDIT_PAGE_SIZE))
        if offset > 0
        else None
    )

    context = {
        **_common_context(user),
        "title": "Audit",
        "rows": items,
        "filter_action": action,
        "filter_user_id": user_id,
        "available_actions": available_actions,
        "page_num": page_num,
        "next_url": next_url,
        "prev_url": prev_url,
    }
    return templates.TemplateResponse(request, "admin/audit.html.j2", context)


# ---------------------------------------------------------------------------
# /admin/system
# ---------------------------------------------------------------------------

JOB_DEFINITIONS = [
    {
        "name": "ingest_jobtech",
        "label": "Ingest — JobTech",
        "schedule": "06:00 dagligen",
        "audit_source": "jobtech",
    },
    {
        "name": "ingest_bolagsverket",
        "label": "Ingest — Bolagsverket",
        "schedule": "07:00 dagligen",
        "audit_source": "bolagsverket",
    },
    {
        "name": "ingest_ted",
        "label": "Ingest — TED",
        "schedule": "08:00 dagligen",
        "audit_source": "ted",
    },
    {
        "name": "daily_digest",
        "label": "Daglig digest",
        "schedule": "06:30 dagligen",
        "audit_source": None,
    },
    {
        "name": "scrub_personal_data",
        "label": "GDPR — Rensa persondata",
        "schedule": "03:00 dagligen",
        "audit_source": None,
    },
    {
        "name": "purge_deleted_users",
        "label": "GDPR — Hård-radera utgångna konton",
        "schedule": "03:15 dagligen",
        "audit_source": None,
    },
]


async def _last_admin_run(
    session: SessionDep, *, action: AuditAction, source: str | None = None
) -> datetime | None:
    stmt = select(func.max(AuditLog.created_at)).where(AuditLog.action == action.value)
    if source is not None:
        stmt = stmt.where(AuditLog.audit_metadata["source"].astext == source)
    row = (await session.execute(stmt)).scalar()
    return row


@router.get("/system", response_class=HTMLResponse, include_in_schema=False)
async def system_view(
    request: Request,
    session: SessionDep,
    user: CurrentSuperuser,
    flash: Annotated[str | None, Query()] = None,
    flash_kind: Annotated[str, Query()] = "ok",
) -> HTMLResponse:
    jobs_view: list[dict[str, Any]] = []
    for j in JOB_DEFINITIONS:
        last: datetime | None = None
        if j["name"].startswith("ingest_"):
            last = await _last_admin_run(
                session,
                action=AuditAction.ADMIN_TRIGGER_INGEST,
                source=j["audit_source"],
            )
        elif j["name"] == "daily_digest":
            last = await _last_admin_run(
                session, action=AuditAction.ADMIN_TRIGGER_DIGEST
            )
        else:
            last = await _last_admin_run(
                session, action=AuditAction.ADMIN_TRIGGER_GDPR_SCRUB
            )
        jobs_view.append(
            {
                "name": j["name"],
                "label": j["label"],
                "schedule": j["schedule"],
                "last_run": last,
            }
        )

    db_counts = {}
    for label, model in [
        ("users", User),
        ("subscriptions", Subscription),
        ("job_postings", JobPosting),
        ("company_changes", CompanyChange),
        ("procurements", Procurement),
        ("delivered_alerts", DeliveredAlert),
        ("audit_log", AuditLog),
        ("companies", Company),
    ]:
        cnt = (await session.execute(select(func.count()).select_from(model))).scalar_one()
        db_counts[label] = cnt

    # Resend domain — best-effort, never crash this page.
    resend_status = "unknown"
    resend_detail: str | None = None
    try:
        s = await ensure_domain_verified(wait=False)
        resend_status = s.value if isinstance(s, DomainStatus) else str(s)
    except DomainNotVerifiedError as exc:
        resend_status = "pending"
        resend_detail = str(exc)
    except Exception as exc:
        resend_status = "unreachable"
        resend_detail = str(exc)

    from vittring.config import get_settings

    settings = get_settings()

    context = {
        **_common_context(user),
        "title": "System",
        "jobs": jobs_view,
        "db_counts": db_counts,
        "resend": {
            "domain": settings.email_sending_domain,
            "status": resend_status,
            "detail": resend_detail,
        },
        "app_version": app_version,
        "python_version": platform.python_version(),
        "flash": flash,
        "flash_kind": flash_kind,
    }
    return templates.TemplateResponse(request, "admin/system.html.j2", context)


# ---------------------------------------------------------------------------
# /admin/system/trigger/{job_name}
# ---------------------------------------------------------------------------

INGEST_ADAPTERS = {
    "ingest_jobtech": ("jobtech", JobTechAdapter),
    "ingest_bolagsverket": ("bolagsverket", BolagsverketAdapter),
    "ingest_ted": ("ted", TedAdapter),
}


@router.post(
    "/system/trigger/{job_name}", include_in_schema=False
)
async def system_trigger(
    job_name: str,
    request: Request,
    session: SessionDep,
    user: CurrentSuperuser,
) -> RedirectResponse:
    meta = request_meta(request)
    flash_msg = ""
    flash_kind = "ok"

    if job_name in INGEST_ADAPTERS:
        source, adapter_cls = INGEST_ADAPTERS[job_name]
        try:
            since = datetime.now(timezone.utc) - timedelta(hours=26)
            result = await asyncio.wait_for(
                run_ingest(adapter_cls(), since=since), timeout=120
            )
            await audit(
                session,
                action=AuditAction.ADMIN_TRIGGER_INGEST,
                user_id=user.id,
                ip=meta["ip"],
                user_agent=meta["user_agent"],
                metadata={
                    "source": source,
                    "fetched": result.fetched,
                    "new_rows": result.new_rows,
                    "duration_seconds": round(result.duration_seconds, 2),
                },
            )
            flash_msg = (
                f"{source}: {result.fetched} hämtade, {result.new_rows} nya rader."
            )
        except Exception as exc:
            logger.exception("admin_trigger_ingest_failed", source=source)
            await audit(
                session,
                action=AuditAction.ADMIN_TRIGGER_INGEST,
                user_id=user.id,
                ip=meta["ip"],
                user_agent=meta["user_agent"],
                metadata={"source": source, "error": str(exc)},
            )
            flash_msg = f"{source} misslyckades: {exc}"
            flash_kind = "error"
    elif job_name == "daily_digest":
        try:
            await asyncio.wait_for(run_daily_digest(), timeout=300)
            await audit(
                session,
                action=AuditAction.ADMIN_TRIGGER_DIGEST,
                user_id=user.id,
                ip=meta["ip"],
                user_agent=meta["user_agent"],
                metadata={"status": "ok"},
            )
            flash_msg = "Daglig digest körd."
        except Exception as exc:
            logger.exception("admin_trigger_digest_failed")
            await audit(
                session,
                action=AuditAction.ADMIN_TRIGGER_DIGEST,
                user_id=user.id,
                ip=meta["ip"],
                user_agent=meta["user_agent"],
                metadata={"status": "error", "error": str(exc)},
            )
            flash_msg = f"Digest misslyckades: {exc}"
            flash_kind = "error"
    elif job_name == "scrub_personal_data":
        try:
            scrubbed = await asyncio.wait_for(scrub_personal_data(), timeout=120)
            await audit(
                session,
                action=AuditAction.ADMIN_TRIGGER_GDPR_SCRUB,
                user_id=user.id,
                ip=meta["ip"],
                user_agent=meta["user_agent"],
                metadata={"job": "scrub_personal_data", "scrubbed": scrubbed},
            )
            flash_msg = f"Persondata rensad: {scrubbed} rader."
        except Exception as exc:
            logger.exception("admin_trigger_scrub_failed")
            await audit(
                session,
                action=AuditAction.ADMIN_TRIGGER_GDPR_SCRUB,
                user_id=user.id,
                ip=meta["ip"],
                user_agent=meta["user_agent"],
                metadata={"job": "scrub_personal_data", "error": str(exc)},
            )
            flash_msg = f"Scrub misslyckades: {exc}"
            flash_kind = "error"
    elif job_name == "purge_deleted_users":
        try:
            purged = await asyncio.wait_for(purge_deleted_users(), timeout=120)
            await audit(
                session,
                action=AuditAction.ADMIN_TRIGGER_GDPR_SCRUB,
                user_id=user.id,
                ip=meta["ip"],
                user_agent=meta["user_agent"],
                metadata={"job": "purge_deleted_users", "purged": purged},
            )
            flash_msg = f"Hård-raderade {purged} användare."
        except Exception as exc:
            logger.exception("admin_trigger_purge_failed")
            await audit(
                session,
                action=AuditAction.ADMIN_TRIGGER_GDPR_SCRUB,
                user_id=user.id,
                ip=meta["ip"],
                user_agent=meta["user_agent"],
                metadata={"job": "purge_deleted_users", "error": str(exc)},
            )
            flash_msg = f"Purge misslyckades: {exc}"
            flash_kind = "error"
    else:
        raise HTTPException(status_code=404, detail="unknown_job")

    flash = urlencode({"flash": flash_msg, "flash_kind": flash_kind})
    return RedirectResponse(
        f"/admin/system?{flash}", status_code=status.HTTP_303_SEE_OTHER
    )


# ---------------------------------------------------------------------------
# /admin/email
# ---------------------------------------------------------------------------

@router.get("/email", response_class=HTMLResponse, include_in_schema=False)
async def email_view(
    request: Request, session: SessionDep, user: CurrentSuperuser
) -> HTMLResponse:
    week_ago = datetime.now(timezone.utc) - timedelta(days=7)

    sent_7d = (
        await session.execute(
            select(func.count())
            .select_from(DeliveredAlert)
            .where(DeliveredAlert.delivered_at >= week_ago)
        )
    ).scalar_one()
    opened_7d = (
        await session.execute(
            select(func.count())
            .select_from(DeliveredAlert)
            .where(
                DeliveredAlert.delivered_at >= week_ago,
                DeliveredAlert.opened_at.is_not(None),
            )
        )
    ).scalar_one()
    clicked_7d = (
        await session.execute(
            select(func.count())
            .select_from(DeliveredAlert)
            .where(
                DeliveredAlert.delivered_at >= week_ago,
                DeliveredAlert.clicked_at.is_not(None),
            )
        )
    ).scalar_one()
    distinct_users_7d = (
        await session.execute(
            select(func.count(distinct(DeliveredAlert.user_id))).where(
                DeliveredAlert.delivered_at >= week_ago
            )
        )
    ).scalar_one()

    open_rate = round(opened_7d * 100 / sent_7d, 1) if sent_7d else 0
    click_rate = round(clicked_7d * 100 / sent_7d, 1) if sent_7d else 0

    rows = (
        await session.execute(
            select(DeliveredAlert, User.email)
            .join(User, DeliveredAlert.user_id == User.id)
            .order_by(DeliveredAlert.delivered_at.desc())
            .limit(EMAIL_RECENT_LIMIT)
        )
    ).all()
    items = [
        {
            "delivered_at": d.delivered_at,
            "user_id": d.user_id,
            "user_email": email,
            "signal_type": d.signal_type,
            "signal_id": d.signal_id,
            "opened_at": d.opened_at,
            "clicked_at": d.clicked_at,
            "resend_message_id": d.resend_message_id,
        }
        for (d, email) in rows
    ]

    context = {
        **_common_context(user),
        "title": "E-post",
        "stats": {
            "sent_7d": sent_7d,
            "opened_7d": opened_7d,
            "clicked_7d": clicked_7d,
            "distinct_users_7d": distinct_users_7d,
            "open_rate": open_rate,
            "click_rate": click_rate,
        },
        "rows": items,
    }
    return templates.TemplateResponse(request, "admin/email.html.j2", context)
