"""Regression tests for the approved Gate 7 geography universe."""
from pathlib import Path
import pytest

from app.services.buybox_towns import (
    BUYBOX_TOWN_COUNT, EXCLUDED_CITIES, evaluate_buybox, in_buybox, normalize_town,
)
from app.services.buybox_zips import EXCLUDED_ZIPS, in_buybox_zip, normalize_zip
from app.services.investor_sold import analyze

FIXTURES = Path(__file__).parent / "fixtures"


def check(city="Hempstead", zip_code="11550", county="Nassau", state="NY"):
    return evaluate_buybox(city, zip_code, county, state)


def test_exclusion_union_matches_approved_source():
    assert len(EXCLUDED_ZIPS) == 72
    assert len(EXCLUDED_CITIES) == 84
    assert {"westhampton", "west hampton", "westhampton beach", "west hampton beach", "e moriches"} <= EXCLUDED_CITIES
    assert {"11557", "11598", "11545", "11576", "11771"} <= EXCLUDED_ZIPS
    assert "james" in EXCLUDED_CITIES
    assert "saint james" not in EXCLUDED_CITIES


@pytest.mark.parametrize("zip_code", sorted(EXCLUDED_ZIPS))
def test_excluded_zip_cannot_be_rescued_by_city(zip_code):
    decision = check(city="Hempstead", zip_code=zip_code)
    assert not decision.included
    assert decision.reason == "excluded_zip"


@pytest.mark.parametrize("city", sorted(EXCLUDED_CITIES))
def test_excluded_city_is_only_used_without_zip(city):
    assert check(city=city, zip_code="").reason == "excluded_city"
    assert check(city=city, zip_code="11550").reason == "included_zip"


def test_missing_zip_city_fallback_is_not_old_positive_allowlist():
    assert check("Massapequa Pk", "").included
    assert check("Brookville", None).included
    assert check(" East   Moriches, ", "").reason == "excluded_city"
    assert check("", "").reason == "missing_city"
    assert check("Saint James", "").included
    assert check("Saint James", "11780").reason == "excluded_zip"


@pytest.mark.parametrize("county,state,reason", [
    ("Queens", "NY", "excluded_county"),
    ("Kings", "NY", "excluded_county"),
    ("Erie", "NY", "excluded_county"),
    ("", "NY", "excluded_county"),
    (None, "NY", "excluded_county"),
    ("Nassau", "FL", "excluded_state"),
    ("Suffolk", "MA", "excluded_state"),
    ("Nassau", "", "excluded_state"),
    ("Nassau", None, "excluded_state"),
])
def test_county_state_are_required_even_for_allowed_zip(county, state, reason):
    assert check(county=county, state=state).reason == reason


def test_county_state_normalization_and_wrapper():
    assert check(county=" Nassau County ", state="new york").included
    assert in_buybox("Coram", "11727", "Suffolk", "NY")
    assert not in_buybox("Hempstead", "11550")


@pytest.mark.parametrize("raw,expected", [
    ("11550", "11550"), ("11550-1234", "11550"), ("115501234", "11550"),
    ("11550.0", "11550"), (11550.0, "11550"), ("6390.0", "06390"),
    ("6390", "06390"), ("06390", "06390"), ("", None), (None, None),
    ("nan", None), ("abc", None), ("zip11550", None), ("115501", None),
    ("11550-abc", None), ("123", None), ("11550 extra", None),
])
def test_normalize_zip(raw, expected):
    assert normalize_zip(raw) == expected


@pytest.mark.parametrize("raw", ["nan", "abc", "zip11550", "115501", "11550-abc", "123"])
def test_malformed_nonblank_zip_cannot_fall_back(raw):
    decision = check(zip_code=raw)
    assert not decision.included
    assert decision.reason == "invalid_zip"


def test_zip_only_helper_requires_separate_county_scope():
    assert in_buybox_zip("11550")
    assert not in_buybox_zip("11968")
    assert not in_buybox_zip("")
    assert not in_buybox_zip("abc")


def test_town_normalization():
    assert normalize_town("  East Northport, ") == "east northport"
    assert normalize_town("Bay   Shore") == "bay shore"
    assert normalize_town(None) == ""


def test_analyze_excludes_non_buybox_cities(tmp_path):
    sold = tmp_path / "sold.csv"
    sold.write_text(
        "period_date,period_label,dataflik_id,transaction_id,parcel_number,buyer_full_name,"
        "property_address,property_city,property_zip,county,state,sale_amount,investor,"
        "in_my_records,investor_score,distressors,address_key\n"
        "2026-07-01,Jul 2026,1,t1,,Buyer,100 Main St,Hempstead,11550,Nassau,NY,250000,TRUE,FALSE,80,,main\n"
        "2026-07-01,Jul 2026,2,t2,,Buyer,200 Oak Ave,Buffalo,14201,Erie,NY,180000,TRUE,FALSE,10,,oak\n",
        encoding="utf-8",
    )
    result = analyze(
        str(sold),
        reisift_path=str(FIXTURES / "investor_sold_reisift.csv"),
        ql_path=str(FIXTURES / "investor_sold_ql.csv"),
    )
    assert result.sold_rows_scanned == 2
    assert result.sold_rows_excluded_buybox == 1
    assert result.sold_rows_ingested == 1
    assert result.buybox_excluded_zip_count == 72
    assert result.buybox_exclusions == {"excluded_county": 1}
    assert result.property_rows == 1
    assert result.rows[0].city == "Hempstead"
    assert "buybox" in result.methodology_note.lower()
    api = result.to_api_dict()["inputs"]
    assert api["sold_rows_scanned"] == 2
    assert api["sold_rows_excluded_buybox"] == 1


def test_analyze_includes_zip_matched_unlisted_city_spelling(tmp_path):
    sold = tmp_path / "sold.csv"
    sold.write_text(
        "period_date,period_label,dataflik_id,transaction_id,parcel_number,buyer_full_name,"
        "property_address,property_city,property_zip,county,state,sale_amount,investor,"
        "in_my_records,investor_score,distressors,address_key\n"
        "2026-07-01,Jul 2026,1,t1,,Buyer,100 Main St,Massapequa Pk,11758,Nassau,NY,250000,TRUE,FALSE,80,,main\n",
        encoding="utf-8",
    )
    result = analyze(
        str(sold),
        reisift_path=str(FIXTURES / "investor_sold_reisift.csv"),
        ql_path=str(FIXTURES / "investor_sold_ql.csv"),
    )
    assert result.sold_rows_excluded_buybox == 0
    assert result.property_rows == 1


