"""Operator CLI for one-off tasks.

Run via ``uv run python -m vittring.cli <command> [args]``.

Commands:
    verify-user EMAIL          Mark a user as is_verified=True (skip email verification).
    promote-superuser EMAIL    Mark a user as is_superuser=True.
    create-user EMAIL PASSWORD Create a verified user from the command line.
"""

from __future__ import annotations

import asyncio
import sys
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, update

from vittring.db import session_scope
from vittring.models.user import User
from vittring.security.passwords import hash_password


async def _verify_user(email: str) -> int:
    async with session_scope() as session:
        result = await session.execute(
            update(User).where(User.email == email).values(is_verified=True)
        )
        return result.rowcount or 0


async def _promote_superuser(email: str) -> int:
    async with session_scope() as session:
        result = await session.execute(
            update(User).where(User.email == email).values(is_superuser=True)
        )
        return result.rowcount or 0


async def _create_user(email: str, password: str) -> int:
    async with session_scope() as session:
        existing = (
            await session.execute(select(User).where(User.email == email))
        ).scalar_one_or_none()
        if existing is not None:
            print(f"User {email} already exists (id={existing.id}); marking as verified.")
            existing.is_verified = True
            return existing.id
        user = User(
            email=email,
            password_hash=hash_password(password),
            plan="trial",
            is_verified=True,
            trial_ends_at=datetime.now(timezone.utc) + timedelta(days=14),
        )
        session.add(user)
        await session.flush()
        return user.id


def _usage() -> None:
    print(__doc__, file=sys.stderr)
    sys.exit(2)


def main() -> None:
    if len(sys.argv) < 2:
        _usage()

    command = sys.argv[1]

    if command == "verify-user" and len(sys.argv) == 3:
        n = asyncio.run(_verify_user(sys.argv[2]))
        print(f"Updated {n} user(s).")
    elif command == "promote-superuser" and len(sys.argv) == 3:
        n = asyncio.run(_promote_superuser(sys.argv[2]))
        print(f"Updated {n} user(s).")
    elif command == "create-user" and len(sys.argv) == 4:
        uid = asyncio.run(_create_user(sys.argv[2], sys.argv[3]))
        print(f"User id={uid}.")
    else:
        _usage()


if __name__ == "__main__":
    main()
