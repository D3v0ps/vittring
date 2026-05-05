"""Resend delivery-event webhook receiver.

Updates ``delivered_alerts.opened_at`` / ``clicked_at`` based on Resend's
``email.opened`` and ``email.clicked`` events. Bounces and complaints flag
``users.is_active`` after three hard bounces in 30 days (CLAUDE.md §11).
"""

from __future__ import annotations

import hashlib
import hmac
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Request, status
from sqlalchemy import update

from vittring.config import get_settings
from vittring.db import SessionDep
from vittring.models.subscription import DeliveredAlert

router = APIRouter(prefix="/api/webhooks", tags=["webhooks"])


def _verify_signature(body: bytes, signature: str | None) -> None:
    """Reject unsigned or wrongly-signed webhook deliveries (fail closed).

    If ``RESEND_WEBHOOK_SECRET`` is not configured the endpoint refuses every
    request — the previous behaviour silently accepted unauthenticated POSTs
    in production whenever the secret was missing, which let any attacker
    flag arbitrary deliveries as opened/clicked.
    """
    secret = get_settings().resend_webhook_secret
    if secret is None:
        raise HTTPException(
            status_code=503,
            detail="resend_webhook_secret_not_configured",
        )
    if signature is None:
        raise HTTPException(status_code=400, detail="missing_signature")
    expected = hmac.new(
        secret.get_secret_value().encode(), body, hashlib.sha256
    ).hexdigest()
    if not hmac.compare_digest(expected, signature):
        raise HTTPException(status_code=400, detail="invalid_signature")


@router.post("/resend", include_in_schema=False)
async def resend_webhook(request: Request, session: SessionDep) -> dict[str, str]:
    body = await request.body()
    _verify_signature(body, request.headers.get("svix-signature"))

    payload = await request.json()
    event_type = payload.get("type", "")
    data = payload.get("data") or {}
    message_id = data.get("email_id")

    if not message_id:
        return {"status": "ignored"}

    now = datetime.now(timezone.utc)

    if event_type == "email.opened":
        await session.execute(
            update(DeliveredAlert)
            .where(DeliveredAlert.resend_message_id == message_id)
            .values(opened_at=now)
        )
    elif event_type == "email.clicked":
        await session.execute(
            update(DeliveredAlert)
            .where(DeliveredAlert.resend_message_id == message_id)
            .values(clicked_at=now)
        )
    elif event_type in ("email.bounced", "email.complained"):
        # TODO(bounce-policy): aggregate hard bounces over 30d window and
        # flag users.is_active=false on threshold per CLAUDE.md §11.
        pass

    return {"status": "ok"}
