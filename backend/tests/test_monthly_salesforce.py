from datetime import datetime

import pandas as pd
import pytest

from app.services.analysis import parse_tags
from app.services.closing_resolution import resolve_milestones_from_parsed
from app.services.lifecycle import build_events, compute_stage_funnel_open
from app.services.monthly_salesforce import build_monthly_salesforce


def run(tmp_path, ql=None, opp=None, txn=None, month="2026-08"):
    frames = {
        "ql_path": pd.DataFrame(ql if ql is not None else [], columns=["Street", "City", "State/Province", "Zip/Postal Code", "Phone", "Create Date", "Created Date/Time", "Lead Status"]),
        "opportunities_path": pd.DataFrame(opp if opp is not None else [], columns=["Address (Street)", "Address (City)", "Address (ZIP/Postal Code)", "Created Date", "Close Date", "Stage", "Opportunity Owner: Phone"]),
        "transactions_path": pd.DataFrame(txn if txn is not None else [], columns=["Address (Street)", "Address (State/Province)", "Address (ZIP/Postal Code)", "Date Contract Signed", "Date Contract Signed (MLS)", "Closed Date", "Path", "Date of Accepted Offer", "Scheduled Closing"]),
    }
    paths = {}
    for name, frame in frames.items():
        path = tmp_path / f"{name}.xlsx"
        frame.to_excel(path, index=False)
        paths[name] = str(path)
    return build_monthly_salesforce(month, **paths)


def test_creation_dates_do_not_backdate_present_status(tmp_path):
    result = run(tmp_path,
        ql=[{"Street": "1 Main St", "Create Date": "2026-08-03", "Lead Status": "Converted"}],
        opp=[{"Address (Street)": "2 Main St", "Created Date": "2026-08-04", "Close Date": "2026-08-20", "Stage": "Closed Lost"}])
    assert set(result.tags.salesforce_tag) == {"(SF) STATUS - New - 2026-08-03", "(SF) UPDATED - Opportunity - 2026-08-04"}
    assert not any("Converted" in tag or "Lost" in tag for tag in result.tags.salesforce_tag)
    assert any("not a qualification" in warning for warning in result.summary["warnings"])
    parsed = parse_tags(result.tags.iloc[1].salesforce_tag)
    assert parsed[0]["label"] == "Opportunity"
    assert parsed[0]["date"] == "2026-08-04T00:00:00"
    assert compute_stage_funnel_open(build_events(parsed), pd.Timestamp("2026-08-31"))["ENGAGED"]["reached"]


def test_exact_source_days_and_real_close_grammar(tmp_path):
    result = run(tmp_path, txn=[{"Address (Street)": "1 Main St", "Path": "Wholesale Closed",
        "Date Contract Signed": datetime(2026, 8, 9), "Closed Date": datetime(2026, 8, 29)}])
    assert list(result.tags.event_date) == ["2026-08-09", "2026-08-29"]
    assert list(result.tags.salesforce_tag) == ["(SF) UPDATED - Under Contract - 2026-08-09", "(CLOSED) 8020 - 8/2026"]
    parsed = parse_tags(",".join(result.tags.salesforce_tag))
    milestones = resolve_milestones_from_parsed(parsed)
    assert milestones.date_under_contract == datetime(2026, 8, 9)
    assert milestones.date_closed == datetime(2026, 8, 1)  # existing closing token has month precision
    assert result.events.iloc[1].event_date == "2026-08-29"


@pytest.mark.parametrize("path", ["Dead", "Closing Scheduled", "Under Contract", ""])
def test_planned_or_dead_transaction_not_closed(tmp_path, path):
    result = run(tmp_path, txn=[{"Address (Street)": "1 Main St", "Path": path,
        "Closed Date": "2026-08-20", "Scheduled Closing": "2026-08-20", "Date of Accepted Offer": "2026-08-10"}])
    assert result.tags.empty
    assert result.summary["sources"][2]["unverified_closing_rows"] == 1


def test_prior_signed_contract_still_real_when_deal_now_dead(tmp_path):
    result = run(tmp_path, txn=[{"Address (Street)": "1 Main St", "Path": "Dead",
        "Date Contract Signed": "2026-08-08", "Closed Date": "2026-08-20"}])
    assert list(result.events.event_kind) == ["under_contract"]
    assert "closed_date_without_closed_path" in set(result.review.reason)


