"""Matching-engine tests — 100 % branch coverage required.

Each predicate is exercised on:
1. The empty-criteria base case (matches everything).
2. The positive case for each individual criterion.
3. The negative case for each individual criterion.
4. Edge cases: case-insensitivity, missing optional fields, multi-criterion
   AND semantics, geography OR semantics.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from vittring.matching.criteria import Criteria
from vittring.matching.engine import (
    match_company_change,
    match_job_posting,
    match_procurement,
)
from vittring.schemas.ingest import (
    CompanyChangeItem,
    JobPostingItem,
    ProcurementItem,
)


# ---------------------------------------------------------------------------
# Builders
# ---------------------------------------------------------------------------

def make_job(**overrides: object) -> JobPostingItem:
    base: dict[str, object] = {
        "external_id": "job-1",
        "employer_orgnr": "5560000001",
        "employer_name": "Acme Bemanning AB",
        "headline": "Lagerarbetare till logistikcenter",
        "description": "Vi söker dig som vill jobba i bemanning, interim eller konsult.",
        "occupation_label": "Lagerarbetare",
        "occupation_concept_id": "pBR2_VG3_NDr",
        "workplace_municipality": "Södertälje",
        "workplace_county": "Stockholms län",
        "employment_type": "Vanlig anställning",
        "duration": "Tillsvidare",
        "published_at": datetime(2026, 5, 1, 8, 0, tzinfo=timezone.utc),
        "source_url": "https://example.com/jobs/1",
    }
    base.update(overrides)
    return JobPostingItem(**base)  # type: ignore[arg-type]


def make_change(**overrides: object) -> CompanyChangeItem:
    base: dict[str, object] = {
        "orgnr": "5560000001",
        "company_name": "Acme Bemanning AB",
        "change_type": "ceo",
        "old_value": {"name": "Anna Andersson"},
        "new_value": {"name": "Bo Bengtsson"},
        "source_ref": "kungorelse-123",
        "changed_at": datetime(2026, 5, 1, 8, 0, tzinfo=timezone.utc),
    }
    base.update(overrides)
    return CompanyChangeItem(**base)  # type: ignore[arg-type]


def make_procurement(**overrides: object) -> ProcurementItem:
    base: dict[str, object] = {
        "external_id": "ted-1",
        "buyer_orgnr": "2120000001",
        "buyer_name": "Stockholms kommun",
        "title": "Ramavtal för bemanning av lagerpersonal",
        "description": "Avser konsult- och bemanningstjänster.",
        "cpv_codes": ["79610000", "79620000"],
        "estimated_value_sek": 1_500_000,
        "procedure_type": "open",
        "deadline": datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc),
        "source_url": "https://ted.europa.eu/notice/1",
        "source": "ted",
    }
    base.update(overrides)
    return ProcurementItem(**base)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Job postings
# ---------------------------------------------------------------------------

class TestMatchJobPosting:
    def test_empty_criteria_matches(self) -> None:
        assert match_job_posting(make_job(), Criteria()) is True

    def test_excluded_orgnr_rejects(self) -> None:
        criteria = Criteria(exclude_employer_orgnrs=["5560000001"])
        assert match_job_posting(make_job(), criteria) is False

    def test_excluded_orgnr_does_not_block_others(self) -> None:
        criteria = Criteria(exclude_employer_orgnrs=["5560000099"])
        assert match_job_posting(make_job(), criteria) is True

    def test_occupation_concept_id_match(self) -> None:
        criteria = Criteria(occupation_concept_ids=["pBR2_VG3_NDr"])
        assert match_job_posting(make_job(), criteria) is True

    def test_occupation_concept_id_miss(self) -> None:
        criteria = Criteria(occupation_concept_ids=["other"])
        assert match_job_posting(make_job(), criteria) is False

    def test_occupation_concept_id_with_none_on_job(self) -> None:
        criteria = Criteria(occupation_concept_ids=["pBR2_VG3_NDr"])
        job = make_job(occupation_concept_id=None)
        assert match_job_posting(job, criteria) is False

    def test_occupation_label_case_insensitive(self) -> None:
        criteria = Criteria(occupations=["LAGERARBETARE"])
        assert match_job_posting(make_job(), criteria) is True

    def test_occupation_label_miss(self) -> None:
        criteria = Criteria(occupations=["Truckförare"])
        assert match_job_posting(make_job(), criteria) is False

    def test_geography_municipality_match(self) -> None:
        criteria = Criteria(municipalities=["Södertälje"])
        assert match_job_posting(make_job(), criteria) is True

    def test_geography_county_match_when_municipality_misses(self) -> None:
        criteria = Criteria(
            municipalities=["Göteborg"], counties=["Stockholms län"]
        )
        assert match_job_posting(make_job(), criteria) is True

    def test_geography_both_miss(self) -> None:
        criteria = Criteria(municipalities=["Göteborg"], counties=["Västra Götaland"])
        assert match_job_posting(make_job(), criteria) is False

    def test_geography_only_county_set_match(self) -> None:
        criteria = Criteria(counties=["Stockholms län"])
        assert match_job_posting(make_job(), criteria) is True

    def test_geography_only_municipality_set_miss(self) -> None:
        criteria = Criteria(municipalities=["Malmö"])
        assert match_job_posting(make_job(), criteria) is False

    def test_keywords_any_match(self) -> None:
        criteria = Criteria(keywords_any=["bemanning"])
        assert match_job_posting(make_job(), criteria) is True

    def test_keywords_any_miss(self) -> None:
        criteria = Criteria(keywords_any=["sjuksköterska"])
        assert match_job_posting(make_job(), criteria) is False

    def test_keywords_any_with_empty_text(self) -> None:
        criteria = Criteria(keywords_any=["bemanning"])
        job = make_job(headline="", description=None)
        assert match_job_posting(job, criteria) is False

    def test_keywords_none_excludes(self) -> None:
        criteria = Criteria(keywords_none=["tillsvidare"])
        # description includes "tillsvidare"? No, but headline+description must
        # not contain "tillsvidare" — let's force it in description.
        job = make_job(description="Anställning på tillsvidare basis.")
        assert match_job_posting(job, criteria) is False

    def test_keywords_none_passes_when_absent(self) -> None:
        criteria = Criteria(keywords_none=["sjuksköterska"])
        assert match_job_posting(make_job(), criteria) is True

    def test_combined_and_semantics(self) -> None:
        criteria = Criteria(
            occupations=["Lagerarbetare"],
            municipalities=["Södertälje"],
            keywords_any=["bemanning"],
        )
        assert match_job_posting(make_job(), criteria) is True

    def test_combined_one_failing_rejects_all(self) -> None:
        criteria = Criteria(
            occupations=["Lagerarbetare"],
            municipalities=["Göteborg"],  # this fails
            keywords_any=["bemanning"],
        )
        assert match_job_posting(make_job(), criteria) is False


# ---------------------------------------------------------------------------
# Company changes
# ---------------------------------------------------------------------------

class TestMatchCompanyChange:
    def test_empty_criteria_matches(self) -> None:
        assert match_company_change(make_change(), Criteria()) is True

    def test_change_type_match(self) -> None:
        criteria = Criteria(change_types=["ceo"])
        assert match_company_change(make_change(), criteria) is True

    def test_change_type_miss(self) -> None:
        criteria = Criteria(change_types=["liquidation"])
        assert match_company_change(make_change(), criteria) is False

    def test_sni_match(self) -> None:
        criteria = Criteria(sni_codes=["49410"])
        assert (
            match_company_change(make_change(), criteria, company_sni="49410")
            is True
        )

    def test_sni_miss(self) -> None:
        criteria = Criteria(sni_codes=["49410"])
        assert (
            match_company_change(make_change(), criteria, company_sni="52100")
            is False
        )

    def test_sni_missing_on_company(self) -> None:
        criteria = Criteria(sni_codes=["49410"])
        assert match_company_change(make_change(), criteria, company_sni=None) is False

    def test_geography_municipality_match(self) -> None:
        criteria = Criteria(municipalities=["Stockholm"])
        assert (
            match_company_change(
                make_change(), criteria, company_municipality="Stockholm"
            )
            is True
        )

    def test_geography_county_match_when_municipality_misses(self) -> None:
        criteria = Criteria(
            municipalities=["Göteborg"], counties=["Stockholms län"]
        )
        assert (
            match_company_change(
                make_change(),
                criteria,
                company_municipality="Stockholm",
                company_county="Stockholms län",
            )
            is True
        )

    def test_geography_both_miss(self) -> None:
        criteria = Criteria(municipalities=["Göteborg"], counties=["Skåne län"])
        assert (
            match_company_change(
                make_change(),
                criteria,
                company_municipality="Stockholm",
                company_county="Stockholms län",
            )
            is False
        )

    def test_geography_only_municipality_set(self) -> None:
        criteria = Criteria(municipalities=["Stockholm"])
        assert (
            match_company_change(make_change(), criteria, company_municipality=None)
            is False
        )


# ---------------------------------------------------------------------------
# Procurements
# ---------------------------------------------------------------------------

class TestMatchProcurement:
    def test_empty_criteria_matches(self) -> None:
        assert match_procurement(make_procurement(), Criteria()) is True

    def test_cpv_intersection_match(self) -> None:
        criteria = Criteria(cpv_codes=["79610000"])
        assert match_procurement(make_procurement(), criteria) is True

    def test_cpv_disjoint_miss(self) -> None:
        criteria = Criteria(cpv_codes=["33100000"])
        assert match_procurement(make_procurement(), criteria) is False

    def test_min_value_match(self) -> None:
        criteria = Criteria(min_procurement_value_sek=1_000_000)
        assert match_procurement(make_procurement(), criteria) is True

    def test_min_value_miss(self) -> None:
        criteria = Criteria(min_procurement_value_sek=2_000_000)
        assert match_procurement(make_procurement(), criteria) is False

    def test_min_value_with_missing_value_treated_as_zero(self) -> None:
        criteria = Criteria(min_procurement_value_sek=1)
        proc = make_procurement(estimated_value_sek=None)
        assert match_procurement(proc, criteria) is False

    def test_municipality_match(self) -> None:
        criteria = Criteria(municipalities=["Stockholm"])
        assert (
            match_procurement(
                make_procurement(), criteria, buyer_municipality="Stockholm"
            )
            is True
        )

    def test_municipality_miss(self) -> None:
        criteria = Criteria(municipalities=["Göteborg"])
        assert (
            match_procurement(
                make_procurement(), criteria, buyer_municipality="Stockholm"
            )
            is False
        )

    def test_municipality_unknown(self) -> None:
        criteria = Criteria(municipalities=["Stockholm"])
        assert (
            match_procurement(make_procurement(), criteria, buyer_municipality=None)
            is False
        )

    def test_keywords_any_match(self) -> None:
        criteria = Criteria(keywords_any=["bemanning"])
        assert match_procurement(make_procurement(), criteria) is True

    def test_keywords_any_miss(self) -> None:
        criteria = Criteria(keywords_any=["sjukvård"])
        assert match_procurement(make_procurement(), criteria) is False

    def test_keywords_none_excludes(self) -> None:
        criteria = Criteria(keywords_none=["bemanning"])
        assert match_procurement(make_procurement(), criteria) is False

    def test_keywords_none_passes_when_absent(self) -> None:
        criteria = Criteria(keywords_none=["sjukvård"])
        assert match_procurement(make_procurement(), criteria) is True

    def test_keywords_with_empty_text(self) -> None:
        criteria = Criteria(keywords_any=["bemanning"])
        proc = make_procurement(title="", description=None)
        assert match_procurement(proc, criteria) is False


# ---------------------------------------------------------------------------
# Sanity checks on Criteria itself
# ---------------------------------------------------------------------------

class TestCriteria:
    def test_extra_fields_rejected(self) -> None:
        with pytest.raises(ValueError):
            Criteria(unknown_field=True)  # type: ignore[call-arg]

    def test_strings_stripped(self) -> None:
        c = Criteria(occupations=["  Lagerarbetare  "])
        assert c.occupations == ["Lagerarbetare"]

    def test_frozen(self) -> None:
        c = Criteria()
        with pytest.raises((TypeError, ValueError)):
            c.occupations = ["x"]  # type: ignore[misc]
