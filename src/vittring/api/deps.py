"""Shared FastAPI dependencies — current user, request context."""

from __future__ import annotations

from typing import Annotated
from urllib.parse import quote

from fastapi import Cookie, Depends, HTTPException, Request, status
from sqlalchemy import select

from vittring.db import SessionDep
from vittring.models.user import User
from vittring.security.tokens import decode_access_token

ACCESS_TOKEN_COOKIE = "vittring_session"


def _safe_next(path: str) -> str:
    """Sanitise a candidate ``?next=`` path so it can't open-redirect.

    Only same-origin absolute paths (starting with a single ``/``) are
    accepted — protocol-relative ``//evil.example.com`` and full URLs
    are rejected and fall back to the default landing.
    """
    if not path or not path.startswith("/") or path.startswith("//"):
        return "/app"
    return path


async def current_user_or_none(
    session: SessionDep,
    token: Annotated[str | None, Cookie(alias=ACCESS_TOKEN_COOKIE)] = None,
) -> User | None:
    if not token:
        return None
    try:
        payload = decode_access_token(token)
    except Exception:
        return None
    user_id = payload.get("sub")
    if not user_id:
        return None
    result = await session.execute(select(User).where(User.id == int(user_id)))
    return result.scalar_one_or_none()


async def current_user(
    request: Request,
    user: Annotated[User | None, Depends(current_user_or_none)],
) -> User:
    """Require an authenticated, active user.

    Anonymous or inactive callers used to get a hard 401 with a JSON body
    (``{"detail":"not_authenticated"}``), which dead-ended every page in
    the logged-in shell once the 15-min session cookie expired. Bounce
    them to ``/auth/login`` instead, preserving the original path in
    ``?next=`` so they land back where they were after re-auth.
    """
    if user is None or not user.is_active:
        path = request.url.path or "/"
        if request.url.query:
            path = f"{path}?{request.url.query}"
        next_param = quote(path, safe="/?&=")
        raise HTTPException(
            status_code=status.HTTP_303_SEE_OTHER,
            detail="not_authenticated",
            headers={"Location": f"/auth/login?next={next_param}"},
        )
    return user


async def current_verified_user(
    user: Annotated[User, Depends(current_user)],
) -> User:
    """Require a verified email; otherwise bounce to the friendly page.

    Raising HTTPException(303) with a Location header is honoured by the
    HTTP exception handler in ``main.py``, which forwards 3xx exceptions
    as real redirects rather than serialising them as JSON.
    """
    if not user.is_verified:
        raise HTTPException(
            status_code=status.HTTP_303_SEE_OTHER,
            detail="email_not_verified",
            headers={"Location": f"/auth/verification-needed?email={user.email}"},
        )
    return user


async def current_superuser(
    user: Annotated[User, Depends(current_user)],
) -> User:
    """Allow only platform owners (``is_superuser=True``).

    Depends on ``current_user`` (not ``current_verified_user``) on purpose: a
    superuser whose own ``is_verified`` flag is somehow off must still be able
    to operate the admin panel — they're the one who can fix it.
    """
    if not user.is_superuser:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="admin_required"
        )
    return user


def request_meta(request: Request) -> dict[str, str | None]:
    forwarded = request.headers.get("x-forwarded-for")
    ip = (
        forwarded.split(",", 1)[0].strip()
        if forwarded
        else (request.client.host if request.client else None)
    )
    return {
        "ip": ip,
        "user_agent": request.headers.get("user-agent"),
    }


CurrentUser = Annotated[User, Depends(current_user)]
CurrentVerifiedUser = Annotated[User, Depends(current_verified_user)]
CurrentSuperuser = Annotated[User, Depends(current_superuser)]
OptionalUser = Annotated[User | None, Depends(current_user_or_none)]
