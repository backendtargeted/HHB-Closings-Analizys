"""Tests for Gate 4 Web Leads report."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from app.services.web_leads import (
    analyze,
    compute_web_journey_path,
    result_from_metrics_dict,
)
from app.services.lifecycle import build_events


FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _write_reisift(tmp_path: Path) -> str:
    df = pd.DataFrame(
        [
            {
                "Property address": "100 Main St",
                "Property city": "Springfield",
                "Property state": "NY",
                "Property zip": "11772",
                "Created on": "2025-05-20",
                "Lists": "High Equity,Default Risk",
                "Tags": (
                    "List Purchased 8020 1/2025,"
                    "(8020) CC - 2/2025,"
                    "(SF) STATUS - New - 2025-05-18"
                ),
            },
            {
                "Property address": "200 Oak Ave",
                "Property city": "Springfield",
                "Property state": "NY",
                "Property zip": "11772",
                "Created on": "2025-05-22",
                "Lists": "Absentee",
                "Tags": "(SF) STATUS - New - 2025-05-21",
            },
        ]
    )
    path = tmp_path / "reisift.csv"
    df.to_csv(path, index=False)
    return str(path)


def _write_ql(tmp_path: Path) -> str:
    df = pd.DataFrame(
        [
            {
                "Street": "100 Main St",
                "City": "Springfield",
                "State": "NY",
                "Zip": "11772",
                "Lead Source": "Website",
                "Create Date": "2025-05-21",
            },
            {
                "Street": "200 Oak Ave",
                "City": "Springfield",
                "State": "NY",
                "Zip": "11772",
                "Lead Source": "Website",
                "Create Date": "2025-05-22",
            },
            {
                "Street": "999 Unknown Rd",
                "City": "Nowhere",
                "State": "NY",
                "Zip": "11772",
                "Lead Source": "Website",
                "Create Date": "2025-05-23",
            },
        ]
    )
    path = tmp_path / "ql.csv"
    df.to_csv(path, index=False)
    return str(path)


def test_compute_web_journey_path():
    parsed = [
        {"type": "list_purchase", "date": "2025-01-01", "precision": "month", "label": "LIST", "tag": ""},
        {"type": "contact", "date": "2025-02-01", "channel": "CC", "precision": "month", "label": "CC", "tag": ""},
    ]
    events = build_events(parsed)
    path = compute_web_journey_path(events, pd.Timestamp("2025-05-20"))
    assert path == "LIST -> CC -> WEB"


def test_analyze_web_leads_prior_history(tmp_path):
    reisift = _write_reisift(tmp_path)
    ql = _write_ql(tmp_path)
    result = analyze(reisift, ql, use_full_file_span=True)

    assert result.website_ql_total == 3
    assert result.matched_count == 2
    assert result.unmatched_count == 1
    assert result.prior_history_count == 1
    assert result.new_to_db_count == 1

    matched_rows = [r for r in result.rows if r.matched]
    prior_row = next(r for r in matched_rows if r.address.startswith("100"))
    assert prior_row.had_prior_history is True
    assert prior_row.days_list_to_web is not None
    assert prior_row.days_list_to_web > 0
    assert "CC" in prior_row.prior_8020_channels
    assert prior_row.journey_path.endswith("WEB")

    new_row = next(r for r in matched_rows if r.address.startswith("200"))
    assert new_row.had_prior_history is False

    assert len(result.top_paths) >= 1
    assert result.combinations == [] or all(c["row_count"] >= 3 for c in result.combinations)


def test_result_roundtrip():
    result = result_from_metrics_dict(
        {
            "date_window_start": "2025-05-01",
            "date_window_end": "2025-05-31",
            "inputs": {"reisift_rows_ingested": 10, "website_ql_total": 2},
            "match": {"matched": 2, "unmatched": 0, "match_rate_pct": 100.0},
            "prior_history": {
                "count": 1,
                "share_pct": 50.0,
                "new_to_db_count": 1,
                "new_to_db_pct": 50.0,
            },
            "top_lists": [],
            "combinations": [],
            "top_paths": [],
            "age_buckets": [],
            "rows": [
                {
                    "address": "100 Main",
                    "address_key": "k",
                    "ql_create_date": "2025-05-21",
                    "reisift_created_on": "2025-05-20",
                    "anchor_date": "2025-05-20",
                    "lists": ["High Equity"],
                    "combo_key": "",
                    "had_prior_history": True,
                    "earliest_list_date": "2025-01-01",
                    "days_list_to_web": 139,
                    "prior_8020_channels": ["CC"],
                    "journey_path": "LIST -> CC -> WEB",
                    "matched": True,
                }
            ],
            "warnings": [],
            "methodology_note": "test",
        }
    )
    assert result.matched_count == 2
    assert len(result.rows) == 1
