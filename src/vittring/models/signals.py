"""Signal models: job postings, company changes, procurements."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from vittring.db import Base


class JobPosting(Base):
    __tablename__ = "job_postings"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    external_id: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    company_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("companies.id", ondelete="SET NULL"),
        nullable=True,
    )
    employer_name: Mapped[str] = mapped_column(Text, nullable=False)
    headline: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    occupation_label: Mapped[str | None] = mapped_column(Text, nullable=True)
    occupation_concept_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    workplace_municipality: Mapped[str | None] = mapped_column(Text, nullable=True)
    workplace_county: Mapped[str | None] = mapped_column(Text, nullable=True)
    employment_type: Mapped[str | None] = mapped_column(Text, nullable=True)
    duration: Mapped[str | None] = mapped_column(Text, nullable=True)
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    source_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    ingested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        Index("idx_jobs_published", "published_at"),
        Index("idx_jobs_company", "company_id"),
        Index("idx_jobs_municipality", "workplace_municipality"),
    )


class CompanyChange(Base):
    """Bolagsverket / PoIT change records.

    Personal data (officer names) lives in ``old_value`` / ``new_value`` and is
    purged by the ``scrub_personal_data`` job after the GDPR retention window.
    """

    __tablename__ = "company_changes"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    company_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("companies.id"),
        nullable=False,
    )
    change_type: Mapped[str] = mapped_column(Text, nullable=False)
    old_value: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    new_value: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    source_ref: Mapped[str | None] = mapped_column(Text, nullable=True)
    changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ingested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    personal_data_purged_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    __table_args__ = (
        Index("idx_changes_company_changed", "company_id", "changed_at"),
        Index(
            "idx_changes_purge_candidate",
            "ingested_at",
            postgresql_where=("personal_data_purged_at IS NULL"),
        ),
    )


class Procurement(Base):
    __tablename__ = "procurements"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    external_id: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    buyer_orgnr: Mapped[str | None] = mapped_column(String(13), nullable=True)
    buyer_name: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    cpv_codes: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, server_default="{}"
    )
    estimated_value_sek: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    procedure_type: Mapped[str | None] = mapped_column(Text, nullable=True)
    deadline: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    source_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    source: Mapped[str] = mapped_column(Text, nullable=False)
    ingested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        Index("idx_proc_deadline", "deadline"),
        Index("idx_proc_cpv", "cpv_codes", postgresql_using="gin"),
    )
