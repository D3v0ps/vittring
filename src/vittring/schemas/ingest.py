"""Pydantic schemas representing parsed upstream items.

These are the typed payloads adapters yield from ``fetch_since``. Storage is
delegated to ``persist`` which converts them into ORM rows.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore", str_strip_whitespace=True)


class JobPostingItem(_Frozen):
    external_id: str
    employer_orgnr: str | None = None
    employer_name: str
    headline: str
    description: str | None = None
    occupation_label: str | None = None
    occupation_concept_id: str | None = None
    workplace_municipality: str | None = None
    workplace_county: str | None = None
    employment_type: str | None = None
    duration: str | None = None
    published_at: datetime
    source_url: str | None = None


CompanyChangeType = Literal[
    "ceo",
    "board_member",
    "address",
    "name",
    "remark",
    "liquidation",
    "sni",
]


class CompanyChangeItem(_Frozen):
    orgnr: str
    company_name: str
    change_type: CompanyChangeType
    old_value: dict[str, Any] | None = None
    new_value: dict[str, Any] | None = None
    source_ref: str | None = None
    changed_at: datetime


class ProcurementItem(_Frozen):
    external_id: str
    buyer_orgnr: str | None = None
    buyer_name: str
    title: str
    description: str | None = None
    cpv_codes: list[str] = Field(default_factory=list)
    estimated_value_sek: int | None = None
    procedure_type: str | None = None
    deadline: datetime | None = None
    source_url: str | None = None
    source: str  # e.g. 'ted'
