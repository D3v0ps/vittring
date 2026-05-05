"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-05-05 09:00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS citext")

    op.create_table(
        "companies",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("orgnr", sa.String(length=13), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("sni_code", sa.String(length=10), nullable=True),
        sa.Column("hq_municipality", sa.Text(), nullable=True),
        sa.Column("hq_county", sa.Text(), nullable=True),
        sa.Column("employee_count_band", sa.Text(), nullable=True),
        sa.Column(
            "first_seen_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "last_seen_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_companies")),
        sa.UniqueConstraint("orgnr", name=op.f("uq_companies_orgnr")),
    )
    op.create_index("idx_companies_municipality", "companies", ["hq_municipality"])
    op.create_index("idx_companies_sni", "companies", ["sni_code"])

    op.create_table(
        "users",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("email", postgresql.CITEXT(), nullable=False),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column("full_name", sa.Text(), nullable=True),
        sa.Column("company_name", sa.Text(), nullable=True),
        sa.Column("plan", sa.Text(), server_default="trial", nullable=False),
        sa.Column("trial_ends_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("stripe_customer_id", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("is_verified", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("is_superuser", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("totp_secret", sa.Text(), nullable=True),
        sa.Column("totp_enabled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failed_login_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_login_ip", postgresql.INET(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("deletion_requested_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_users")),
        sa.UniqueConstraint("email", name=op.f("uq_users_email")),
    )

    op.create_table(
        "job_postings",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("external_id", sa.Text(), nullable=False),
        sa.Column("company_id", sa.BigInteger(), nullable=True),
        sa.Column("employer_name", sa.Text(), nullable=False),
        sa.Column("headline", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("occupation_label", sa.Text(), nullable=True),
        sa.Column("occupation_concept_id", sa.Text(), nullable=True),
        sa.Column("workplace_municipality", sa.Text(), nullable=True),
        sa.Column("workplace_county", sa.Text(), nullable=True),
        sa.Column("employment_type", sa.Text(), nullable=True),
        sa.Column("duration", sa.Text(), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=True),
        sa.Column(
            "ingested_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["company_id"],
            ["companies.id"],
            name=op.f("fk_job_postings_company_id_companies"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_job_postings")),
        sa.UniqueConstraint("external_id", name=op.f("uq_job_postings_external_id")),
    )
    op.create_index("idx_jobs_published", "job_postings", ["published_at"])
    op.create_index("idx_jobs_company", "job_postings", ["company_id"])
    op.create_index("idx_jobs_municipality", "job_postings", ["workplace_municipality"])

    op.create_table(
        "company_changes",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("company_id", sa.BigInteger(), nullable=False),
        sa.Column("change_type", sa.Text(), nullable=False),
        sa.Column("old_value", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("new_value", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("source_ref", sa.Text(), nullable=True),
        sa.Column("changed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "ingested_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("personal_data_purged_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["company_id"],
            ["companies.id"],
            name=op.f("fk_company_changes_company_id_companies"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_company_changes")),
    )
    op.create_index(
        "idx_changes_company_changed",
        "company_changes",
        ["company_id", "changed_at"],
    )
    op.create_index(
        "idx_changes_purge_candidate",
        "company_changes",
        ["ingested_at"],
        postgresql_where=sa.text("personal_data_purged_at IS NULL"),
    )

    op.create_table(
        "procurements",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("external_id", sa.Text(), nullable=False),
        sa.Column("buyer_orgnr", sa.String(length=13), nullable=True),
        sa.Column("buyer_name", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "cpv_codes",
            postgresql.ARRAY(sa.Text()),
            server_default="{}",
            nullable=False,
        ),
        sa.Column("estimated_value_sek", sa.BigInteger(), nullable=True),
        sa.Column("procedure_type", sa.Text(), nullable=True),
        sa.Column("deadline", sa.DateTime(timezone=True), nullable=True),
        sa.Column("source_url", sa.Text(), nullable=True),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column(
            "ingested_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_procurements")),
        sa.UniqueConstraint("external_id", name=op.f("uq_procurements_external_id")),
    )
    op.create_index("idx_proc_deadline", "procurements", ["deadline"])
    op.create_index(
        "idx_proc_cpv",
        "procurements",
        ["cpv_codes"],
        postgresql_using="gin",
    )

    op.create_table(
        "subscriptions",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("signal_types", postgresql.ARRAY(sa.Text()), nullable=False),
        sa.Column("criteria", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("active", sa.Boolean(), server_default="true", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_subscriptions_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_subscriptions")),
    )
    op.create_index(
        "idx_subs_user_active",
        "subscriptions",
        ["user_id"],
        postgresql_where=sa.text("active"),
    )

    op.create_table(
        "delivered_alerts",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("subscription_id", sa.BigInteger(), nullable=False),
        sa.Column("signal_type", sa.Text(), nullable=False),
        sa.Column("signal_id", sa.BigInteger(), nullable=False),
        sa.Column(
            "delivered_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("opened_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("clicked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resend_message_id", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(
            ["subscription_id"],
            ["subscriptions.id"],
            name=op.f("fk_delivered_alerts_subscription_id_subscriptions"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_delivered_alerts_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_delivered_alerts")),
        sa.UniqueConstraint(
            "user_id",
            "signal_type",
            "signal_id",
            name="uq_delivered_alerts_user_signal",
        ),
    )

    op.create_table(
        "audit_log",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=True),
        sa.Column("action", sa.Text(), nullable=False),
        sa.Column("ip", postgresql.INET(), nullable=True),
        sa.Column("user_agent", sa.Text(), nullable=True),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_audit_log_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_audit_log")),
    )
    op.create_index("idx_audit_user_created", "audit_log", ["user_id", "created_at"])
    op.create_index("idx_audit_action_created", "audit_log", ["action", "created_at"])

    op.create_table(
        "stripe_webhook_events",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("event_type", sa.Text(), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column(
            "received_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_stripe_webhook_events")),
    )

    op.create_table(
        "password_reset_tokens",
        sa.Column("token_hash", sa.Text(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_password_reset_tokens_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("token_hash", name=op.f("pk_password_reset_tokens")),
    )

    op.create_table(
        "email_verification_tokens",
        sa.Column("token_hash", sa.Text(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_email_verification_tokens_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("token_hash", name=op.f("pk_email_verification_tokens")),
    )


def downgrade() -> None:
    op.drop_table("email_verification_tokens")
    op.drop_table("password_reset_tokens")
    op.drop_table("stripe_webhook_events")
    op.drop_index("idx_audit_action_created", table_name="audit_log")
    op.drop_index("idx_audit_user_created", table_name="audit_log")
    op.drop_table("audit_log")
    op.drop_table("delivered_alerts")
    op.drop_index("idx_subs_user_active", table_name="subscriptions")
    op.drop_table("subscriptions")
    op.drop_index("idx_proc_cpv", table_name="procurements")
    op.drop_index("idx_proc_deadline", table_name="procurements")
    op.drop_table("procurements")
    op.drop_index("idx_changes_purge_candidate", table_name="company_changes")
    op.drop_index("idx_changes_company_changed", table_name="company_changes")
    op.drop_table("company_changes")
    op.drop_index("idx_jobs_municipality", table_name="job_postings")
    op.drop_index("idx_jobs_company", table_name="job_postings")
    op.drop_index("idx_jobs_published", table_name="job_postings")
    op.drop_table("job_postings")
    op.drop_table("users")
    op.drop_index("idx_companies_sni", table_name="companies")
    op.drop_index("idx_companies_municipality", table_name="companies")
    op.drop_table("companies")
    op.execute("DROP EXTENSION IF EXISTS citext")
