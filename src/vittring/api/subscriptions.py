"""Subscription CRUD."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select

from vittring.api.deps import CurrentVerifiedUser, request_meta
from vittring.api.templates import templates
from vittring.audit.log import AuditAction, audit
from vittring.db import SessionDep
from vittring.matching.criteria import Criteria
from vittring.models.subscription import Subscription

router = APIRouter(prefix="/app/subscriptions", tags=["subscriptions"])


PLAN_LIMITS = {
    "trial": 5,
    "solo": 5,
    "team": 20,
    "pro": None,  # unlimited
}


def _plan_limit(plan: str) -> int | None:
    return PLAN_LIMITS.get(plan, 5)


@router.get("/", response_class=HTMLResponse, include_in_schema=False)
async def list_subscriptions(
    request: Request, session: SessionDep, user: CurrentVerifiedUser
) -> HTMLResponse:
    rows = (
        await session.execute(
            select(Subscription)
            .where(Subscription.user_id == user.id)
            .order_by(Subscription.created_at.desc())
        )
    ).scalars().all()
    return templates.TemplateResponse(
        request,
        "app/subscriptions.html.j2",
        {"title": "Prenumerationer", "user": user, "subscriptions": rows},
    )


@router.get("/new", response_class=HTMLResponse, include_in_schema=False)
async def new_subscription_page(request: Request, user: CurrentVerifiedUser) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        "app/subscription_form.html.j2",
        {"title": "Ny prenumeration", "user": user, "subscription": None, "error": None},
    )


@router.post("/", include_in_schema=False, response_model=None)
async def create_subscription(
    request: Request,
    session: SessionDep,
    user: CurrentVerifiedUser,
    name: Annotated[str, Form()],
    signal_types: Annotated[list[str], Form()],
    occupations: Annotated[str, Form()] = "",
    municipalities: Annotated[str, Form()] = "",
    counties: Annotated[str, Form()] = "",
    sni_codes: Annotated[str, Form()] = "",
    keywords_any: Annotated[str, Form()] = "",
    keywords_none: Annotated[str, Form()] = "",
    cpv_codes: Annotated[str, Form()] = "",
    min_procurement_value_sek: Annotated[str, Form()] = "",
) -> HTMLResponse | RedirectResponse:
    count = (
        await session.execute(
            select(Subscription).where(Subscription.user_id == user.id)
        )
    ).all()
    limit = _plan_limit(user.plan)
    if limit is not None and len(count) >= limit:
        return templates.TemplateResponse(
            request,
            "app/subscription_form.html.j2",
            {
                "title": "Ny prenumeration",
                "user": user,
                "subscription": None,
                "error": f"Din plan tillåter max {limit} prenumerationer.",
            },
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
        )

    def _split(value: str) -> list[str]:
        return [s.strip() for s in value.split(",") if s.strip()]

    criteria = Criteria(
        occupations=_split(occupations),
        municipalities=_split(municipalities),
        counties=_split(counties),
        sni_codes=_split(sni_codes),
        keywords_any=_split(keywords_any),
        keywords_none=_split(keywords_none),
        cpv_codes=_split(cpv_codes),
        min_procurement_value_sek=int(min_procurement_value_sek)
        if min_procurement_value_sek
        else None,
    )

    sub = Subscription(
        user_id=user.id,
        name=name,
        signal_types=signal_types,
        criteria=criteria.model_dump(exclude_defaults=False),
    )
    session.add(sub)
    meta = request_meta(request)
    await audit(
        session,
        action=AuditAction.SUBSCRIPTION_CREATED,
        user_id=user.id,
        ip=meta["ip"],
        user_agent=meta["user_agent"],
        metadata={"name": name},
    )
    return RedirectResponse("/app/subscriptions", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/{subscription_id}/delete", include_in_schema=False)
async def delete_subscription(
    request: Request,
    session: SessionDep,
    user: CurrentVerifiedUser,
    subscription_id: int,
) -> RedirectResponse:
    sub = (
        await session.execute(
            select(Subscription).where(
                Subscription.id == subscription_id,
                Subscription.user_id == user.id,
            )
        )
    ).scalar_one_or_none()
    if sub is None:
        raise HTTPException(status_code=404)
    await session.delete(sub)
    meta = request_meta(request)
    await audit(
        session,
        action=AuditAction.SUBSCRIPTION_DELETED,
        user_id=user.id,
        ip=meta["ip"],
        user_agent=meta["user_agent"],
        metadata={"subscription_id": subscription_id},
    )
    return RedirectResponse("/app/subscriptions", status_code=status.HTTP_303_SEE_OTHER)
