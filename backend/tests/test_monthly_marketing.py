import csv

import pytest

from app.services.monthly_marketing import resolve_event_date, run_monthly_marketing, validate_reporting_month


def write(tmp_path, name, rows):
    path = tmp_path / name
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    return str(path)


def cold(date="9/3/2026", status="Decision Maker - Lead", phone="6315550100"):
    return {"Phone": phone, "Address": "100 Main St", "City": "Hempstead", "State": "NY",
            "Zip Code": "11550", "Log Type": status, "Log Time (Date)": date, "Log Time (Time)": "19:43:37"}


@pytest.mark.parametrize("value", ["2026-9", "2026-13", "", None, "0000-01", "2026-09-01"])
def test_month_required_and_strict(value):
    with pytest.raises(ValueError):
        validate_reporting_month(value)


def test_dates_authoritative_missing_month_precision_and_invalid_excluded(tmp_path):
    rows = [cold(), cold("8/31/2026"), {**cold("", phone="6315550101"), "Address": "200 Main St"}, cold("2/30/2026"), cold("NA")]
    result = run_monthly_marketing(write(tmp_path, "calls.csv", rows), [], "2026-09")
    source = result.stats["sources"][0]
    assert source == dict(source="calls.csv", channel="CC", input_rows=5, included_rows=2,
                          outside_month_rows=1, missing_date_rows=1, invalid_date_rows=2, duplicate_rows=0, unusable_identity_rows=0)
    assert result.cold_df.iloc[0].event_date == "2026-09-03"
    fallback = result.cold_df.iloc[1]
    assert fallback.event_date == ""
    assert fallback.date_precision == "month"
    assert fallback.date_source == "selected_month_fallback"
    assert set(result.marketing_tags_df.tag) == {"(MARKETING) CC - 9/2026"}
    assert len(result.review_df) == 3


def test_sms_real_phone1_row_labels_not_filename_and_conflicts_unresolved(tmp_path):
    base = {"First Name": "Jane", "Address": "100 Main St", "City": "Hempstead", "State": "NY", "Zip Code": "11550"}
    rows = [{**base, "Phone 1": "6315550100", "Labels": "Decision Maker|Not Interested"},
            {**base, "Phone 1": "6315550101", "Labels": "Wrong Number"},
            {**base, "Phone 1": "6315550102", "Labels": "Undefined"}]
    path = write(tmp_path, "Charles SMS Labels (2).csv", rows)
    result = run_monthly_marketing(None, [("Charles SMS Labels (2).csv", path)], "2026-09")
    # Both labels have the same documented phone disposition, so no chronological priority is invented.
    assert result.sms_df.iloc[0].phone_status == "CORRECT"
    assert result.sms_df.iloc[1].phone_status == "WRONG"
    assert result.sms_df.iloc[2].phone_status == ""
    assert result.sms_unmapped == ["undefined"]
    assert set(result.sms_df.date_source) == {"selected_month_fallback"}
    assert set(result.sms_df.event_date) == {""}
    assert result.stats["sources"][0]["missing_date_rows"] == 3
    assert set(result.marketing_tags_df.evidence_type) == {"sms_labels_snapshot"}


def test_conflicting_sms_phone_labels_have_no_silent_priority(tmp_path):
    path = write(tmp_path, "sms.csv", [{"Phone 1": "6315550100", "Labels": "Wrong Number|Decision Maker"}])
    result = run_monthly_marketing(None, [("sms.csv", path)], "2026-09")
    assert result.sms_df.iloc[0].phone_status == ""
    assert result.sms_df.iloc[0].row_validation_reason == "conflicting_status_labels"
    assert result.review_df.iloc[0].review_reason == "conflicting_status_labels"


def test_nyi_not_silently_promoted_to_lead(tmp_path):
    path = write(tmp_path, "calls.csv", [cold(status="Decision Maker - NYI")])
    result = run_monthly_marketing(path, [], "2026-09")
    assert result.cold_df.iloc[0].status == ""
    assert result.cold_unmapped == ["decision maker - nyi"]


