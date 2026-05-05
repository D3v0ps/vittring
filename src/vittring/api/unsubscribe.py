"""One-click unsubscribe handler used in digest email footers."""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import update

from vittring.api.templates import templates
from vittring.db import SessionDep
from vittring.models.subscription import Subscription

router = APIRouter(tags=["unsubscribe"])


@router.get("/unsubscribe", response_class=HTMLResponse, include_in_schema=False)
async def unsubscribe(request: Request, t: str, session: SessionDep) -> HTMLResponse:
    """Pause every subscription for the given user token.

    The current implementation uses the user id as the token for simplicity;
    upgrade to a signed token in v2 to prevent enumeration.
    """
    try:
        user_id = int(t)
    except ValueError:
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
