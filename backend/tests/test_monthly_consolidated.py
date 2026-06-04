"""Tests for monthly consolidated report service."""

from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from app.services.monthly_consolidated import (
    analyze,
    compute_combinations,
    compute_list_metrics,
    filter_reisift_cohort,
    parse_report_month,
    row_has_closing_tag,
    row_has_sf_tag,
    split_list_tokens,
)

FIXTURES = Path(__file__).parent / "fixtures"
REISIFT = FIXTURES / "monthly_reisift_sample.csv"
QL = FIXTURES / "qualified_leads_sample.csv"


def test_parse_report_month():
    start, end = parse_report_month("2025-03")
    assert start == date(2025, 3, 1)
    assert end == date(2025, 3, 31)


def test_split_list_tokens_dedupes():
    assert split_list_tokens("A, B, A") == ["A", "B"]


def test_row_has_sf_and_closing():
    assert row_has_sf_tag("(SF) STATUS - New - 2025-01-01")
    assert not row_has_sf_tag("(8020) CC - 1/2025")
    assert row_has_closing_tag("(CLOSED) 8020 - 6/2025")
    assert not row_has_closing_tag("(8020) CC - 1/2025")


def test_filter_cohort_march_only():
    df = pd.read_csv(REISIFT)
    cohort, _ = filter_reisift_cohort(df, date(2025, 3, 1), date(2025, 3, 31))
    assert len(cohort) == 4


def test_compute_list_metrics():
    df = pd.read_csv(REISIFT)
    cohort, _ = filter_reisift_cohort(df, date(2025, 3, 1), date(2025, 3, 31))
    metrics = compute_list_metrics(cohort, {"High Equity": 2})
    by_token = {m.token: m for m in metrics}
    assert by_token["High Equity"].row_count == 3
    assert by_token["High Equity"].closing_count == 2
    assert by_token["High Equity"].crm_lead_count >= 1


def test_combinations_min_rows():
    df = pd.read_csv(REISIFT)
    cohort, _ = filter_reisift_cohort(df, date(2025, 3, 1), date(2025, 3, 31))
    combos = compute_combinations(cohort, min_rows=2)
    assert any(c.lists_key == "Default Risk + High Equity" for c in combos)


def test_analyze_integration():
    result = analyze(str(REISIFT), str(QL), "2025-03")
    assert result.cohort_rows == 4
    assert result.closing_rows == 2
    assert result.crm_lead_rows >= 2
    assert result.qualified_leads["posted_in_window"] >= 0
    d = result.to_dict()
    assert d["report_month"] == "2025-03"
    assert len(d["lists"]) > 0


def test_build_export_workbook():
    from app.services.monthly_consolidated import build_export_workbook

    result = analyze(str(REISIFT), str(QL), "2025-03")
    data = build_export_workbook(result)
    assert len(data) > 1000
