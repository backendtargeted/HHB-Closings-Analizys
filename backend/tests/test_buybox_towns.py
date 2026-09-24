"""Tests for Gate 7 marketed-town buybox."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.services.buybox_towns import BUYBOX_TOWN_COUNT, in_buybox, normalize_town
from app.services.buybox_zips import in_buybox_zip, normalize_zip
from app.services.investor_sold import analyze

FIXTURES = Path(__file__).parent / "fixtures"


def test_normalize_town_strips_and_casefolds():
    assert normalize_town("  East Northport, ") == "east northport"
    assert normalize_town("FRANKLIN SQUAR") == "franklin squar"
    assert normalize_town("Bay   Shore") == "bay shore"
    assert normalize_town("") == ""
    assert normalize_town(None) is not None and normalize_town(None) == ""


def test_in_buybox_allowlist_and_aliases():
    assert in_buybox("Hempstead") is True
    assert in_buybox("hempstead") is True
    assert in_buybox("Bay Shore") is True
    assert in_buybox("bayshore") is True
    assert in_buybox("E Farmingdale") is True
    assert in_buybox("N babylon") is True
    assert in_buybox("Buffalo") is False
    assert in_buybox("Albany") is False
    assert in_buybox("") is False
    assert BUYBOX_TOWN_COUNT >= 200


def test_in_buybox_removed_and_added_towns():
    # Removed 2026-09-23: confirmed suppressed (or shared-zip risk) in docs/BUYBOX_8020REI.md S13.
    for town in (
        "East Marion", "East Moriches", "E Moriches", "Eastport",
        "Lloyd Harbor", "Southold", "Westhampton Beach", "Brookville",
    ):
        assert in_buybox(town) is False, town
    # Added 2026-09-23: evidenced by nonzero 8020REI buybox score, not suppressed.
    for town in ("Captree Island", "Port Washington North", "Davis Park", "Oyster Bay Cove"):
        assert in_buybox(town) is True, town


def test_normalize_zip():
    assert normalize_zip("11550") == "11550"
    assert normalize_zip("11550-1234") == "11550"
    assert normalize_zip("11550.0") == "11550"
    assert normalize_zip("6390.0") == "06390"
    assert normalize_zip("6390") == "06390"
    assert normalize_zip("06390") == "06390"
    assert normalize_zip("") is None
    assert normalize_zip(None) is None
    assert normalize_zip("nan") is None
    assert normalize_zip("abc") is None


def test_in_buybox_zip():
    assert in_buybox_zip("11550") is True
    assert in_buybox_zip("11758") is True
    assert in_buybox_zip("11545") is False  # not on the flat zip allowlist
    assert in_buybox_zip("14201") is False  # Buffalo
    assert in_buybox_zip("") is False
    assert in_buybox_zip("abc") is False


def test_in_buybox_zip_recovers_unlisted_city_spelling():
    assert in_buybox("Massapequa Pk") is False  # town-only still fails
    assert in_buybox("Massapequa Pk", "11758") is True  # zip recovers it


def test_in_buybox_either_list_matching_is_enough():
    assert in_buybox("Hempstead", "not-a-zip") is True  # town matches, zip doesn't
    assert in_buybox("Not A Real Town", "11550") is True  # zip matches, town doesn't
    assert in_buybox("Buffalo", "14201") is False  # neither matches


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
    assert result.buybox_town_count == BUYBOX_TOWN_COUNT
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


