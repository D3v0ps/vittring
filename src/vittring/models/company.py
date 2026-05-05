"""Company aggregate — one row per organization number."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Index, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from vittring.db import Base


class Company(Base):
    __tablename__ = "companies"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    orgnr: Mapped[str] = mapped_column(String(13), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    sni_code: Mapped[str | None] = mapped_column(String(10), nullable=True)
    hq_municipality: Mapped[str | None] = mapped_column(Text, nullable=True)
    hq_county: Mapped[str | None] = mapped_column(Text, nullable=True)
    employee_count_band: Mapped[str | None] = mapped_column(Text, nullable=True)
    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        Index("idx_companies_municipality", "hq_municipality"),
        Index("idx_companies_sni", "sni_code"),
    )