def test_exact_duplicate_logs_do_not_inflate_counts(tmp_path):
    path = write(tmp_path, "calls.csv", [cold(), cold(), cold("9/4/2026")])
    result = run_monthly_marketing(path, [], "2026-09")
    assert result.stats["sources"][0]["duplicate_rows"] == 1
    assert result.stats["sources"][0]["included_rows"] == 2
    assert len(result.cold_df) == 1
    assert result.cold_df.iloc[0].event_date == "2026-09-04"
    assert len(result.marketing_tags_df) == 2


def test_legacy_sms_filename_supported_and_created_is_not_a_send_date(tmp_path):
    path = write(tmp_path, "sms.csv", [{"Phone": "6315550100", "Created": "2000-01-01"}])
    result = run_monthly_marketing(None, [("Wrong Number (6).csv", path)], "2026-09")
    assert result.sms_df.iloc[0].phone_status == "WRONG"
    assert result.sms_df.iloc[0].date_source == "selected_month_fallback"


def test_source_iso_date_preserves_local_calendar_day():
    event = resolve_event_date("2026-09-30T23:45:00-04:00", "2026-09", "Sent At")
    assert event["event_date"] == "2026-09-30"
    assert event["date_status"] == "valid"


def test_explicit_empty_mapping_remains_unmapped(tmp_path):
    path = write(tmp_path, "calls.csv", [cold()])
    result = run_monthly_marketing(path, [], "2026-09", property_mapping={})
    assert result.cold_df.iloc[0].status == ""


def test_all_outside_month_retains_empty_export_schema(tmp_path):
    path = write(tmp_path, "calls.csv", [cold("8/1/2026")])
    result = run_monthly_marketing(path, [], "2026-09")
    assert result.cold_df.empty
    assert "status" in result.cold_df.columns
    assert "tag" in result.marketing_tags_df.columns
    assert result.stats["tag_counts"] == {}


def test_latest_call_controls_status_regardless_of_input_order(tmp_path):
    rows = [cold("9/9/2026", status="Wrong Number"), cold("9/1/2026", status="Decision Maker - Lead")]
    result = run_monthly_marketing(write(tmp_path, "calls.csv", rows), [], "2026-09")
    assert list(result.cold_df.status) == ["Wrong Number"]
    assert len(result.marketing_tags_df) == 2


def test_unknown_latest_call_does_not_resurrect_older_lead(tmp_path):
    rows = [cold("9/1/2026"), cold("9/2/2026", status="Decision Maker - NYI")]
    result = run_monthly_marketing(write(tmp_path, "calls.csv", rows), [], "2026-09")
    assert list(result.cold_df.status) == [""]


def test_same_day_times_and_unresolved_ties(tmp_path):
    early = {**cold(status="Wrong Number"), "Log Time (Time)": "10:00:00"}
    late = {**cold(), "Log Time (Time)": "11:00:00"}
    result = run_monthly_marketing(write(tmp_path, "calls.csv", [late, early]), [], "2026-09")
    assert list(result.cold_df.status) == ["Lead"]
    result = run_monthly_marketing(write(tmp_path, "calls.csv", [late, {**early, "Log Time (Time)": "11:00:00"}]), [], "2026-09")
    assert list(result.cold_df.status) == [""]
    assert "conflicting_status_events" in set(result.review_df.review_reason)


def test_undated_sms_status_conflicts_do_not_use_file_order(tmp_path):
    path = write(tmp_path, "sms.csv", [{"Phone": "6315550100", "Labels": label} for label in ["Wrong Number", "Decision Maker"]])
    result = run_monthly_marketing(None, [("sms.csv", path)], "2026-09")
    assert list(result.sms_df.phone_status) == [""]
    assert "conflicting_status_events" in set(result.review_df.review_reason)


def test_sms_label_synonyms_and_untouched_rows(tmp_path):
    path = write(tmp_path, "sms.csv", [{"Phone": f"631555010{i}", "Labels": label} for i, label in enumerate(
        ["Do Not Call", "New Lead", "Undefined", "Agent Untouched Yet", "No Label"])])
    result = run_monthly_marketing(None, [("sms.csv", path)], "2026-09")
    assert result.sms_df.iloc[0].phone_status == "DNC"
    assert result.sms_df.iloc[1].phone_status == "CORRECT"
    assert len(result.marketing_tags_df) == 2
    assert list(result.review_df.review_reason).count("no_sms_activity_evidence") == 3
