"""Password hashing and strength check.

Uses ``bcrypt_sha256`` rather than plain ``bcrypt`` so passphrases longer than
72 bytes are not silently truncated (and modern ``bcrypt`` >= 4 raises on
oversize input). The wrapper SHA-256-hashes the plaintext first, then bcrypts
the digest — the resulting input to bcrypt is always 64 bytes regardless of
the original length.
"""

from __future__ import annotations

from passlib.context import CryptContext

from vittring.utils.errors import WeakPasswordError

_pwd_context = CryptContext(
    schemes=["bcrypt_sha256"],
    deprecated="auto",
    bcrypt_sha256__rounds=12,
)

MIN_PASSWORD_LENGTH = 12


def hash_password(plain: str) -> str:
    return _pwd_context.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    return _pwd_context.verify(plain, hashed)


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
