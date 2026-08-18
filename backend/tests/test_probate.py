"""Tests for Gate 5 probate lifecycle."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from app.services.probate import (
    FIRST_SOURCE_8020_FIRST,
    FIRST_SOURCE_LIP_FIRST,
    FIRST_SOURCE_LIP_ONLY,
    FIRST_SOURCE_SAME,
    LOCKED_PROBATE_TAGS,
    analyze,
    classify_first_source,
    first_probate_hit,
    months_between,
    normalize_campaign,
    parse_8020_list_purchase_date,
    parse_probate_tags,
    result_from_metrics_dict,
    row_has_probate_tag,
)


def _write_csv(path: Path, df: pd.DataFrame) -> str:
    df.to_csv(path, index=False)
    return str(path)


def test_parse_probate_tags_hyphen_and_leading_zero():
    tags = "Probates NY Nassau 02-2025,Probates NY Suffolk 1-2026,(8020) CC - 3/2025"
    hits = parse_probate_tags(tags)
    assert [h["county"] for h in hits] == ["Nassau", "Suffolk"]
    assert hits[0]["date"] == pd.Timestamp("2025-02-01")
    assert hits[1]["date"] == pd.Timestamp("2026-01-01")
    assert row_has_probate_tag(tags) is True
    assert row_has_probate_tag("List Purchased 8020 2/2025") is False
    assert parse_probate_tags("Probates NY County 3-2025") == []
    assert parse_probate_tags("Probates NY Nassau 03/2025") == []
    assert len(LOCKED_PROBATE_TAGS) == 38
    assert "Probates NY Nassau 02-2025" not in LOCKED_PROBATE_TAGS
    assert "Probates NY Nassau 03-2025" not in LOCKED_PROBATE_TAGS
    assert "Probates NY Nassau 3-2026" in LOCKED_PROBATE_TAGS
    assert "Probates NY Queens 3-2026" in LOCKED_PROBATE_TAGS
    assert row_has_probate_tag("Probates NY Nassau 02-2025") is False
    assert row_has_probate_tag("Probates NY Nassau 3-2026") is True
    assert all(parse_probate_tags(tag) for tag in LOCKED_PROBATE_TAGS)
    assert row_has_probate_tag("Probates NY Nassau 11-2025") is False
    assert parse_probate_tags("Probates NY Nassau 11-2025") != []
    mixed = "Probates NY Nassau 01-2024,Probates NY Nassau 05-2025"
    assert first_probate_hit(mixed)["date"] == pd.Timestamp("2025-05-01")


def test_parse_8020_list_purchase_not_contact_tags():
    assert parse_8020_list_purchase_date("List Purchased 8020 3/2025") == pd.Timestamp(
        "2025-03-01"
    )
    combined = "List Purchased 1/2025,(8020)"
    assert parse_8020_list_purchase_date(combined) == pd.Timestamp("2025-01-01")
    contact_only = "List Purchased 1/2025,(8020) CC - 2/2025"
    assert parse_8020_list_purchase_date(contact_only) is None
    assert parse_8020_list_purchase_date("Probates NY Nassau 02-2025") is None


def test_normalize_campaign_blank_and_smarter_contact():
    assert normalize_campaign("") == "No Campaign in Salesforce"
    assert normalize_campaign(None) == "No Campaign in Salesforce"
    assert normalize_campaign("(blank)") == "No Campaign in Salesforce"
    assert normalize_campaign("Smarter Contact 1 - RES") == "RES SMS"
    assert normalize_campaign("Smarter Contact 1-RES") == "RES SMS"
    assert normalize_campaign("smarter contact 1 – RES") == "RES SMS"
    assert normalize_campaign("VA - Cold Calling (RES)") == "VA - Cold Calling (RES)"


def test_first_source_and_lag_math():
    lip = pd.Timestamp("2025-02-01")
    eight = pd.Timestamp("2025-04-01")
    assert classify_first_source(lip, None) == FIRST_SOURCE_LIP_ONLY
    assert classify_first_source(lip, eight) == FIRST_SOURCE_LIP_FIRST
    assert classify_first_source(eight, lip) == FIRST_SOURCE_8020_FIRST
    assert classify_first_source(lip, pd.Timestamp("2025-02-15")) == FIRST_SOURCE_SAME
    assert months_between(lip, pd.Timestamp("2025-08-20")) == 6
    assert months_between(lip, pd.Timestamp("2025-02-28")) == 0
    assert months_between(pd.Timestamp("2025-06-01"), pd.Timestamp("2025-02-01")) == -4


def test_analyze_first_source_match_and_txn_reasons(tmp_path):
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
                    "Tags": "Probates NY Nassau 04-2025,List Purchased 8020 6/2025",
                },
                {
                    "Property address": "20 Oak Ave",
                    "Property city": "Patchogue",
                    "Property state": "NY",
                    "Property zip": "11772",
                    "Phone 1": "",
                    "Tags": "List Purchased 8020 3/2025,Probates NY Suffolk 05-2025",
                },
                {
                    "Property address": "30 Pine Rd",
                    "Property city": "Hicksville",
                    "Property state": "NY",
                    "Property zip": "11801",
                    "Phone 1": "5165550999",
                    "Tags": "Probates NY Nassau 04-2025",
                },
                {
                    "Property address": "40 Elm St",
                    "Property city": "Queens",
                    "Property state": "NY",
                    "Property zip": "11354",
                    "Phone 1": "",
                    "Tags": "List Purchased 8020 2/2025,(8020) CC - 3/2025",
                },
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
                    "Lead Source": "Cold Calling",
                    "Campaign": "VA - Cold Calling (RES)",
                    "Create Date": "2025-08-15",
                    "Primary Reason for Selling": "Should not be used",
                },
                {
                    "Street": "20 Oak Ave",
                    "City": "Patchogue",
                    "State/Province": "NY",
                    "Zip/Postal Code": "11772",
                    "Phone": "",
                    "Lead Source": "Direct Mail",
                    "Campaign": "Check Mailer (In-House)",
                    "Create Date": "2025-04-01",
                    "Primary Reason for Selling": "Should not be used",
                },
                {
                    "Street": "30 Pine Rd",
                    "City": "Hicksville",
                    "State/Province": "NY",
                    "Zip/Postal Code": "11801",
                    "Phone": "5165550999",
                    "Lead Source": "PPC",
                    "Campaign": "PPC - Google",
                    "Create Date": "2025-01-15",
                    "Primary Reason for Selling": "Should not be used",
                },
                {
                    "Street": "99 Missing Ln",
                    "City": "Nowhere",
                    "State/Province": "NY",
                    "Zip/Postal Code": "11111",
                    "Phone": "5165550000",
                    "Lead Source": "SMS",
                    "Create Date": "2025-03-01",
                    "Primary Reason for Selling": "Estate",
                },
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
                    "Primary Reason for Selling": "Opp reason ignored",
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
                    "Address (ZIP/Postal Code)": "11520-1234",
                    "Closed Date": "2025-10-02",
                    "Primary Reason for Selling": "Estate",
                    "Secondary Reason for Selling": "Tired Landlord",
                }
            ]
        ),
    )

    result = analyze(reisift, ql, opps, txn)
    assert result.reisift_rows_ingested == 4
    assert result.lip_universe == 3
    assert result.prospect_matched == 2
    assert result.crm_before_first_list_count == 1
    assert result.opp_matched == 1
    assert result.txn_matched == 1
    assert result.funnel["lip"] == 3
    assert result.funnel["transaction"] == 1

    maple = next(r for r in result.rows if r.address.startswith("10 Maple"))
    assert maple.first_source == FIRST_SOURCE_LIP_FIRST
    assert maple.prospect_source == FIRST_SOURCE_LIP_FIRST
    assert maple.ql_campaign == "VA - Cold Calling (RES)"
    assert maple.county == "Nassau"
    assert maple.months_lip_to_prospect == 4
    assert maple.txn_primary_reason == "Estate"
    assert maple.txn_secondary_reason == "Tired Landlord"

    oak = next(r for r in result.rows if r.address.startswith("20 Oak"))
    assert oak.first_source == FIRST_SOURCE_8020_FIRST
    assert oak.prospect_matched is True
    assert oak.prospect_source == FIRST_SOURCE_8020_FIRST
    assert oak.months_lip_to_prospect == -1
    assert oak.months_eight_to_prospect == 1
    assert oak.months_winner_to_prospect == 1

    pine = next(r for r in result.rows if r.address.startswith("30 Pine"))
    assert pine.first_source == FIRST_SOURCE_LIP_ONLY
    assert pine.prospect_matched is False
    assert pine.prospect_source == ""
    assert pine.ql_campaign == ""
    assert pine.months_lip_to_prospect is None
    assert any(item["address"].startswith("30 Pine") for item in result.crm_before_first_list)
    assert all(item["label"] != "PPC - Google" for item in result.campaigns)
    assert any(item["label"] == "VA - Cold Calling (RES)" for item in result.campaigns)

    assert all(not r.address.startswith("40 Elm") for r in result.rows)
    assert any(item["label"] == "Estate" for item in result.primary_reasons)
    assert any(item["label"] == "Tired Landlord" for item in result.secondary_reasons)
    assert all(item["label"] != "Should not be used" for item in result.primary_reasons)
    assert all(item["label"] != "Opp reason ignored" for item in result.primary_reasons)


def test_phone_fallback_and_same_month(tmp_path):
    reisift = _write_csv(
        tmp_path / "reisift.csv",
        pd.DataFrame(
            [
                {
                    "Property address": "",
                    "Property city": "",
                    "Property state": "NY",
                    "Property zip": "",
                    "Phone 1": "6315552222",
                    "Tags": "Probates NY Suffolk 02-2025,List Purchased 8020 2/2025",
                }
            ]
        ),
    )
    ql = _write_csv(
        tmp_path / "ql.csv",
        pd.DataFrame(
            [
                {
                    "Street": "Hidden",
                    "City": "Islip",
                    "State/Province": "NY",
                    "Zip/Postal Code": "11751",
                    "Phone": "16315552222",
                    "Lead Source": "Direct Mail",
                    "Campaign": "Postcard Offer (75%)",
                    "Create Date": "2025-02-10",
                }
            ]
        ),
    )
    result = analyze(reisift, ql)
    assert result.lip_universe == 1
    row = result.rows[0]
    assert row.first_source == FIRST_SOURCE_SAME
    assert row.prospect_matched is True
    assert row.prospect_match_via == "phone"
    assert row.prospect_source == FIRST_SOURCE_SAME
    assert row.months_lip_to_prospect == 0


def test_result_roundtrip():
    result = result_from_metrics_dict(
        {
            "date_window_start": "2025-02-01",
            "date_window_end": "2026-08-01",
            "inputs": {"reisift_rows_ingested": 10, "lip_universe": 2},
            "match": {
                "prospect_matched": 1,
                "prospect_rate_pct": 50.0,
                "opp_matched": 0,
                "opp_rate_pct": 0.0,
                "txn_matched": 0,
                "txn_rate_pct": 0.0,
            },
            "lag": {
                "mean_months_lip_to_prospect": 4.0,
                "median_months_lip_to_prospect": 4.0,
            },
            "first_source": [],
            "counties": [],
            "cohorts": [],
            "lag_buckets": [],
            "funnel": {"lip": 2, "prospect": 1, "opportunity": 0, "transaction": 0},
            "primary_reasons": [],
            "secondary_reasons": [],
            "rows": [
                {
                    "address": "10 Maple",
                    "address_key": "k",
                    "county": "Nassau",
                    "counties": ["Nassau"],
                    "lip_month": "2025-02",
                    "eight_month": "",
                    "first_source": FIRST_SOURCE_LIP_ONLY,
                    "first_source_label": "LIP only",
                    "prospect_date": "2025-06-01",
                    "prospect_matched": True,
                    "prospect_match_via": "address",
                    "months_lip_to_prospect": 4,
                    "months_eight_to_prospect": None,
                    "months_winner_to_prospect": 4,
                    "lag_bucket": "4-6 months",
                    "opp_matched": False,
                    "opp_created_date": "",
                    "txn_matched": False,
                    "txn_closed_date": "",
                    "txn_primary_reason": "",
                    "txn_secondary_reason": "",
                    "tags": "Probates NY Nassau 02-2025",
                }
            ],
            "warnings": [],
            "methodology_note": "test",
        }
    )
    assert result.lip_universe == 2
    assert len(result.rows) == 1
    assert result.rows[0].county == "Nassau"


def test_unlocked_probate_tag_excluded_from_universe(tmp_path):
    reisift = _write_csv(
        tmp_path / "reisift.csv",
        pd.DataFrame(
            [
                {
                    "Property address": "1 Old St",
                    "Property city": "Freeport",
                    "Property state": "NY",
                    "Property zip": "11520",
                    "Phone 1": "",
                    "Tags": "Probates NY Nassau 11-2025",
                },
                {
                    "Property address": "2 New St",
                    "Property city": "Freeport",
                    "Property state": "NY",
                    "Property zip": "11520",
                    "Phone 1": "",
                    "Tags": "Probates NY Nassau 01-2024,Probates NY Nassau 05-2025",
                },
            ]
        ),
    )
    ql = _write_csv(
        tmp_path / "ql.csv",
        pd.DataFrame(
            [
                {
                    "Street": "2 New St",
                    "City": "Freeport",
                    "State/Province": "NY",
                    "Zip/Postal Code": "11520",
                    "Phone": "",
                    "Lead Source": "Cold Calling",
                    "Campaign": "VA - Cold Calling (RES)",
                    "Create Date": "2025-06-01",
                }
            ]
        ),
    )
    result = analyze(reisift, ql)
    assert result.lip_universe == 1
    assert result.rows[0].address.startswith("2 New")
    assert result.rows[0].lip_month == "2025-05"
    assert result.rows[0].prospect_matched is True
    assert result.rows[0].months_winner_to_prospect == 1


def test_early_and_later_ql_uses_on_or_after_create_date(tmp_path):
    reisift = _write_csv(
        tmp_path / "reisift.csv",
        pd.DataFrame(
            [
                {
                    "Property address": "30 Pine Rd",
                    "Property city": "Hicksville",
                    "Property state": "NY",
                    "Property zip": "11801",
                    "Phone 1": "5165550999",
                    "Tags": "Probates NY Nassau 04-2025",
                }
            ]
        ),
    )
    ql = _write_csv(
        tmp_path / "ql.csv",
        pd.DataFrame(
            [
                {
                    "Street": "30 Pine Rd",
                    "City": "Hicksville",
                    "State/Province": "NY",
                    "Zip/Postal Code": "11801",
                    "Phone": "5165550999",
                    "Lead Source": "PPC",
                    "Campaign": "PPC - Google",
                    "Create Date": "2025-01-15",
                },
                {
                    "Street": "30 Pine Rd",
                    "City": "Hicksville",
                    "State/Province": "NY",
                    "Zip/Postal Code": "11801",
                    "Phone": "5165550999",
                    "Lead Source": "Cold Calling",
                    "Campaign": "VA - Cold Calling (RES)",
                    "Create Date": "2025-06-10",
                },
            ]
        ),
    )
    result = analyze(reisift, ql)
    row = result.rows[0]
    assert row.prospect_matched is True
    assert row.prospect_source == FIRST_SOURCE_LIP_ONLY
    assert row.ql_campaign == "VA - Cold Calling (RES)"
    assert row.prospect_date == "2025-06-10"
    assert row.months_winner_to_prospect == 2
    assert result.crm_before_first_list_count == 0
    assert all(item["label"] != "PPC - Google" for item in result.campaigns)


def test_campaign_smarter_contact_rollup_and_blank(tmp_path):
    reisift = _write_csv(
        tmp_path / "reisift.csv",
        pd.DataFrame(
            [
                {
                    "Property address": "10 A St",
                    "Property city": "Freeport",
                    "Property state": "NY",
                    "Property zip": "11520",
                    "Phone 1": "",
                    "Tags": "Probates NY Nassau 04-2025",
                },
                {
                    "Property address": "20 B St",
                    "Property city": "Freeport",
                    "Property state": "NY",
                    "Property zip": "11521",
                    "Phone 1": "",
                    "Tags": "Probates NY Nassau 04-2025",
                },
                {
                    "Property address": "30 C St",
                    "Property city": "Freeport",
                    "Property state": "NY",
                    "Property zip": "11522",
                    "Phone 1": "",
                    "Tags": "Probates NY Nassau 04-2025",
                },
            ]
        ),
    )
    ql = _write_csv(
        tmp_path / "ql.csv",
        pd.DataFrame(
            [
                {
                    "Street": "10 A St",
                    "City": "Freeport",
                    "State/Province": "NY",
                    "Zip/Postal Code": "11520",
                    "Campaign": "Smarter Contact 1 - RES",
                    "Create Date": "2025-05-01",
                },
                {
                    "Street": "20 B St",
                    "City": "Freeport",
                    "State/Province": "NY",
                    "Zip/Postal Code": "11521",
                    "Campaign": "Smarter Contact 1-RES",
                    "Create Date": "2025-05-01",
                },
                {
                    "Street": "30 C St",
                    "City": "Freeport",
                    "State/Province": "NY",
                    "Zip/Postal Code": "11522",
                    "Campaign": "",
                    "Create Date": "2025-05-01",
                },
            ]
        ),
    )
    result = analyze(reisift, ql)
    assert result.prospect_matched == 3
    labels = {item["label"]: item["count"] for item in result.campaigns}
    assert labels["RES SMS"] == 2
    assert labels["No Campaign in Salesforce"] == 1
    assert all("Smarter Contact" not in (item["label"] or "") for item in result.campaigns)
