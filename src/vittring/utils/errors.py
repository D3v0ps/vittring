"""Custom exception hierarchy.

All raised exceptions in the codebase inherit from ``VittringError`` so that
top-level handlers can distinguish expected domain errors from genuine bugs.
"""

from __future__ import annotations


class VittringError(Exception):
    """Base class for all application-raised exceptions."""


# Configuration / startup ----------------------------------------------------

class ConfigurationError(VittringError):
    """Configuration is missing or invalid."""


# Data ingestion -------------------------------------------------------------

class IngestError(VittringError):
    """An ingest adapter failed."""


class IngestSourceUnavailable(IngestError):
    """Upstream source returned an error or unreachable."""


class IngestParseError(IngestError):
    """Upstream payload could not be parsed into the expected shape."""


# Auth / users ---------------------------------------------------------------

class AuthError(VittringError):
    """Base for authentication and authorization failures."""


class InvalidCredentialsError(AuthError):
    pass


class AccountLockedError(AuthError):
    pass


class EmailNotVerifiedError(AuthError):
    pass


class TwoFactorRequiredError(AuthError):
    pass


class WeakPasswordError(AuthError):
    pass


# Subscriptions / billing ----------------------------------------------------

class SubscriptionError(VittringError):
    pass


class PlanLimitExceededError(SubscriptionError):
    """User attempted to exceed plan filter or seat count."""


class BillingError(VittringError):
    pass


class StripeWebhookError(BillingError):
    pass


# Email / delivery -----------------------------------------------------------

class EmailError(VittringError):
    pass


class DomainNotVerifiedError(EmailError):
    """Resend domain has not been verified yet — DNS records pending."""


# Rate limiting / abuse ------------------------------------------------------

class RateLimitExceededError(VittringError):
    def __init__(self, retry_after_seconds: int) -> None:
        super().__init__(f"Rate limit exceeded; retry after {retry_after_seconds}s")
        self.retry_after_seconds = retry_after_seconds
