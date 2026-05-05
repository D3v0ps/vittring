"""Account dashboard, profile, GDPR export and deletion."""

from __future__ import annotations

import json
from datetime import datetime, timezone

from fastapi import APIRouter, Request, status
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from sqlalchemy import select

from vittring.api.deps import CurrentVerifiedUser, request_meta
from vittring.api.templates import templates
from vittring.audit.log import AuditAction, audit
from vittring.db import SessionDep
from vittring.models.subscription import DeliveredAlert, Subscription
from vittring.models.audit import AuditLog

router = APIRouter(prefix="/app", tags=["account"])


@router.get("", response_class=HTMLResponse, include_in_schema=False)
async def dashboard(
    request: Request, session: SessionDep, user: CurrentVerifiedUser
) -> HTMLResponse:
    subs = (
        await session.execute(
            select(Subscription).where(
                Subscription.user_id == user.id,
                Subscription.active.is_(True),
            )
        )
    ).scalars().all()
    recent_alerts = (
        await session.execute(
            select(DeliveredAlert)
            .where(DeliveredAlert.user_id == user.id)
            .order_by(DeliveredAlert.delivered_at.desc())
            .limit(20)
        )
    ).scalars().all()
    return templates.TemplateResponse(
        request,
        "app/dashboard.html.j2",
        {
            "title": "Konto",
            "user": user,
            "subscriptions": subs,
            "recent_alerts": recent_alerts,
        },
    )


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
