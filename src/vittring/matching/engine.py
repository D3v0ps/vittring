"""Pure matching predicates.

All functions here are deterministic and side-effect-free: same inputs always
produce the same boolean. The engine takes already-loaded Pydantic items
(see ``schemas/ingest.py``) so it can be unit-tested without database access.

Performance target (CLAUDE.md §10): match 5 000 signals against all active
subscriptions in under 30 seconds on the CX23. The predicates are O(criteria
size) — fine for the expected workload of < 100 subscriptions × 5 000 signals.
"""

from __future__ import annotations

from collections.abc import Iterable

from vittring.matching.criteria import Criteria
from vittring.schemas.ingest import (
    CompanyChangeItem,
    JobPostingItem,
    ProcurementItem,
)


def _ci_in(value: str | None, options: Iterable[str]) -> bool:
    """Return True if ``value`` is in ``options``, comparing case-insensitively."""
    if value is None:
        return False
    needle = value.casefold()
    return any(needle == option.casefold() for option in options)


def _any_keyword_in(text: str | None, keywords: Iterable[str]) -> bool:
    if not text:
        return False
    haystack = text.casefold()
    return any(keyword.casefold() in haystack for keyword in keywords)


# ---------------------------------------------------------------------------
# Job postings
# ---------------------------------------------------------------------------

def match_job_posting(job: JobPostingItem, criteria: Criteria) -> bool:
    """Return True if a job posting passes the criteria.

    ``min_postings_per_employer`` is *not* checked here — it requires
    aggregation across multiple postings and is applied by the orchestrator
    after this predicate filters individual items.
    """
    if criteria.exclude_employer_orgnrs and job.employer_orgnr in criteria.exclude_employer_orgnrs:
        return False

    if criteria.occupation_concept_ids and not _ci_in(
        job.occupation_concept_id, criteria.occupation_concept_ids
    ):
        return False

    if criteria.occupations and not _ci_in(job.occupation_label, criteria.occupations):
        return False

    if criteria.municipalities or criteria.counties:
        municipality_match = (
            bool(criteria.municipalities)
            and _ci_in(job.workplace_municipality, criteria.municipalities)
        )
        county_match = (
            bool(criteria.counties) and _ci_in(job.workplace_county, criteria.counties)
        )
        if not (municipality_match or county_match):
            return False

    text = " ".join(filter(None, [job.headline, job.description]))
    if criteria.keywords_any and not _any_keyword_in(text, criteria.keywords_any):
        return False
    if criteria.keywords_none and _any_keyword_in(text, criteria.keywords_none):
        return False

    return True


# ---------------------------------------------------------------------------
# Company changes
# ---------------------------------------------------------------------------

def match_company_change(
    change: CompanyChangeItem,
    criteria: Criteria,
    *,
    company_municipality: str | None = None,
    company_county: str | None = None,
    company_sni: str | None = None,
) -> bool:
    """Return True if a company change matches.

    Geography and SNI are properties of the *company*, not the change row,
    so the orchestrator passes them in. ``change_types`` filters the change's
    own type.
    """
    if criteria.change_types and not _ci_in(change.change_type, criteria.change_types):
        return False
    if criteria.sni_codes and not _ci_in(company_sni, criteria.sni_codes):
        return False
    if criteria.municipalities or criteria.counties:
        municipality_match = (
            bool(criteria.municipalities)
            and _ci_in(company_municipality, criteria.municipalities)
        )
        county_match = (
            bool(criteria.counties) and _ci_in(company_county, criteria.counties)
        )
        if not (municipality_match or county_match):
            return False
    return True


# ---------------------------------------------------------------------------
# Procurements
# ---------------------------------------------------------------------------

def match_procurement(
    procurement: ProcurementItem,
    criteria: Criteria,
    *,
    buyer_municipality: str | None = None,
) -> bool:
    """Return True if a procurement matches the criteria."""
    if criteria.cpv_codes:
        normalized = {code.casefold() for code in procurement.cpv_codes}
        wanted = {code.casefold() for code in criteria.cpv_codes}
        if not (normalized & wanted):
            return False

    if (
        criteria.min_procurement_value_sek is not None
        and (procurement.estimated_value_sek or 0) < criteria.min_procurement_value_sek
    ):
        return False

    if criteria.municipalities and not _ci_in(buyer_municipality, criteria.municipalities):
        return False

    text = " ".join(filter(None, [procurement.title, procurement.description]))
    if criteria.keywords_any and not _any_keyword_in(text, criteria.keywords_any):
        return False
    if criteria.keywords_none and _any_keyword_in(text, criteria.keywords_none):
        return False

    return True
