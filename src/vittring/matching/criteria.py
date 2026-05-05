"""Typed criteria model used by the matching engine and the API."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

SignalType = Literal["job", "company_change", "procurement"]


class Criteria(BaseModel):
    """Filter spec stored as ``subscriptions.criteria`` JSONB.

    All fields are optional; an empty criteria object matches nothing useful
    (the API rejects creating a subscription without at least one selector).
    Strings are case-insensitive at match time — adapters store source values
    as-is, the matcher lowercases for comparison.
    """

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, frozen=True)

    # Job postings ---------------------------------------------------------
    occupations: list[str] = Field(default_factory=list)
    occupation_concept_ids: list[str] = Field(default_factory=list)

    # Geography (job postings + company changes) --------------------------
    municipalities: list[str] = Field(default_factory=list)
    counties: list[str] = Field(default_factory=list)

    # Industry codes (company changes) ------------------------------------
    sni_codes: list[str] = Field(default_factory=list)

    # Free-text (jobs + procurements) -------------------------------------
    keywords_any: list[str] = Field(default_factory=list)
    keywords_none: list[str] = Field(default_factory=list)

    # Aggregation gates (jobs) --------------------------------------------
    min_postings_per_employer: int | None = None
    exclude_employer_orgnrs: list[str] = Field(default_factory=list)

    # Procurement ----------------------------------------------------------
    cpv_codes: list[str] = Field(default_factory=list)
    min_procurement_value_sek: int | None = None

    # Company changes ------------------------------------------------------
    change_types: list[str] = Field(default_factory=list)
