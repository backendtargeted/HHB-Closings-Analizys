"""Tests for shared sold-properties pipeline helpers (Investor Sold reuse)."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.services.sold_properties import (
    analyze,
    build_export_workbook,
    earliest_prospect_list,
    parse_sold_month,
    result_from_metrics_dict,
)
from app.services.analysis import parse_tags
from app.services.analysis import _dedupe_parsed_tag_events as dedupe

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


def test_earliest_prospect_list_sources():
    eight = dedupe(parse_tags("List Purchased 8020 3/2025"))
    dt, src = earliest_prospect_list(eight, "List Purchased 8020 3/2025")
    assert src == "8020"
    assert dt is not None and dt.month == 3 and dt.year == 2025

    lip_tags = "Probates NY Nassau 04-2025,List Purchased 8020 6/2025"
    dt, src = earliest_prospect_list(dedupe(parse_tags(lip_tags)), lip_tags)
    assert src == "lip"
    assert dt is not None and dt.month == 4 and dt.year == 2025

    ca_tags = "List Purchased Court Alerts 5/2025"
    dt, src = earliest_prospect_list([], ca_tags)
    assert src == "court_alerts"
    assert dt is not None and dt.month == 5

    dt, src = earliest_prospect_list([], "", "Court Alerts, High Equity")
    assert dt is None and src == "court_alerts"

    dt, src = earliest_prospect_list([], "", "LI Profiles")
    assert dt is None and src == "lip"


def test_cohort_excludes_blank_and_unparseable(sp_paths):
    result = analyze(sp_paths["reisift"], sp_paths["ql"])
    # 100 Main, 200 Oak, 400 Elm, 600 Willow, 700 Cedar — not 300 (blank) or 500 (unparseable)
    assert result.cohort_rows == 5
    assert result.sold_month_unparseable == 1
    keys = {r.address_key for r in result.rows}
    assert any("100 main" in k for k in keys)
    assert any("200 oak" in k for k in keys)
    assert any("400 elm" in k for k in keys)
    assert any("600 willow" in k for k in keys)
    assert any("700 cedar" in k for k in keys)
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
    assert main.qualified_lead_matched is True
    assert main.prospect_matched is True
    assert main.prospect_source == "ql"
    assert main.pipeline_stage in (
        "QUALIFIED_LEAD",
        "OPPORTUNITY",
        "HHB_CLOSED",
    )
    oak = by_street["200 oak ave"]
    assert oak.qualified_lead_matched is False
    assert oak.lead_matched is False
    assert oak.pipeline_stage == "MARKETED"


def test_prospect_from_podio_seller_leads(sp_paths):
    result = analyze(sp_paths["reisift"], sp_paths["ql"])
    by_street = {r.street.lower(): r for r in result.rows}
    willow = by_street["600 willow ln"]
    assert willow.lead_matched is True
    assert willow.lead_source == "podio"
    assert willow.prospect_matched is True
    assert willow.prospect_source == "podio"
    assert willow.pipeline_stage == "LEAD"
    # Spaced "Podio Seller Leads" must not count
    cedar = by_street["700 cedar ct"]
    assert cedar.prospect_matched is False
    assert cedar.pipeline_stage == "PROSPECT"


def test_podio_prospect_plus_opportunity(sp_paths):
    result = analyze(
        sp_paths["reisift"],
        sp_paths["ql"],
        opportunities_path=sp_paths["opps"],
    )
    by_street = {r.street.lower(): r for r in result.rows}
    willow = by_street["600 willow ln"]
    assert willow.lead_matched is True
    assert willow.prospect_source == "podio"
    assert willow.opp_matched is True
    assert willow.pipeline_stage == "OPPORTUNITY"


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
    assert elm.pipeline_stage == "OPPORTUNITY"
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
    from io import BytesIO

    import openpyxl

    wb = openpyxl.load_workbook(BytesIO(xlsx))
    assert "Never Marketed" in wb.sheetnames
    restored = result_from_metrics_dict(result.to_api_dict())
    assert restored.cohort_rows == result.cohort_rows
    assert len(restored.rows) == len(result.rows)
