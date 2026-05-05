"""Password hashing and strength check.

Uses the ``bcrypt`` library directly. ``passlib`` and ``bcrypt`` 4+ have a
compatibility issue that surfaces as a misleading "password cannot be longer
than 72 bytes" error even for short inputs, so we bypass passlib.

Long passphrases are pre-folded with SHA-256 + base64 so the bcrypt input is
always 44 bytes regardless of the original length — no silent truncation.
"""

from __future__ import annotations

import base64
import hashlib

import bcrypt

from vittring.utils.errors import WeakPasswordError

ROUNDS = 12
MIN_PASSWORD_LENGTH = 12


def _prepare(plain: str) -> bytes:
    digest = hashlib.sha256(plain.encode("utf-8")).digest()
    return base64.b64encode(digest)  # 44 bytes, well under bcrypt's 72


def hash_password(plain: str) -> str:
    salt = bcrypt.gensalt(rounds=ROUNDS)
    return bcrypt.hashpw(_prepare(plain), salt).decode("ascii")


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(_prepare(plain), hashed.encode("ascii"))
    except (ValueError, TypeError):
        return False


def assert_strong_password(plain: str) -> None:
    """Reject obviously weak passwords.

    The full HIBP top-1M check via the pwnedpasswords library is invoked
    asynchronously by the auth router (network call) — this function
    handles the deterministic, in-memory rules.
    """
    if len(plain) < MIN_PASSWORD_LENGTH:
        raise WeakPasswordError(
            f"Lösenordet måste vara minst {MIN_PASSWORD_LENGTH} tecken."
        )
    if plain.lower() in {"password123!", "lösenord1234", "vittring1234"}:
        raise WeakPasswordError("Lösenordet är för vanligt — välj något annat.")
