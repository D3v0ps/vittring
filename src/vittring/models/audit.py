"""Audit log and Stripe webhook idempotency table."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Index,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import INET, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from vittring.db import Base


class AuditLog(Base):
    """Append-only audit trail.

    Action vocabulary (extend as needed): ``login``, ``login_failed``,
    ``password_change``, ``password_reset``, ``email_verified``, ``2fa_enable``,
    ``2fa_disable``, ``account_locked``, ``gdpr_export``, ``gdpr_delete``,
    ``plan_change``, ``subscription_created``, ``subscription_deleted``,
    ``deploy``.
    """

    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    action: Mapped[str] = mapped_column(Text, nullable=False)
    ip: Mapped[str | None] = mapped_column(INET, nullable=True)
    user_agent: Mapped[str | None] = mapped_column(Text, nullable=True)
    audit_metadata: Mapped[dict[str, Any] | None] = mapped_column(
        "metadata", JSONB, nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        Index("idx_audit_user_created", "user_id", "created_at"),
        Index("idx_audit_action_created", "action", "created_at"),
    )


class StripeWebhookEvent(Base):
    """Idempotency record for Stripe webhook deliveries.

    Stripe retries failed deliveries; processing is idempotent because the
    primary key is the Stripe event id. Re-deliveries are no-ops.
    """

    __tablename__ = "stripe_webhook_events"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    event_type: Mapped[str] = mapped_column(Text, nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
