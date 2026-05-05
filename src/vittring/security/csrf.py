"""CSRF protection via the synchronizer-token pattern.

Stateless: the token is HMAC(session_id, secret) — server validates by
recomputation. Tokens are issued in a non-HttpOnly cookie so the page can
echo them in a header on form submit, and validated on every state-changing
request.
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
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
EXEMPT_PATHS_PREFIXES: tuple[str, ...] = (
    "/api/webhooks/",  # Stripe & Resend webhooks have their own signature
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


class CSRFMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)

    async def dispatch(self, request: Request, call_next):  # type: ignore[no-untyped-def]
        path = request.url.path
        method = request.method.upper()

        if method in SAFE_METHODS or any(path.startswith(p) for p in EXEMPT_PATHS_PREFIXES):
            response = await call_next(request)
            if request.cookies.get(CSRF_COOKIE_NAME) is None:
                response.set_cookie(
                    CSRF_COOKIE_NAME,
                    issue_token(),
                    httponly=False,
                    secure=True,
                    samesite="lax",
                    max_age=60 * 60 * 24,
                )
            return response

        cookie_token = request.cookies.get(CSRF_COOKIE_NAME)
        header_token = request.headers.get(CSRF_HEADER_NAME)
        if (
            not cookie_token
            or not header_token
            or cookie_token != header_token
            or not _valid(cookie_token)
        ):
            return JSONResponse(
                {"detail": "csrf_token_invalid"},
                status_code=status.HTTP_403_FORBIDDEN,
            )
        return await call_next(request)
