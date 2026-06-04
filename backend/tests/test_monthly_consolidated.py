"""Tests for monthly consolidated report service."""

from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from app.services.monthly_consolidated import (
    analyze,
    analysis_list_tokens,
    combinations_from_scan,
    compute_combinations,
    compute_list_metrics,
    filter_reisift_cohort,
    is_excluded_list_token,
    list_metrics_from_scan,
    parse_report_month,
    prepare_reisift_cohort,
    resolve_combo_min_rows,
    row_has_closing_tag,
    row_has_sf_tag,
    scan_cohort,
    split_list_tokens,
    stackable_list_tokens,
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


def test_analysis_list_tokens_excludes_source_lists():
    raw = "8020 Source List, High Equity, PODIO (SOURCE), Default Risk"
    assert analysis_list_tokens(raw) == ["High Equity", "Default Risk"]
    assert is_excluded_list_token("8020 Source List")
    assert is_excluded_list_token("podio (source)")
    assert not is_excluded_list_token("High Equity")


def test_compute_list_metrics_ignores_excluded_lists():
    df = pd.DataFrame(
        [
            {
                "Lists": "8020 Source List, High Equity",
                "Tags": "(CLOSED) 8020 - 6/2025",
            },
            {
                "Lists": "PODIO (SOURCE)",
                "Tags": "(CLOSED) 8020 - 5/2025",
            },
        ]
    )
    metrics = compute_list_metrics(df, {})
    tokens = {m.token for m in metrics}
    assert "8020 Source List" not in tokens
    assert "PODIO (SOURCE)" not in tokens
    assert tokens == {"High Equity"}
    assert metrics[0].closing_count == 1


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
    combos, threshold = compute_combinations(cohort, min_rows=2)
    assert threshold == 2
    assert any(c.lists_key == "Default Risk + High Equity" for c in combos)


def test_hygiene_lists_fully_excluded():
    assert is_excluded_list_token("DNC + Dead Deals")
    assert is_excluded_list_token("Closings App MLSLI TBD")
    assert is_excluded_list_token("DNC")
    assert is_excluded_list_token("Closings App")
    assert is_excluded_list_token("MLSLI")
    assert is_excluded_list_token("Buyers (Investorbase)")
    assert is_excluded_list_token("Appraiva (Source List)")
    assert not is_excluded_list_token("High Equity")


def test_hygiene_lists_excluded_from_metrics_and_combos():
    df = pd.DataFrame(
        [
            {
                "Lists": "High Equity, DNC + Dead Deals",
                "Tags": "(8020) CC - 1/2025",
            },
            {
                "Lists": "High Equity, Default Risk, DNC, Dead Deals",
                "Tags": "(CLOSED) 8020 - 6/2025",
            },
            {
                "Lists": "High Equity, Default Risk, Closings App, MLSLI",
                "Tags": "(8020) SMS - 2/2025",
            },
            {
                "Lists": "Leads, DNC, Buyers (Investorbase)",
                "Tags": "(8020) DM - 3/2025",
            },
        ]
    )
    assert stackable_list_tokens(df.iloc[0]["Lists"]) == ["High Equity"]
    assert set(stackable_list_tokens(df.iloc[1]["Lists"])) == {
        "Default Risk",
        "High Equity",
    }
    metrics = compute_list_metrics(df, {})
    tokens = {m.token for m in metrics}
    assert "DNC" not in tokens
    assert "Dead Deals" not in tokens
    assert "Closings App" not in tokens
    assert "MLSLI" not in tokens
    assert "Buyers (Investorbase)" not in tokens
    combos, _ = compute_combinations(df, min_rows=2)
    for c in combos:
        assert "DNC" not in c.lists_key
        assert "Dead Deals" not in c.lists_key
        assert "Closings App" not in c.lists_key
        assert "MLSLI" not in c.lists_key
    assert any(c.lists_key == "Default Risk + High Equity" for c in combos)


def test_resolve_combo_min_rows_median():
    assert resolve_combo_min_rows([4, 10, 20, 100]) == 15
    assert resolve_combo_min_rows([3]) == 5  # floor
    assert resolve_combo_min_rows([]) == 10


def test_prepare_reisift_full_file():
    df = pd.read_csv(REISIFT)
    cohort, _, scope = prepare_reisift_cohort(df)
    assert scope == "full_file"
    assert len(cohort) == len(df)


def test_analyze_integration_month_optional():
    result = analyze(str(REISIFT), str(QL), "2025-03")
    assert result.cohort_rows == 4
    assert result.cohort_scope == "calendar_month"
    assert result.closing_rows == 2
    assert result.crm_lead_rows >= 2
    d = result.to_dict()
    assert d["report_month"] == "2025-03"
    assert len(d["lists"]) > 0


def test_analyze_full_file_default():
    result = analyze(str(REISIFT), str(QL))
    assert result.cohort_rows == 5
    assert result.cohort_scope == "full_file"
    assert result.report_month == "full_export"
    assert len(result.lists) > 0


def test_build_export_workbook():
    from app.services.monthly_consolidated import build_export_workbook

    result = analyze(str(REISIFT), str(QL), "2025-03")
    data = build_export_workbook(result)
    assert len(data) > 1000


def test_derive_tag_lead_source_from_contact():
    from app.services.monthly_consolidated import derive_tag_lead_source

    assert derive_tag_lead_source("(8020) CC - 1/2025") == "CC"
    assert derive_tag_lead_source("(8020) SMS - 2/2025") == "SMS"


def test_derive_tag_lead_source_list_fallback():
    from app.services.monthly_consolidated import derive_tag_lead_source

    assert derive_tag_lead_source("List Purchased 8020 1/2025") == "LIST"
    assert derive_tag_lead_source("") == "NONE"


def test_open_pipeline_stuck_at_stage():
    from app.services.monthly_consolidated import build_open_pipeline_lifecycle

    df = pd.DataFrame(
        [
            {"Tags": "(SF) STATUS - follow up - 2025-01-01", "Created": "2025-01-15"},
            {"Tags": "(CLOSED) 8020 - 6/2025", "Created": "2025-03-01"},
        ]
    )
    out = build_open_pipeline_lifecycle(df, "Created", pd.Timestamp("2025-06-01"))
    assert out["open_rows"] == 1
    assert out["stuck_at_stage"][0]["count"] == 1


def test_analyze_includes_tag_lead_source_and_open_pipeline():
    result = analyze(str(REISIFT), str(QL))
    assert len(result.tag_lead_source_counts) > 0
    assert result.open_pipeline_lifecycle.get("open_rows", 0) >= 0


def test_analyze_reports_progress_callbacks():
    steps: list[tuple[int, str]] = []

    def on_progress(pct: int, msg: str) -> None:
        steps.append((pct, msg))

    analyze(str(REISIFT), str(QL), "2025-03", on_progress=on_progress)
    assert len(steps) >= 5
    assert steps[0][0] < steps[-1][0]
    assert any("Scanning" in msg for _, msg in steps)


def test_scan_matches_legacy_list_and_combo_counts():
    df = pd.read_csv(REISIFT)
    cohort, _ = filter_reisift_cohort(df, date(2025, 3, 1), date(2025, 3, 31))
    scan = scan_cohort(cohort)
    lists = list_metrics_from_scan(scan, {"High Equity": 2})
    combos, _ = combinations_from_scan(scan, list_metrics=lists, min_rows=2)
    assert scan.crm_lead_rows == int(cohort["Tags"].apply(row_has_sf_tag).sum())
    assert scan.closing_rows == int(cohort["Tags"].apply(row_has_closing_tag).sum())
    assert any(c.lists_key == "Default Risk + High Equity" for c in combos)
