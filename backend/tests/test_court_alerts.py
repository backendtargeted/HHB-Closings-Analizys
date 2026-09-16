"""Tests for Gate 6 Court Alerts lifecycle."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from app.services.court_alerts import (
    FIRST_SOURCE_8020_FIRST,
    FIRST_SOURCE_CA_FIRST,
    FIRST_SOURCE_CA_ONLY,
    FIRST_SOURCE_SAME,
    LAG_CREDIT_CA,
    LAG_CREDIT_EIGHT,
    LAG_CREDIT_SAME,
    analyze,
    build_export_workbook,
    classify_first_source,
    lag_credit_group,
    result_from_metrics_dict,
)

FIXTURES = Path(__file__).parent / "fixtures"


def _write_csv(path: Path, df: pd.DataFrame) -> str:
    df.to_csv(path, index=False)
    return str(path)


def test_classify_first_source_and_lag_credit():
    ca = pd.Timestamp("2025-04-01")
    eight = pd.Timestamp("2025-06-01")
    assert classify_first_source(ca, None) == FIRST_SOURCE_CA_ONLY
    assert classify_first_source(ca, eight) == FIRST_SOURCE_CA_FIRST
    assert classify_first_source(eight, ca) == FIRST_SOURCE_8020_FIRST
    assert classify_first_source(ca, pd.Timestamp("2025-04-15")) == FIRST_SOURCE_SAME
    assert lag_credit_group(FIRST_SOURCE_CA_ONLY) == LAG_CREDIT_CA
    assert lag_credit_group(FIRST_SOURCE_CA_FIRST) == LAG_CREDIT_CA
    assert lag_credit_group(FIRST_SOURCE_8020_FIRST) == LAG_CREDIT_EIGHT
    assert lag_credit_group(FIRST_SOURCE_SAME) == LAG_CREDIT_SAME


def test_analyze_court_alerts_fixture_files():
    result = analyze(
        str(FIXTURES / "court_alerts_sample.csv"),
        str(FIXTURES / "court_alerts_reisift_sample.csv"),
        str(FIXTURES / "court_alerts_ql_sample.csv"),
    )
    assert result.ca_universe == 3
    assert result.funnel["court_alerts"] == 3
    by_addr = {r.address_key: r for r in result.rows}

    maple = next(r for r in result.rows if "Maple" in r.address)
    assert maple.first_source == FIRST_SOURCE_CA_FIRST
    assert maple.ca_month == "2025-04"
    assert maple.eight_month == "2025-06"
    assert maple.prospect_matched is True
    assert maple.months_winner_to_prospect == 4  # Apr → Aug
    assert maple.county == "Nassau"

    oak = next(r for r in result.rows if "Oak" in r.address)
    assert oak.first_source == FIRST_SOURCE_8020_FIRST
    assert oak.ca_month == "2025-05"
    assert oak.eight_month == "2025-03"
    assert oak.prospect_matched is True
    assert oak.county == "Suffolk"

    pine = next(r for r in result.rows if "Pine" in r.address)
    assert pine.first_source == FIRST_SOURCE_CA_ONLY
    assert pine.prospect_matched is False
    assert result.crm_before_first_list_count == 1
    assert any("Pine" in r["address"] for r in result.crm_before_first_list)

    assert result.prospect_matched == 2
    assert result.funnel["prospect"] == 2
    assert any(r["key"] == FIRST_SOURCE_CA_FIRST for r in result.first_source)
    assert "ca" in (result.lag_by_source or {})
    assert by_addr  # nonempty

    restored = result_from_metrics_dict(result.to_api_dict())
    assert restored.ca_universe == 3
    assert restored.funnel["court_alerts"] == 3
    xlsx = build_export_workbook(result)
    assert len(xlsx) > 1000


def test_analyze_with_opps_and_txn(tmp_path):
    ca = _write_csv(
        tmp_path / "ca.csv",
        pd.DataFrame(
            [
                {
                    "address": "10 Maple St",
                    "city": "Freeport",
                    "state": "NY",
                    "zip_code": "11520",
                    "county_name": "Nassau",
                    "created_on": "2025-04-15",
                }
            ]
        ),
    )
    reisift = _write_csv(
        tmp_path / "reisift.csv",
        pd.DataFrame(
            [
                {
                    "Property address": "10 Maple St",
                    "Property city": "Freeport",
                    "Property state": "NY",
                    "Property zip": "11520",
                    "Phone 1": "5165550101",
                    "Tags": "List Purchased 8020 6/2025",
                }
            ]
        ),
    )
    ql = _write_csv(
        tmp_path / "ql.csv",
        pd.DataFrame(
            [
                {
                    "Street": "10 Maple St",
                    "City": "Freeport",
                    "State/Province": "NY",
                    "Zip/Postal Code": "11520",
                    "Phone": "5165550101",
                    "Campaign": "VA - Cold Calling (RES)",
                    "Create Date": "2025-08-15",
                }
            ]
        ),
    )
    opps = _write_csv(
        tmp_path / "opps.csv",
        pd.DataFrame(
            [
                {
                    "Address (Street)": "10 Maple St",
                    "Address (City)": "Freeport",
                    "Address (ZIP/Postal Code)": "11520",
                    "Created Date": "2025-09-01",
                }
            ]
        ),
    )
    txn = _write_csv(
        tmp_path / "txn.csv",
        pd.DataFrame(
            [
                {
                    "Address (Street)": "10 Maple St",
                    "Address (City)": "Freeport",
                    "Address (ZIP/Postal Code)": "11520",
                    "Closed Date": "2025-10-01",
                    "Primary Reason for Selling": "Foreclosure",
                    "Secondary Reason for Selling": "Divorce",
                }
            ]
        ),
    )
    result = analyze(ca, reisift, ql, opportunities_path=opps, transactions_path=txn)
    assert result.ca_universe == 1
    assert result.opp_matched == 1
    assert result.txn_matched == 1
    assert result.primary_reasons[0]["label"] == "Foreclosure"
    assert result.rows[0].txn_secondary_reason == "Divorce"
