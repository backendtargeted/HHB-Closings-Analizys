"""Tests for Gate 6 sold-properties cohort and pipeline depth."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.services.sold_properties import (
    analyze,
    build_export_workbook,
    parse_sold_month,
    result_from_metrics_dict,
)

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def sp_paths(tmp_path):
    return {
        "reisift": str(FIXTURES / "sold_properties_reisift.csv"),
        "ql": str(FIXTURES / "sold_properties_ql.csv"),
        "opps": str(FIXTURES / "sold_properties_opps.csv"),
    }


def test_parse_sold_month_formats():
    assert parse_sold_month("6/2025").month == 6
    assert parse_sold_month("06/2025").year == 2025
    assert parse_sold_month("2025-06").month == 6
    assert parse_sold_month("Jun 2025").month == 6
    assert parse_sold_month("") is None
    assert parse_sold_month("not-a-month") is None


def test_cohort_excludes_blank_and_unparseable(sp_paths):
    result = analyze(sp_paths["reisift"], sp_paths["ql"])
    # 100 Main, 200 Oak, 400 Elm — not 300 (blank) or 500 (unparseable)
    assert result.cohort_rows == 3
    assert result.sold_month_unparseable == 1
    keys = {r.address_key for r in result.rows}
    assert any("100 main" in k for k in keys)
    assert any("200 oak" in k for k in keys)
    assert any("400 elm" in k for k in keys)
    assert not any("300 pine" in k for k in keys)


def test_marketed_and_touch_counts(sp_paths):
    result = analyze(sp_paths["reisift"], sp_paths["ql"])
    by_street = {r.street.lower(): r for r in result.rows}
    main = by_street["100 main st"]
    assert main.marketed is True
    assert main.cc_touch_count == 1
    assert main.sms_touch_count == 1
    assert main.dm_touch_count == 0
    assert result.marketed_count == 3  # main, oak, elm all have contacts


def test_prospect_match_from_ql(sp_paths):
    result = analyze(sp_paths["reisift"], sp_paths["ql"])
    by_street = {r.street.lower(): r for r in result.rows}
    main = by_street["100 main st"]
    assert main.prospect_matched is True
    assert main.prospect_source == "ql"
    assert main.pipeline_stage in ("PROSPECT", "OPPORTUNITY", "UNDER_CONTRACT", "HHB_CLOSED")
    oak = by_street["200 oak ave"]
    assert oak.prospect_matched is False
    assert oak.pipeline_stage == "MARKETED"


def test_under_contract_and_opportunity(sp_paths):
    result = analyze(
        sp_paths["reisift"],
        sp_paths["ql"],
        opportunities_path=sp_paths["opps"],
    )
    by_street = {r.street.lower(): r for r in result.rows}
    elm = by_street["400 elm st"]
    assert elm.under_contract_date.startswith("2025-02")
    assert elm.opp_matched is True
    assert elm.pipeline_stage in ("OPPORTUNITY", "UNDER_CONTRACT")
    assert result.opp_matched >= 1
    assert result.under_contract_count >= 1


def test_missing_sold_column_raises(tmp_path, sp_paths):
    bad = tmp_path / "no_sold.csv"
    bad.write_text(
        "Property address,Property city,Property state,Property zip,Tags\n"
        "1 A St,Town,NY,11772,(8020) CC - 1/2025\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="in_sold_properties_full"):
        analyze(str(bad), sp_paths["ql"])


def test_export_and_roundtrip(sp_paths):
    result = analyze(sp_paths["reisift"], sp_paths["ql"], opportunities_path=sp_paths["opps"])
    xlsx = build_export_workbook(result)
    assert len(xlsx) > 100
    restored = result_from_metrics_dict(result.to_api_dict())
    assert restored.cohort_rows == result.cohort_rows
    assert len(restored.rows) == len(result.rows)
