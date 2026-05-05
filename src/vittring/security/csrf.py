"""CSRF protection (pure ASGI middleware).

We must read the request body to validate a hidden form-field token, but the
endpoint also needs to read the same body via FastAPI's ``Form()`` parsing.
Starlette's ``BaseHTTPMiddleware`` does not expose body-replay to downstream
handlers, so this middleware is implemented at the raw ASGI level: it reads
the body once, validates the token, then replays the cached body to the
downstream app.

Pattern: double-submit cookie + same-origin SameSite=Lax cookie. The token is
HMAC-signed by the app secret so a stolen value still has to verify.
"""

from __future__ import annotations

import hmac
import secrets
from hashlib import sha256
from typing import Any
from urllib.parse import parse_qs

from starlette.datastructures import Headers, MutableHeaders
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from vittring.config import get_settings

CSRF_COOKIE_NAME = "vittring_csrf"
CSRF_HEADER_NAME = "x-csrf-token"
CSRF_FORM_FIELD = "csrf_token"
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
EXEMPT_PATHS_PREFIXES: tuple[str, ...] = (
    "/api/webhooks/",
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


def _parse_cookie_header(header: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for chunk in header.split(";"):
        chunk = chunk.strip()
        if "=" in chunk:
            k, v = chunk.split("=", 1)
            out[k.strip()] = v.strip()
    return out


def _csrf_cookie_value(token: str, secure: bool) -> str:
    parts = [
        f"{CSRF_COOKIE_NAME}={token}",
        "Path=/",
        "SameSite=Lax",
        "Max-Age=86400",
    ]
    if secure:
        parts.append("Secure")
    return "; ".join(parts)


class CSRFMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return

        method: str = scope["method"].upper()
        path: str = scope.get("path", "")
        headers = Headers(scope=scope)
        cookies = _parse_cookie_header(headers.get("cookie", ""))

        # Pick or mint the CSRF token. If valid one exists in cookies, reuse;
        # otherwise mint a fresh one and remember to Set-Cookie on response.
        existing = cookies.get(CSRF_COOKIE_NAME)
        if existing and _valid(existing):
            token = existing
            issue_new = False
        else:
            token = issue_token()
            issue_new = True

        # Expose token to templates via request.state.csrf_token.
        state = scope.setdefault("state", {})
        state["csrf_token"] = token

        secure = scope.get("scheme") == "https"
        is_safe = method in SAFE_METHODS or any(path.startswith(p) for p in EXEMPT_PATHS_PREFIXES)

        if is_safe:
            if issue_new:
                await self._call_with_cookie(scope, receive, send, token, secure)
            else:
                await self.app(scope, receive, send)
            return

        # State-changing request: drain body, validate, replay.
        body = b""
        more_body = True
        while more_body:
            message = await receive()
            if message.get("type") == "http.request":
                body += message.get("body", b"")
                more_body = message.get("more_body", False)
            else:
                more_body = False

        submitted = headers.get(CSRF_HEADER_NAME)
        if not submitted:
            content_type = headers.get("content-type", "")
            if content_type.startswith("application/x-www-form-urlencoded"):
                try:
                    parsed = parse_qs(body.decode("utf-8"))
                    values = parsed.get(CSRF_FORM_FIELD)
                    if values:
                        submitted = values[0]
                except Exception:
                    submitted = None

        cookie_token = cookies.get(CSRF_COOKIE_NAME)
        if (
            not cookie_token
            or not submitted
            or submitted != cookie_token
            or not _valid(cookie_token)
        ):
            response = JSONResponse({"detail": "csrf_token_invalid"}, status_code=403)
            await response(scope, receive, send)
            return

        # Replay body to downstream.
        replayed = False

        async def replay_receive() -> Message:
            nonlocal replayed
            if replayed:
                return {"type": "http.disconnect"}
            replayed = True
            return {"type": "http.request", "body": body, "more_body": False}

        if issue_new:
            await self._call_with_cookie(scope, replay_receive, send, token, secure)
        else:
            await self.app(scope, replay_receive, send)

    async def _call_with_cookie(
        self,
        scope: Scope,
        receive: Receive,
        send: Send,
        token: str,
        secure: bool,
    ) -> None:
        cookie_value = _csrf_cookie_value(token, secure)

        async def wrapped_send(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                headers.append("set-cookie", cookie_value)
            await send(message)

        await self.app(scope, receive, wrapped_send)


# Backwards-compatibility alias for tests that imported the helper directly.
__all__ = ["CSRFMiddleware", "issue_token"]
