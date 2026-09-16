"""Tests for Gate 7 investor & in-list sold + pipeline depth."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.services.investor_sold import (
    analyze,
    build_export_workbook,
    result_from_metrics_dict,
    segment_for,
)

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def sold_path():
    return str(FIXTURES / "investor_sold_transactions.csv")


@pytest.fixture
def reisift_path():
    return str(FIXTURES / "investor_sold_reisift.csv")


@pytest.fixture
def ql_path():
    return str(FIXTURES / "investor_sold_ql.csv")


def test_segment_for_matrix():
    assert segment_for(True, True) == "both"
    assert segment_for(True, False) == "investor"
    assert segment_for(False, True) == "in_our_list"
    assert segment_for(False, False) == "neither"


def test_requires_reisift_and_ql(sold_path):
    with pytest.raises(ValueError, match="REISift"):
        analyze(sold_path)
    with pytest.raises(ValueError, match="Qualified Leads"):
        analyze(sold_path, reisift_path=str(FIXTURES / "investor_sold_reisift.csv"))


def test_segment_counts_and_pipeline(sold_path, reisift_path, ql_path):
    result = analyze(sold_path, reisift_path=reisift_path, ql_path=ql_path)
    # 6 CSV txns; Main St has 2 txns same dataflik+month → 5 property rows
    assert result.sold_rows_ingested == 6
    assert result.property_rows == 5
    assert len(result.rows) == 5
    assert result.unique_addresses == 5
    assert result.investor_count == 3  # main, pine, cedar
    assert result.in_our_list_count == 2  # oak, pine
    assert result.both_count == 1  # pine
    assert result.neither_count == 1  # elm
    assert result.date_window_start == "2026-05"
    assert result.date_window_end == "2026-07"
    assert result.enrichment_enabled is True

    by_street = {r.street.lower(): r for r in result.rows}
    assert by_street["100 main st"].transaction_count == 2
    assert by_street["100 main st"].marketed is True
    assert by_street["100 main st"].cc_touch_count >= 1
    assert by_street["200 oak ave"].prospect_matched is True
    assert by_street["200 oak ave"].lead_matched is True
    assert by_street["200 oak ave"].lead_source == "podio"
    assert by_street["200 oak ave"].prospect_source == "podio"
    assert by_street["200 oak ave"].pipeline_stage == "LEAD"
    assert by_street["300 pine rd"].segment == "both"
    assert by_street["300 pine rd"].qualified_lead_matched is True
    assert by_street["300 pine rd"].prospect_matched is True
    assert by_street["300 pine rd"].prospect_source == "ql"
    assert by_street["300 pine rd"].marketed is True
    assert by_street["300 pine rd"].pipeline_stage in (
        "QUALIFIED_LEAD",
        "OPPORTUNITY",
        "UNDER_CONTRACT",
        "HHB_CLOSED",
    )
    assert by_street["400 elm st"].reisift_matched is False
    assert by_street["400 elm st"].marketed is False

    assert result.marketed_count >= 2
    assert result.lead_matched >= 1
    assert result.qualified_lead_matched >= 1
    assert result.prospect_matched >= 2
    assert result.prospect_sources["podio"] >= 1
    assert result.prospect_sources["ql"] >= 1
    assert result.lead_sources["podio"] >= 1
    # Lost = in_list + investor + not closed (pine is both investor+in_list)
    assert result.lost_to_investor_count >= 1
    assert result.in_list_investor_count >= 1
    assert result.lost_by_stage
    assert "lost" in result.to_api_dict()
    assert any(s["segment"] == "in_our_list" and s["prospects_podio"] >= 1 for s in result.by_segment)
    assert result.pipeline_funnel
    assert result.to_api_dict()["inputs"]["property_rows"] == 5
    assert "marketing" in result.to_api_dict()
    assert "by_segment" in result.to_api_dict()


def test_by_month_and_county(sold_path, reisift_path, ql_path):
    result = analyze(sold_path, reisift_path=reisift_path, ql_path=ql_path)
    months = {r["sold_month"]: r for r in result.by_sold_month}
    assert months["2026-07"]["count"] == 2
    assert months["2026-07"]["investor"] == 1
    assert months["2026-07"]["in_our_list"] == 1
    assert months["2026-07"]["marketed"] >= 1
    counties = {r["county"]: r for r in result.by_county}
    assert counties["Erie"]["count"] == 2
    assert counties["Monroe"]["both"] == 1


def test_export_workbook_sheets(sold_path, reisift_path, ql_path):
    result = analyze(sold_path, reisift_path=reisift_path, ql_path=ql_path)
    xlsx = build_export_workbook(result)
    assert xlsx[:2] == b"PK"
    restored = result_from_metrics_dict(result.to_api_dict())
    assert restored.sold_rows_ingested == 6
    assert restored.property_rows == 5
    assert restored.both_count == 1
    assert restored.prospect_sources.get("podio", 0) >= 1
    assert restored.lost_to_investor_count == result.lost_to_investor_count
    assert len(restored.rows) == 5
    assert any(r.transaction_count == 2 for r in restored.rows)
    assert any(r.prospect_source == "podio" for r in restored.rows)
    assert any(r.lead_matched for r in restored.rows)


def test_missing_flags_raises(tmp_path, reisift_path, ql_path):
    bad = tmp_path / "bad.csv"
    bad.write_text(
        "property_address,property_city,state,property_zip\n1 Main,Buffalo,NY,14201\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="investor"):
        analyze(str(bad), reisift_path=reisift_path, ql_path=ql_path)
