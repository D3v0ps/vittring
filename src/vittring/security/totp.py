"""TOTP-based two-factor authentication."""

from __future__ import annotations

import pyotp


ISSUER = "Vittring"


def generate_secret() -> str:
    return pyotp.random_base32()


def provisioning_uri(secret: str, *, account_name: str) -> str:
    return pyotp.TOTP(secret).provisioning_uri(name=account_name, issuer_name=ISSUER)


def verify_code(secret: str, code: str) -> bool:
    return pyotp.TOTP(secret).verify(code, valid_window=1)
