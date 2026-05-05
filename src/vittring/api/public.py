"""Public-facing pages: landing, pricing, legal."""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

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
