"""User-starred signals.

A row in this table represents a single signal (job posting, company change,
or procurement) that a user has explicitly starred from the dashboard. The
composite ``UNIQUE(user_id, signal_type, signal_id)`` constraint makes the
toggle endpoint idempotent — the route either inserts a new row or deletes
the existing one.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from vittring.db import Base


class SavedSignal(Base):
    __tablename__ = "saved_signals"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    signal_type: Mapped[str] = mapped_column(Text, nullable=False)
    signal_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    saved_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "signal_type",
            "signal_id",
            name="uq_saved_signals_user_signal",
        ),
    )
