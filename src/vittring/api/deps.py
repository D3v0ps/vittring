"""Shared FastAPI dependencies — current user, request context."""

from __future__ import annotations

from typing import Annotated

from fastapi import Cookie, Depends, HTTPException, Request, status
from sqlalchemy import select

from vittring.db import SessionDep
from vittring.models.user import User
from vittring.security.tokens import decode_access_token

ACCESS_TOKEN_COOKIE = "vittring_session"


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
    user: Annotated[User | None, Depends(current_user_or_none)],
) -> User:
    if user is None or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="not_authenticated"
        )
    return user


async def current_verified_user(
    user: Annotated[User, Depends(current_user)],
) -> User:
    if not user.is_verified:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="email_not_verified"
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
