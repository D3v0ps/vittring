"""Stripe billing — endpoints exist but the integration is gated on
``settings.billing_enabled``. While billing is deferred all signups land on
the trial plan and these endpoints return 503 with a clear message.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import JSONResponse

from vittring.api.deps import CurrentVerifiedUser
from vittring.config import get_settings
from vittring.db import SessionDep
from vittring.models.audit import StripeWebhookEvent

router = APIRouter(prefix="/billing", tags=["billing"])


def _ensure_enabled() -> None:
    if not get_settings().billing_enabled:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="billing_not_enabled",
        )


@router.post("/checkout", include_in_schema=False)
async def start_checkout(user: CurrentVerifiedUser, plan: str) -> JSONResponse:
    _ensure_enabled()
    # Implementation lands when Stripe is enabled — see CLAUDE.md §7.
    raise HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail="stripe_checkout_not_yet_implemented",
    )


@router.post("/portal", include_in_schema=False)
async def customer_portal(user: CurrentVerifiedUser) -> JSONResponse:
    _ensure_enabled()
    raise HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail="stripe_portal_not_yet_implemented",
    )


@router.post("/webhook", include_in_schema=False)
async def stripe_webhook(
    request: Request, session: SessionDep
) -> dict[str, str]:
    """Stripe webhook receiver.

    Persists every event to ``stripe_webhook_events`` keyed by Stripe event
    id (idempotent). When billing is enabled the worker dispatches by
    ``event_type`` to the appropriate handler. Until then we just record.
    """
    settings = get_settings()
    body = await request.body()
    signature = request.headers.get("stripe-signature", "")

    if not settings.billing_enabled:
        # Still ack so Stripe (or test calls) don't retry forever.
        return {"status": "billing_not_enabled"}

    # Belt-and-suspenders. billing_enabled already checks the secret is set,
    # but a future refactor could decouple them — fail closed rather than
    # crash if the secret is missing at this point.
    if settings.stripe_webhook_secret is None:
        raise HTTPException(status_code=503, detail="webhook_secret_not_configured")

    import stripe

    try:
        event = stripe.Webhook.construct_event(
            payload=body,
            sig_header=signature,
            secret=settings.stripe_webhook_secret.get_secret_value(),
        )
    except (ValueError, stripe.SignatureVerificationError) as exc:
        raise HTTPException(status_code=400, detail=f"invalid_signature: {exc}") from exc

    # Idempotency: Stripe retries the same event id; a unique-violation on
    # replay is expected, not exceptional. Use INSERT ... ON CONFLICT
    # DO NOTHING so the second delivery acks cleanly.
    from sqlalchemy.dialects.postgresql import insert as pg_insert

    stmt = pg_insert(StripeWebhookEvent).values(
        id=event["id"],
        event_type=event["type"],
        payload=dict(event),
    ).on_conflict_do_nothing(index_elements=["id"])
    await session.execute(stmt)
    return {"status": "received"}
