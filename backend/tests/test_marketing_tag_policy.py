import pytest

from app.services.marketing_tag_policy import resolve_labels, validate_mappings
from app.services.monthly_marketing import run_monthly_marketing
from tests.test_monthly_marketing import cold, write


@pytest.mark.parametrize("channel", ["CC", "SMS"])
@pytest.mark.parametrize("label,property_status,phone_status,tags", [
    ("Wrong Number", "Follow Up", "Wrong", {"Wrong Number"}),
    ("Voicemail", "Follow Up", "No Answer", {"Voicemail"}),
    ("No Answer", "Follow Up", "No Answer", set()),
    ("Disconnected", "Follow Up", "Dead", set()),
    ("Decision Maker - NYI", "Follow Up", "Correct", {"Correct", "Contacted"}),
    ("Not Interested", "Follow Up", "Correct", {"Contacted"}),
    ("DNC - Decision Maker", "dnc", "Correct DNC", {"DNC"}),
    ("DNC - Unknown", "", "DNC", {"DNC"}),
])
def test_approved_rules_apply_to_each_channel(tmp_path, channel, label, property_status, phone_status, tags):
    row = cold(status=label) if channel == "CC" else {"Phone": "6315550100", "Labels": label}
    path = write(tmp_path, "input.csv", [row])
    result = run_monthly_marketing(path if channel == "CC" else None,
                                   [("input.csv", path)] if channel == "SMS" else [], "2026-09")
    assert result.property_df.iloc[0].status == property_status
    assert result.phone_df.iloc[0].phone_status == phone_status
    assert set(filter(None, result.phone_df.iloc[0].phone_tag.split(","))) == tags


def test_known_evidence_survives_unknown_label_and_other_target_conflicts():
    result = resolve_labels(["decision maker", "not interested", "fu1"])
    assert result["status"] == ""
    assert result["phone_status"] == "Correct"
    assert set(result["phone_tag"].split(",")) == {"Correct", "Contacted"}
    assert result["unmapped_phone_labels"] == "fu1"
    assert resolve_labels(["sold"])["status"] == "sold"
    assert resolve_labels(["sold"])["phone_status"] == ""


def test_optout_survives_conflicting_labels():
    result = resolve_labels(["dnc - decision maker", "wrong number"])
    assert result["status"] == "dnc"
    assert result["phone_status"] == "DNC"
    assert result["phone_tag"] == "DNC"


def test_optout_survives_later_activity(tmp_path):
    path = write(tmp_path, "calls.csv", [cold("9/1/2026", "DNC - Decision Maker"), cold("9/2/2026", "Wrong Number")])
    result = run_monthly_marketing(path, [], "2026-09")
    assert list(result.property_df.status) == ["dnc"]
    assert list(result.phone_df.phone_status) == ["Wrong DNC"]


def test_one_property_with_two_distinct_phone_updates(tmp_path):
    path = write(tmp_path, "calls.csv", [cold(status="Voicemail"), cold(status="Wrong Number", phone="6315550101")])
    result = run_monthly_marketing(path, [], "2026-09")
    assert list(result.property_df.status) == ["Follow Up"]
    assert set(result.phone_df.phone_status) == {"No Answer", "Wrong"}


def test_unmapped_property_does_not_block_phone(tmp_path):
    path = write(tmp_path, "calls.csv", [cold()])
    result = run_monthly_marketing(path, [], "2026-09", property_mapping={})
    assert list(result.property_df.status) == [""]
    assert list(result.phone_df.phone_status) == ["Correct"]
    assert set(result.review_df.review_target) == {"property"}


@pytest.mark.parametrize("properties,phones", [({"x": "follow_up"}, {}), ({}, {"x": ("CORRECT", "")}), ({}, {"x": ("Dead", "Dead Number")})])
def test_invalid_account_values_are_rejected(properties, phones):
    with pytest.raises(ValueError):
        validate_mappings(properties, phones)