def test_month_boundaries_missing_invalid_and_duplicates(tmp_path):
    ql = [{"Street": "1 Main St", "Create Date": date} for date in
          ["2026-07-31", "2026-08-01", "2026-08-31", "2026-09-01", "", "bad", "2026-08-01"]]
    result = run(tmp_path, ql=ql)
    stats = result.summary["sources"][0]
    assert stats["input_rows"] == 7
    assert stats["included_rows"] == 2
    assert stats["outside_month_rows"] == 2
    assert stats["missing_date_rows"] == 1
    assert stats["invalid_date_rows"] == 1
    assert stats["duplicate_rows"] == 1
    assert set(result.tags.event_date) == {"2026-08-01", "2026-08-31"}


def test_alias_priority_does_not_pick_date_just_to_fit_month(tmp_path):
    result = run(tmp_path, ql=[{"Street": "1 Main St", "Create Date": "2026-07-31",
                              "Created Date/Time": "2026-08-01"}])
    assert result.tags.empty
    assert result.summary["sources"][0]["outside_month_rows"] == 1


def test_missing_date_alias_can_use_real_timestamp(tmp_path):
    result = run(tmp_path, ql=[{"Street": "1 Main St", "Created Date/Time": "2026-08-31T23:30:00-04:00"}])
    assert list(result.tags.event_date) == ["2026-08-31"]
    assert list(result.tags.date_source) == ["Created Date/Time"]


def test_invalid_authoritative_date_does_not_fall_through(tmp_path):
    result = run(tmp_path, ql=[{"Street": "1 Main St", "Create Date": "bad",
                              "Created Date/Time": "2026-08-01"}])
    assert result.tags.empty
    assert result.summary["sources"][0]["invalid_date_rows"] == 1
    assert "invalid_authoritative_creation_date" in set(result.review.reason)


def test_wrong_report_role_rejected(tmp_path):
    wrong = tmp_path / "wrong.xlsx"
    pd.DataFrame([{"Street": "1 Main St", "Created Date": "2026-08-01", "Stage": "Closed"}]).to_excel(wrong, index=False)
    with pytest.raises(ValueError, match="wrong report role"):
        build_monthly_salesforce("2026-08", ql_path=str(wrong), opportunities_path=str(wrong), transactions_path=str(wrong))


def test_employee_phone_never_used_for_property(tmp_path):
    result = run(tmp_path, opp=[{"Created Date": "2026-08-02", "Opportunity Owner: Phone": "2125550100"}])
    assert result.tags.empty
    assert result.summary["sources"][1]["unusable_identity_rows"] == 1


def test_distinct_phone_only_leads_do_not_collapse(tmp_path):
    result = run(tmp_path, ql=[{"Phone": phone, "Create Date": "2026-08-01"} for phone in ["2125550100", "2125550101"]])
    assert len(result.tags) == 2
    assert set(result.tags.address_key) == {""}


def test_duplicate_milestone_columns_but_distinct_days_preserved(tmp_path):
    result = run(tmp_path, txn=[{"Address (Street)": "1 Main St", "Date Contract Signed": "2026-08-01",
        "Date Contract Signed (MLS)": "2026-08-01", "Closed Date": "2026-08-20", "Path": "Closed"},
        {"Address (Street)": "1 Main St", "Date Contract Signed": "2026-08-02", "Path": "Dead"}])
    assert len(result.tags) == 3
    assert list(result.events.event_date) == ["2026-08-01", "2026-08-20", "2026-08-02"]


def test_excel_zip_zero_padding_and_serial_date(tmp_path):
    result = run(tmp_path, ql=[{"Street": "1 Main St", "Zip/Postal Code": 501,
        "Create Date": (datetime(2026, 8, 4) - datetime(1899, 12, 30)).days}])
    assert result.tags.iloc[0]["zip"] == "00501"
    assert result.tags.iloc[0].event_date == "2026-08-04"


@pytest.mark.parametrize("month", ["2026-13", "2026-1", "today", "2026-00"])
def test_invalid_month_rejected(month):
    with pytest.raises(ValueError, match="YYYY-MM"):
        build_monthly_salesforce(month, ql_path="a.xlsx", opportunities_path="b.xlsx", transactions_path="c.xlsx")


def test_all_sources_required():
    with pytest.raises(ValueError, match="required"):
        build_monthly_salesforce("2026-08", ql_path="", opportunities_path="a.xlsx", transactions_path="b.xlsx")
