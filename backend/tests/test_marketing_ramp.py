"""Tests for marketing ramp report service."""

from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from app.services.marketing_ramp import (
    NO_CLEAR_SOURCE,
    analyze_files,
    load_closings_file,
)

FIXTURES = Path(__file__).parent / "fixtures"
MR_FIXTURES = FIXTURES / "marketing_ramp"


@pytest.fixture
def mr_paths(tmp_path):
    """Minimal QL, REISift, and closings fixtures with explicit address columns."""
    ql = pd.DataFrame(
        {
            "Lead Source": ["Cold Calling", "Direct Mail", "SEO"],
            "Create Date": ["2025-03-10", "2025-03-15", "2025-03-20"],
            "Street": ["100 Main St", "500 Maple Dr", "600 Lost Ave"],
            "City": ["Springfield", "Springfield", "Springfield"],
            "State/Province": ["NY", "NY", "NY"],
            "Zip/Postal Code": ["11772", "11772", "11772"],
        }
    )
    reisift = pd.DataFrame(
        {
            "Property address": [
                "100 Main St",
                "500 Maple Dr",
                "200 Oak Ave",
            ],
            "Property city": ["Springfield", "Springfield", "Springfield"],
            "Property state": ["NY", "NY", "NY"],
            "Property zip": ["11772", "11772", "11772"],
            "Created": ["2025-03-01", "2025-03-01", "2025-03-01"],
            "Lists": ["High Equity", "High Equity", "High Equity"],
            "Tags": [
                "List Purchased 8020 1/2025,(8020) CC - 2/2025",
                "List Purchased 8020 2/2025,(SF) UPDATED - converted - 2025-03-16,(8020) SMS - 3/2025",
                "List Purchased 8020 1/2025,(8020) DM - 2/2025",
            ],
        }
    )
    closings = pd.DataFrame(
        {
            "Street": ["200 Oak Ave", "600 Lost Ave", "700 Closed Lost St"],
            "City": ["Springfield", "Springfield", "Springfield"],
            "State": ["NY", "NY", "NY"],
            "Zip": ["11772", "11772", "11772"],
            "Date Closed": ["2025-06-01", "2025-06-15", "2025-06-20"],
            "Stage": ["Closed", "Closed Won", "Closed Lost"],
        }
    )

    ql_path = tmp_path / "ql.csv"
    reisift_path = tmp_path / "reisift.csv"
    closings_path = tmp_path / "closings.xlsx"
    ql.to_csv(ql_path, index=False)
    reisift.to_csv(reisift_path, index=False)
    closings.to_excel(closings_path, index=False)
    return str(ql_path), str(reisift_path), str(closings_path)


def test_merge_population_kinds(mr_paths):
    ql_path, reisift_path, closings_path = mr_paths
    result = analyze_files(
        ql_path,
        reisift_path,
        closings_path,
        start_date=date(2025, 3, 1),
        end_date=date(2025, 6, 30),
    )
    rows = {r["address_key"]: r for r in result.rows}
    kinds = {r["population_kind"] for r in result.rows}
    assert "both" in kinds
    assert "qualified_only" in kinds
    assert "closing_only" in kinds
  # 100 Main St: QL only (no closing)
    main_key = "100 main st|springfield|ny|11772"
    assert rows[main_key]["population_kind"] == "qualified_only"
  # 500 Maple: QL + would need closing - only QL in our fixture
    maple_key = "500 maple dr|springfield|ny|11772"
    assert rows[maple_key]["population_kind"] == "qualified_only"
  # 200 Oak: closing only
    oak_key = "200 oak ave|springfield|ny|11772"
    assert rows[oak_key]["population_kind"] == "closing_only"
    assert rows[oak_key]["reporting_channel"] == NO_CLEAR_SOURCE
    assert rows[oak_key]["create_date"] == ""
  # 600 Lost: QL + closing -> both
    lost_key = "600 lost ave|springfield|ny|11772"
    assert rows[lost_key]["population_kind"] == "both"


def test_touch_from_tags_not_lists(mr_paths):
    ql_path, reisift_path, closings_path = mr_paths
    result = analyze_files(
        ql_path,
        reisift_path,
        closings_path,
        start_date=date(2025, 3, 1),
        end_date=date(2025, 6, 30),
    )
    main = next(r for r in result.rows if "100 main" in r["address_key"])
    assert main["first_touch_channel"] == "CC"
    assert main["cc_touch_count"] == 1
    assert main["sms_touch_count"] == 0
    assert main["days_list_to_first_touch"] == 31  # Jan 1 -> Feb 1 (month granularity)

    oak = next(r for r in result.rows if "200 oak" in r["address_key"])
    assert oak["first_touch_channel"] == "DM"
    assert result.metrics["touch_counts"]["DM"] >= 1


def test_converted_only_for_under_contract(mr_paths):
    ql_path, reisift_path, closings_path = mr_paths
    result = analyze_files(
        ql_path,
        reisift_path,
        closings_path,
        start_date=date(2025, 3, 1),
        end_date=date(2025, 6, 30),
    )
    maple = next(r for r in result.rows if "500 maple" in r["address_key"])
    assert maple["date_under_contract"] == "2025-03-16"
    assert result.metrics["opportunity_counts"]["under_contract"] >= 1

    main = next(r for r in result.rows if "100 main" in r["address_key"])
    assert main["date_under_contract"] == ""


def test_closed_lost_excluded_from_population(mr_paths):
    ql_path, reisift_path, closings_path = mr_paths
    result = analyze_files(
        ql_path,
        reisift_path,
        closings_path,
        start_date=date(2025, 3, 1),
        end_date=date(2025, 6, 30),
    )
    keys = [r["address_key"] for r in result.rows]
    assert not any("700 closed lost" in k for k in keys)
    assert result.metrics["population_counts"]["closings_in_window"] == 2


def test_no_clear_source_closing_only(mr_paths):
    ql_path, reisift_path, closings_path = mr_paths
    result = analyze_files(
        ql_path,
        reisift_path,
        closings_path,
        start_date=date(2025, 3, 1),
        end_date=date(2025, 6, 30),
    )
    closing_only = [r for r in result.rows if r["population_kind"] == "closing_only"]
    assert len(closing_only) >= 1
    for row in closing_only:
        assert row["reporting_channel"] == NO_CLEAR_SOURCE
        assert row["create_date"] == ""


def test_report_anchor_and_duration_columns(mr_paths):
    ql_path, reisift_path, closings_path = mr_paths
    end = date(2025, 6, 30)
    result = analyze_files(
        ql_path,
        reisift_path,
        closings_path,
        start_date=date(2025, 3, 1),
        end_date=end,
    )
    main = next(r for r in result.rows if "100 main" in r["address_key"])
    assert main["report_anchor_date"] == "2025-06-30"
    assert main["list_purchase_date"] == "2025-01-01"
    assert main["days_since_list_to_anchor"] is not None
    assert main["days_list_to_create_date"] is not None


def test_closings_workbook_close_preferred(mr_paths):
    ql_path, reisift_path, closings_path = mr_paths
    result = analyze_files(
        ql_path,
        reisift_path,
        closings_path,
        start_date=date(2025, 3, 1),
        end_date=date(2025, 6, 30),
    )
    lost = next(r for r in result.rows if "600 lost" in r["address_key"])
    assert lost["date_closed"] == "2025-06-15"
    assert lost["close_date_source"] == "closings_workbook"


def test_load_closings_xlsx(mr_paths):
    _, _, closings_path = mr_paths
    df = load_closings_file(closings_path)
    assert len(df) == 3
