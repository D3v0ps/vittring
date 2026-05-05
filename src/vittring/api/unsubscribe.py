"""One-click unsubscribe handler used in digest email footers.

The token is an HMAC-signed ``user_id.signature`` pair so a recipient cannot
unsubscribe other users by guessing or enumerating ids — the signature is
verified against ``app_secret_key``. Tokens never expire (legal anti-spam
requirement: unsubscribe must keep working even years after sending).
"""

from __future__ import annotations

import hashlib
import hmac

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import update

from vittring.api.templates import templates
from vittring.config import get_settings
from vittring.db import SessionDep
from vittring.models.subscription import Subscription

router = APIRouter(tags=["unsubscribe"])

_NS = b"vittring.unsubscribe.v1"


def _sign_user_id(user_id: int) -> str:
    secret = get_settings().app_secret_key.get_secret_value().encode()
    body = str(user_id).encode()
    digest = hmac.new(secret, _NS + b"." + body, hashlib.sha256).hexdigest()[:32]
    return digest


def make_unsubscribe_token(user_id: int) -> str:
    """Build the value to embed in digest emails."""
    return f"{user_id}.{_sign_user_id(user_id)}"


def _verify_token(token: str) -> int | None:
    if "." not in token:
        return None
    raw_id, sig = token.rsplit(".", 1)
    try:
        user_id = int(raw_id)
    except ValueError:
        return None
    expected = _sign_user_id(user_id)
    if not hmac.compare_digest(expected, sig):
        return None
    return user_id


@router.get("/unsubscribe", response_class=HTMLResponse, include_in_schema=False)
async def unsubscribe(request: Request, t: str, session: SessionDep) -> HTMLResponse:
    """Pause every subscription for the user identified by the signed token."""
    user_id = _verify_token(t)
    if user_id is None:
        return templates.TemplateResponse(
            request,
            "public/unsubscribe.html.j2",
            {"title": "Avregistrera", "ok": False},
        )
    await session.execute(
        update(Subscription).where(Subscription.user_id == user_id).values(active=False)
    )
    return templates.TemplateResponse(
        request, "public/unsubscribe.html.j2", {"title": "Avregistrerad", "ok": True}
    )
