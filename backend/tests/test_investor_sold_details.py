import json
from copy import deepcopy

import pytest

from app.services import investor_sold_details as details


def target():
    return dict(key="df:1", dataflik_id="1", county="Nassau", state="NY",
                sold_month="2025-03", parcels=["12-34"],
                sale_events=[dict(buyer_full_name="Example Buyer LLC", sale_amount="500000")])


def record():
    return dict(dataflik_id="1", property=dict(apn="1234", county="Nassau County", state="NY",
                property_type="single_family_residence", years_built=2000,
                total_market_value=500000, living_square_feet=1000, lot_sqrf=4000),
                raw=dict(detail=dict(units_count=1)),
                history=dict(transactions=[dict(sale_date="2025-03-15", buyer_name="Example Buyer LLC",
                             sale_price=500000, seller_name="Jane Smith")]))


def run(tmp_path, records, targets=None):
    path = tmp_path / "details.jsonl"
    path.write_text("\n".join(json.dumps(r) for r in records), encoding="utf-8")
    return details.screen_property_details(str(path), targets or [target()])


def test_verified_identity_and_historical_seller(tmp_path):
    rec = record()
    rec["owner"] = {"name": "Wrong Current Owner LLC"}
    decisions, summary = run(tmp_path, [rec])
    assert decisions["df:1"]["status"] == "eligible"
    assert decisions["df:1"]["seller_name"] == "Jane Smith"
    assert decisions["df:1"]["seller_category"] == "Individual"
    assert summary["eligible"] == 1
    json.dumps(summary)


@pytest.mark.parametrize("field,value,reason", [
    ("apn", "wrong", "identity_mismatch"),
    ("county", "Suffolk", "identity_mismatch"),
    ("apn", "", "identity_missing"),
    ("state", "NJ", "identity_mismatch"),
])
def test_copied_source_ids_do_not_prove_identity(tmp_path, field, value, reason):
    rec = record()
    rec["parcel_number"] = "12-34"
    rec["property"][field] = value
    decision = run(tmp_path, [rec])[0]["df:1"]
    assert decision["status"] == "unresolved"
    assert decision["reason"] == reason
    assert decision["seller_name"] == ""


@pytest.mark.parametrize("field,value,status", [
    ("years_built", 2015, "eligible"), ("years_built", 2016, "excluded"),
    ("years_built", None, "eligible"),
    ("total_market_value", 999999, "eligible"), ("total_market_value", 1000000, "excluded"),
    ("living_square_feet", 199, "excluded"), ("living_square_feet", 200, "eligible"),
    ("living_square_feet", 0, "eligible"),
    ("lot_sqrf", 100, "excluded"), ("lot_sqrf", 101, "eligible"),
    ("property_type", "condo", "excluded"), ("property_type", "", "unresolved"),
    ("total_market_value", "broken", "unresolved"),
])
def test_sfh_boundaries(tmp_path, field, value, status):
    rec = record()
    rec["property"][field] = value
    assert run(tmp_path, [rec])[0]["df:1"]["status"] == status


@pytest.mark.parametrize("units,value,status", [(2, 400000, "eligible"), (9, 1499999, "eligible"),
    (10, 500000, "excluded"), (1, 500000, "excluded"), (None, 500000, "unresolved"),
    (2, 399999, "excluded"), (2, 1500000, "excluded"), (2, 0, "eligible"), (2, None, "eligible")])
def test_multifamily_boundaries(tmp_path, units, value, status):
    rec = record()
    rec["property"].update(property_type="multi_family_residential", total_market_value=value)
    rec["raw"]["detail"]["units_count"] = units
    assert run(tmp_path, [rec])[0]["df:1"]["status"] == status


@pytest.mark.parametrize("field,value", [("sale_date", "2025-04-01"), ("sale_price", 500001),
                                       ("buyer_name", "Other Buyer LLC")])
def test_all_three_sale_facts_required(tmp_path, field, value):
    rec = record()
    rec["history"]["transactions"][0][field] = value
    decision = run(tmp_path, [rec])[0]["df:1"]
    assert decision["seller_name"] == ""
    assert decision["seller_match_status"] == "sale_event_not_matched"


def test_ambiguous_historical_sellers(tmp_path):
    rec = record()
    other = deepcopy(rec["history"]["transactions"][0])
    other["seller_name"] = "Other Seller LLC"
    rec["history"]["transactions"].append(other)
    decision = run(tmp_path, [rec])[0]["df:1"]
    assert decision["seller_category"] == "Unclassified"
    assert decision["seller_match_status"] == "ambiguous_seller_events"


def test_same_seller_distinct_events_still_ambiguous(tmp_path):
    rec = record()
    other = deepcopy(rec["history"]["transactions"][0])
    other["sale_date"] = "2025-03-16"
    rec["history"]["transactions"].append(other)
    assert run(tmp_path, [rec])[0]["df:1"]["seller_match_status"] == "ambiguous_seller_events"


def test_exact_repeat_event_and_state_alias(tmp_path):
    rec = record()
    rec["property"]["state"] = "New York"
    rec["history"]["transactions"] *= 2
    assert run(tmp_path, [rec])[0]["df:1"]["seller_match_status"] == "matched_sale_history"


@pytest.mark.parametrize("name,category", [("Jane Family Trust", "Trust"), ("Jane Smith Trustee", "Trust"),
    ("Bank and Trust Company", "Company"), ("Acme LLC", "Company"), ("Estate of Jane Smith", "Company"),
    ("Jane Smith", "Individual"), ("Jane & John Smith", "Individual"), ("Unknown", "Unclassified"),
    ("Smith", "Unclassified"), ("Jane and", "Unclassified"), ("Acme L.L.C.", "Company"),
    ("Jane Smith EST", "Company"), ("Wilmington Savings Fund Society FSB", "Company"),
    ("SMITH JANE Q", "Individual"),
    ("", "Unclassified")])
def test_seller_categories_are_name_estimates(tmp_path, name, category):
    rec = record()
    rec["history"]["transactions"][0]["seller_name"] = name
    assert run(tmp_path, [rec])[0]["df:1"]["seller_category"] == category


def test_duplicate_conflict_is_order_independent(tmp_path):
    rec = record()
    other = deepcopy(rec)
    other["property"]["total_market_value"] = 600000
    for records in ([rec, other], [other, rec]):
        assert run(tmp_path, records)[0]["df:1"]["reason"] == "conflicting_duplicate_details"
    assert run(tmp_path, [rec, rec])[0]["df:1"]["status"] == "eligible"


def test_stream_handles_unrelated_malformed_oversize_and_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(details, "MAX_LINE_BYTES", 1000)
    rec = record()
    path = tmp_path / "details.jsonl"
    path.write_text('{"dataflik_id":"not-target", BAD}\n{bad}\n' + "x" * 1100 + "\n" + json.dumps(rec))
    absent = {**target(), "key": "df:2", "dataflik_id": "2"}
    decisions, summary = details.screen_property_details(str(path), [target(), absent])
    assert summary["scanned"] == 4
    assert summary["malformed_lines"] == 1
    assert summary["oversized_lines"] == 1
    assert decisions["df:1"]["status"] == "eligible"
    assert decisions["df:2"]["status"] == "unresolved"


def test_known_target_malformed_duplicate_cannot_preserve_eligible(tmp_path):
    path = tmp_path / "details.jsonl"
    path.write_text(json.dumps(record()) + '\n{"dataflik_id":"1", BAD}\n')
    decisions, _ = details.screen_property_details(str(path), [target()])
    assert decisions["df:1"]["status"] == "unresolved"
