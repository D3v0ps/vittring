"""Application configuration loaded from environment.

All settings are validated at startup. Missing or malformed values cause the
process to fail loudly rather than degrade silently. Secrets live in
``/etc/vittring/.env`` on production (mode 640, owner ``root:vittring``).
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import (
    AnyHttpUrl,
    EmailStr,
    Field,
    PostgresDsn,
    SecretStr,
    field_validator,
)
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # App ------------------------------------------------------------------
    app_env: Literal["development", "staging", "production"] = "development"
    app_secret_key: SecretStr
    app_base_url: AnyHttpUrl
    tz: str = "Europe/Stockholm"

    # Database -------------------------------------------------------------
    database_url: PostgresDsn

    # Email (Resend) -------------------------------------------------------
    resend_api_key: SecretStr
    resend_webhook_secret: SecretStr | None = None
    email_from_address: EmailStr
    email_from_name: str = "Vittring"
    email_reply_to: EmailStr
    email_sending_domain: str

    # Stripe (deferred) ----------------------------------------------------
    stripe_secret_key: SecretStr | None = None
    stripe_webhook_secret: SecretStr | None = None
    stripe_price_solo_monthly: str | None = None
    stripe_price_team_monthly: str | None = None
    stripe_price_pro_monthly: str | None = None
    stripe_price_solo_annual: str | None = None
    stripe_price_team_annual: str | None = None
    stripe_price_pro_annual: str | None = None

    # Sentry ---------------------------------------------------------------
    sentry_dsn: SecretStr | None = None
    sentry_environment: str = "production"
    sentry_traces_sample_rate: float = 0.1

    # Data sources ---------------------------------------------------------
    jobtech_base_url: AnyHttpUrl = Field(
        default=AnyHttpUrl("https://jobsearch.api.jobtechdev.se")
    )
    jobtech_taxonomy_url: AnyHttpUrl = Field(
        default=AnyHttpUrl("https://taxonomy.api.jobtechdev.se")
    )
    ted_base_url: AnyHttpUrl = Field(default=AnyHttpUrl("https://api.ted.europa.eu/v3"))
    bolagsverket_backend: Literal["official", "poit"] = "poit"

    # Backups --------------------------------------------------------------
    backup_target: Literal["local", "storagebox"] = "local"
    backup_local_path: Path = Path("/var/backups/vittring")
    backup_encryption_passphrase: SecretStr | None = None
    backup_host: str | None = None
    backup_user: str | None = None
    backup_ssh_key_path: Path | None = None
    backup_remote_path: str | None = None

    # Derived helpers -----------------------------------------------------
    @property
    def billing_enabled(self) -> bool:
        return self.stripe_secret_key is not None and self.stripe_webhook_secret is not None

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"

    @field_validator("sentry_traces_sample_rate")
    @classmethod
    def _sample_rate_in_range(cls, v: float) -> float:
        if not 0.0 <= v <= 1.0:
            raise ValueError("sentry_traces_sample_rate must be between 0 and 1")
        return v


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Singleton accessor.

    Cached so import-time validation runs once. Tests can clear the cache
    via ``get_settings.cache_clear()`` after monkeypatching environment.
    """
    return Settings()  # type: ignore[call-arg]
