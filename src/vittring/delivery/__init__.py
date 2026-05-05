"""Outbound email delivery via Resend."""

from vittring.delivery.email import send_email
from vittring.delivery.domain_setup import (
    DomainStatus,
    ensure_domain_verified,
)

__all__ = ["DomainStatus", "ensure_domain_verified", "send_email"]
