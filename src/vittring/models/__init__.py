"""ORM models for all persisted entities.

Importing this package registers every model on the shared metadata so that
Alembic ``--autogenerate`` and ``Base.metadata.create_all`` see the full
schema without further imports.
"""

from vittring.models.audit import AuditLog, StripeWebhookEvent
from vittring.models.company import Company
from vittring.models.signals import (
    CompanyChange,
    JobPosting,
    Procurement,
)
from vittring.models.subscription import (
    DeliveredAlert,
    Subscription,
)
from vittring.models.user import (
    EmailVerificationToken,
    PasswordResetToken,
    User,
)

__all__ = [
    "AuditLog",
    "Company",
    "CompanyChange",
    "DeliveredAlert",
    "EmailVerificationToken",
    "JobPosting",
    "PasswordResetToken",
    "Procurement",
    "StripeWebhookEvent",
    "Subscription",
    "User",
]
