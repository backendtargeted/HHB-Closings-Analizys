"""Tests for Gate 8 investor & in-list sold segments."""

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


def test_segment_for_matrix():
    assert segment_for(True, True) == "both"
    assert segment_for(True, False) == "investor"
    assert segment_for(False, True) == "in_our_list"
    assert segment_for(False, False) == "neither"


def test_segment_counts_on_property_grain(sold_path):
    result = analyze(sold_path)
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
    by_street = {r.street.lower(): r for r in result.rows}
    assert by_street["100 main st"].transaction_count == 2
    assert by_street["200 oak ave"].transaction_count == 1
    assert by_street["300 pine rd"].segment == "both"
    assert result.enrichment_enabled is False
    assert result.to_api_dict()["inputs"]["property_rows"] == 5


def test_by_month_and_county(sold_path):
    result = analyze(sold_path)
    months = {r["sold_month"]: r for r in result.by_sold_month}
    assert months["2026-07"]["count"] == 2
    assert months["2026-07"]["investor"] == 1
    assert months["2026-07"]["in_our_list"] == 1
    counties = {r["county"]: r for r in result.by_county}
    assert counties["Erie"]["count"] == 2
    assert counties["Monroe"]["both"] == 1


def test_export_workbook_sheets(sold_path):
    result = analyze(sold_path)
    xlsx = build_export_workbook(result)
    assert xlsx[:2] == b"PK"
    restored = result_from_metrics_dict(result.to_api_dict())
    assert restored.sold_rows_ingested == 6
    assert restored.property_rows == 5
    assert restored.both_count == 1
    assert len(restored.rows) == 5
    assert any(r.transaction_count == 2 for r in restored.rows)


def test_missing_flags_raises(tmp_path):
    bad = tmp_path / "bad.csv"
    bad.write_text(
        "property_address,property_city,state,property_zip\n1 Main,Buffalo,NY,14201\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="investor"):
        analyze(str(bad))
