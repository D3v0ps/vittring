"""Shared test fixtures."""

from __future__ import annotations

import os

# Set required env vars before any vittring import that triggers Settings().
os.environ.setdefault("APP_ENV", "development")
os.environ.setdefault("APP_SECRET_KEY", "test-secret-key-with-enough-bytes-1234567890abcdefghi")
os.environ.setdefault("APP_BASE_URL", "http://localhost:8000")
os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+asyncpg://vittring:vittring@localhost:5432/vittring_test",
)
os.environ.setdefault("RESEND_API_KEY", "re_test")
os.environ.setdefault("EMAIL_FROM_ADDRESS", "test@example.com")
os.environ.setdefault("EMAIL_REPLY_TO", "test@example.com")
os.environ.setdefault("EMAIL_SENDING_DOMAIN", "example.com")
