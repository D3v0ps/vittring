"""Password hashing and strength check."""

from __future__ import annotations

from passlib.context import CryptContext

from vittring.utils.errors import WeakPasswordError

_pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto", bcrypt__rounds=12)

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
