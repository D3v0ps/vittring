"""CSRF protection via double-submit cookie.

The middleware issues a signed cookie on safe-method requests. State-changing
requests must echo the same token via either the ``X-CSRF-Token`` header or a
``csrf_token`` form field. Templates render the form-field value with
``{{ csrf_input() }}``.

Why double-submit-cookie + SameSite=Lax:
- The cookie is set with ``SameSite=Lax`` so browsers refuse to send it on
  most cross-site POSTs (covering the easy CSRF vectors).
- For forms within the same origin, we explicitly require a hidden input
  whose value matches the cookie — an attacker cannot read the cookie value
  to forge a request, even if they could trigger a form POST.
- Token has an HMAC signature so a stolen cookie value can be invalidated
  without a database lookup if the secret key rotates.
"""

from __future__ import annotations

import hmac
import secrets
from hashlib import sha256

from fastapi import Request, status
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

from vittring.config import get_settings

CSRF_COOKIE_NAME = "vittring_csrf"
CSRF_HEADER_NAME = "x-csrf-token"
CSRF_FORM_FIELD = "csrf_token"
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
EXEMPT_PATHS_PREFIXES: tuple[str, ...] = (
    "/api/webhooks/",  # Stripe & Resend webhooks have their own signature
    "/billing/webhook",
    "/health",
    "/ready",
    "/static/",
)


def _sign(value: str) -> str:
    secret = get_settings().app_secret_key.get_secret_value().encode()
    return hmac.new(secret, value.encode(), sha256).hexdigest()


def issue_token() -> str:
    raw = secrets.token_urlsafe(24)
    return f"{raw}.{_sign(raw)}"


def _valid(token: str) -> bool:
    try:
        raw, sig = token.rsplit(".", 1)
    except ValueError:
        return False
    return hmac.compare_digest(_sign(raw), sig)


async def _extract_form_token(request: Request) -> str | None:
    content_type = request.headers.get("content-type", "")
    if not content_type.startswith(("application/x-www-form-urlencoded", "multipart/form-data")):
        return None
    try:
        form = await request.form()
    except Exception:
        return None
    value = form.get(CSRF_FORM_FIELD)
    return value if isinstance(value, str) else None


class CSRFMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)

    async def dispatch(self, request: Request, call_next):  # type: ignore[no-untyped-def]
        path = request.url.path
        method = request.method.upper()

        # Ensure the token is available to templates regardless of path.
        cookie_token = request.cookies.get(CSRF_COOKIE_NAME)
        if not cookie_token or not _valid(cookie_token):
            cookie_token = issue_token()
            request.state.csrf_new_cookie = cookie_token
        request.state.csrf_token = cookie_token

        if method in SAFE_METHODS or any(path.startswith(p) for p in EXEMPT_PATHS_PREFIXES):
            response = await call_next(request)
            if getattr(request.state, "csrf_new_cookie", None):
                response.set_cookie(
                    CSRF_COOKIE_NAME,
                    request.state.csrf_new_cookie,
                    httponly=False,
                    secure=request.url.scheme == "https",
                    samesite="lax",
                    max_age=60 * 60 * 24,
                    path="/",
                )
            return response

        # State-changing request: validate token. Accept either header or form field.
        submitted = request.headers.get(CSRF_HEADER_NAME) or await _extract_form_token(request)
        if (
            not request.cookies.get(CSRF_COOKIE_NAME)
            or not submitted
            or submitted != request.cookies.get(CSRF_COOKIE_NAME)
            or not _valid(submitted)
        ):
            return JSONResponse(
                {"detail": "csrf_token_invalid"},
                status_code=status.HTTP_403_FORBIDDEN,
            )
        return await call_next(request)
