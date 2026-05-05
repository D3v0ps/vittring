"""saved_signals table

Revision ID: 0002
Revises: 0001
Create Date: 2026-05-05 22:00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "saved_signals",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("signal_type", sa.Text(), nullable=False),
        sa.Column("signal_id", sa.BigInteger(), nullable=False),
        sa.Column(
            "saved_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_saved_signals_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_saved_signals")),
        sa.UniqueConstraint(
            "user_id",
            "signal_type",
            "signal_id",
            name="uq_saved_signals_user_signal",
        ),
    )


def downgrade() -> None:
    op.drop_table("saved_signals")
