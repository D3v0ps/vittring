"""JWT access tokens and short-lived URL tokens (verify, reset)."""

from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

import jwt

from vittring.config import get_settings

ALGORITHM = "HS256"
ACCESS_TOKEN_TTL = timedelta(minutes=15)
URL_TOKEN_BYTES = 32


def create_access_token(*, sub: str, extra: dict[str, Any] | None = None) -> str:
    settings = get_settings()
    now = datetime.now(timezone.utc)
    payload: dict[str, Any] = {
        "sub": sub,
        "iat": int(now.timestamp()),
        "exp": int((now + ACCESS_TOKEN_TTL).timestamp()),
    }
    if extra:
        payload.update(extra)
    return jwt.encode(payload, settings.app_secret_key.get_secret_value(), algorithm=ALGORITHM)


def decode_access_token(token: str) -> dict[str, Any]:
    settings = get_settings()
    return jwt.decode(  # type: ignore[no-any-return]
        token,
        settings.app_secret_key.get_secret_value(),
        algorithms=[ALGORITHM],
    )


def new_url_token() -> tuple[str, str]:
    """Return ``(plain, hashed)``. Store the hash, send the plain in URL."""
    plain = secrets.token_urlsafe(URL_TOKEN_BYTES)
    hashed = hashlib.sha256(plain.encode()).hexdigest()
    return plain, hashed


def hash_url_token(plain: str) -> str:
    return hashlib.sha256(plain.encode()).hexdigest()
