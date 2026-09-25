"""Tests for Gate 7 investor & in-list sold + pipeline depth."""

from __future__ import annotations

from pathlib import Path
from io import BytesIO

import pytest
import pandas as pd

from app.services.investor_sold import (
    InvestorSoldRow,
    analyze,
    build_export_workbook,
    is_never_prospected_investor,
    result_from_metrics_dict,
    segment_for,
    collapse_property_month_rows,
)

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def sale_case(tmp_path):
    """One July investor sale; REISift starts with an unrelated property."""
    sold = pd.DataFrame([{
        "property_address": "999 Nowhere Rd", "property_city": "Hempstead",
        "state": "NY", "county": "Nassau", "property_zip": "11550", "period_date": "2026-07-01",
        "investor": "TRUE", "in_my_records": "FALSE",
    }])
    reisift = pd.DataFrame([{
        "Property address": "1 Other St", "Property city": "Hempstead",
        "Property state": "NY", "Property zip": "11550", "Tags": "",
        "Lists": "", "Created": "",
    }])
    ql = pd.DataFrame(columns=["Street", "City", "State/Province", "Zip/Postal Code", "Create Date"])

    def run(opps=None, details=None):
        paths = {}
        for name, frame in (("sold", sold), ("reisift", reisift), ("ql", ql)):
            path = tmp_path / f"{name}.csv"
            frame.to_csv(path, index=False)
            paths[name] = str(path)
        opps_path = None
        if opps is not None:
            opps_path = str(tmp_path / "opps.csv")
            opps.to_csv(opps_path, index=False)
        return analyze(paths["sold"], paths["reisift"], paths["ql"], opps_path,
                       property_details_path=details)

    return sold, reisift, ql, run


def test_details_screen_before_enrichment_and_persist_audit(sale_case, tmp_path, monkeypatch):
    import json
    from io import BytesIO
    from app.services import investor_sold as service

    sold, _, _, run = sale_case
    sold.loc[0, ["dataflik_id", "parcel_number", "buyer_full_name", "sale_amount"]] = [
        "pass", "100-1", "Buyer LLC", "500000",
    ]
    for identity, parcel in (("excluded", "200"), ("wrong", "300"), ("missing", "400")):
        row = sold.iloc[0].copy()
        row["dataflik_id"], row["parcel_number"] = identity, parcel
        sold.loc[len(sold)] = row
    later = sold.iloc[0].copy()
    later["period_date"], later["buyer_full_name"] = "2026-08-01", "Later Buyer LLC"
    sold.loc[len(sold)] = later
    payload = []
    for identity, apn, kind in (("pass", "1001", "single_family_residence"),
                                ("excluded", "200", "condo"),
                                ("wrong", "not-300", "single_family_residence")):
        payload.append({"dataflik_id": identity,
                        "property": {"apn": apn, "county": "Nassau", "property_type": kind},
                        "history": {"transactions": [{"sale_date": "2026-07-15",
                            "buyer_name": "Buyer LLC", "sale_price": 500000,
                            "seller_name": "Example Family Trust"}]}})
    details = tmp_path / "details.jsonl"
    details.write_text("\n".join(json.dumps(p) for p in payload), encoding="utf-8")
    enriched = []
    original = service._enrich_row

    def capture(row, **kwargs):
        enriched.append(row.dataflik_id)
        return original(row, **kwargs)

    monkeypatch.setattr(service, "_enrich_row", capture)
    result = run(details=str(details))
    assert enriched == ["pass"]
    assert result.sold_rows_ingested == 5
    assert result.property_rows == 1
    assert result.rows[0].sold_month == "2026-07"
    assert result.rows[0].seller_category == "Trust"
    assert result.rows[0].seller_name == "Example Family Trust"
    assert result.property_screening["target_count"] == 4
    assert result.property_screening["excluded"] == 1
    assert result.property_screening["unresolved"] == 2
    assert len(result.property_screening_rows) == 4
    assert sum(m["count"] for m in result.by_sold_month) == 1
    restored = result_from_metrics_dict(result.to_api_dict())
    assert restored.to_api_dict() == result.to_api_dict()
    workbook = pd.ExcelFile(BytesIO(build_export_workbook(restored)))
    assert len(pd.read_excel(workbook, "Property Screening")) == 4
    assert pd.read_excel(workbook, "Journey").iloc[0]["seller_category"] == "Trust"


def test_no_details_is_explicit_geographic_only(sale_case):
    *_, run = sale_case
    result = run()
    assert result.property_screening["enabled"] is False
    assert any("geography-only" in w for w in result.warnings)


@pytest.mark.parametrize("crm_kind", ["ql", "opportunity"])
def test_crm_only_property_reaches_pipeline_and_counts_loss(sale_case, crm_kind):
    _, _, ql, run = sale_case
    opps = None
    if crm_kind == "ql":
        ql.loc[0] = ["999 Nowhere Rd", "Hempstead", "NY", "11550", "2026-06-15"]
    else:
        opps = pd.DataFrame([{
            "Address (Street)": "999 Nowhere Rd", "Address (City)": "Hempstead",
            "Address (State/Province)": "NY", "Address (ZIP/Postal Code)": "11550",
            "Stage": "Offer Made", "Created Date": "2026-06-15",
        }])
    result = run(opps)
    row = result.rows[0]
    assert row.reisift_matched is False
    assert row.pipeline_stage == ("QUALIFIED_LEAD" if crm_kind == "ql" else "OPPORTUNITY")
    assert row.had_presence is True
    assert result.lost_to_investor_count == 1


def test_scrape_only_presence_reaches_prospect(sale_case):
    sold, _, _, run = sale_case
    sold.loc[0, "in_my_records"] = "TRUE"
    result = run()
    assert result.rows[0].pipeline_stage == "PROSPECT"
    assert result.rows[0].never_prospected_investor is False
    assert next(s["count"] for s in result.pipeline_funnel if s["stage"] == "PROSPECT") == 1


@pytest.mark.parametrize("created,tags,lists", [
    ("2026-08-01", "List Purchased 8020 8/2026", "8020 Absentee"),
    ("2026-08-01", "PodioSellerLeads", "LI Profiles"),
    ("", "List Purchased 8020 8/2026", "8020 Absentee"),
])
def test_post_sale_reisift_presence_does_not_count_as_loss(sale_case, created, tags, lists):
    _, reisift, _, run = sale_case
    reisift.loc[0, ["Property address", "Created", "Tags", "Lists"]] = [
        "999 Nowhere Rd", created, tags, lists,
    ]
    result = run()
    row = result.rows[0]
    assert row.reisift_matched is True
    assert row.reisift_present_at_sale is False
    assert row.had_presence is False
    assert row.pipeline_stage == "NONE"
    assert row.never_prospected_investor is True
    assert result.had_presence_count == result.lost_to_investor_count == 0
    # Export reconstruction must not restore presence just because the address matched.
    restored = result_from_metrics_dict(result.to_api_dict())
    assert restored.rows[0].had_presence is False
    assert restored.rows[0].reisift_present_at_sale is False


def test_later_import_preserves_pre_sale_dated_history(sale_case):
    _, reisift, _, run = sale_case
    reisift.loc[0, ["Property address", "Created", "Tags"]] = [
        "999 Nowhere Rd", "2026-08-01", "List Purchased 8020 6/2026",
    ]
    result = run()
    assert result.rows[0].pipeline_stage == "PROSPECT"
    assert result.rows[0].had_presence is True
    assert result.rows[0].never_prospected_investor is False
    assert result.lost_to_investor_count == 1


@pytest.mark.parametrize("period", ["", "invalid"])
def test_missing_or_invalid_sold_month_rejected(sale_case, period):
    sold, _, _, run = sale_case
    sold.loc[0, "period_date"] = period
    with pytest.raises(ValueError, match="Sold row 1.*missing or invalid sold month"):
        run()


def test_valid_period_label_can_rescue_invalid_period_date(sale_case):
    sold, _, _, run = sale_case
    sold.loc[0, "period_date"] = "invalid"
    sold.loc[0, "period_label"] = "Jul 2026"
    assert run().rows[0].sold_month == "2026-07"


@pytest.mark.parametrize("reverse", [False, True])
def test_property_once_at_earliest_sale_without_later_evidence(sale_case, reverse):
    sold, reisift, ql, run = sale_case
    sold["dataflik_id"] = "property-1"
    sold["transaction_id"] = "late"
    sold["buyer_full_name"] = "Later Buyer"
    sold["in_my_records"] = "TRUE"
    sold.loc[1] = sold.iloc[0].copy()
    sold.loc[1, ["period_date", "transaction_id", "investor", "in_my_records", "buyer_full_name"]] = [
        "2026-02-01", "early", "FALSE", "FALSE", "Earlier Buyer",
    ]
    if reverse:
        sold.iloc[:] = sold.iloc[::-1].to_numpy()
    reisift.loc[0, ["Property address", "Created", "Tags"]] = [
        "999 Nowhere Rd", "2026-03-01", "List Purchased 8020 3/2026",
    ]
    ql.loc[0] = ["999 Nowhere Rd", "Hempstead", "NY", "11550", "2026-04-15"]
    result = run()
    assert result.sold_rows_ingested == 2
    assert result.property_rows == 1
    row = result.rows[0]
    assert row.sold_month == "2026-02"
    assert row.last_sold_month == "2026-07"
    assert row.transaction_count == 2
    assert row.buyer_full_name == "Earlier Buyer"
    assert row.investor is False
    assert row.in_my_records is False
    assert row.had_presence is False
    assert row.qualified_lead_matched is False
    assert row.pipeline_stage == "NONE"
    assert result.investor_count == result.lost_to_investor_count == 0
    assert [r["sold_month"] for r in result.by_sold_month] == ["2026-02"]
    assert sum(r["count"] for r in result.by_sold_month) == result.property_rows
    restored = result_from_metrics_dict(result.to_api_dict())
    assert restored.rows[0].last_sold_month == "2026-07"
    assert restored.property_grain == "property_earliest_sale"


def test_transaction_duplicates_and_same_month_buyers_are_order_independent():
    first = InvestorSoldRow(dataflik_id="1", sold_month="2026-02", transaction_id="a", buyer_full_name="Buyer A", sale_amount="100", investor=True)
    second = InvestorSoldRow(dataflik_id="1", sold_month="2026-02", transaction_id="b", buyer_full_name="Buyer B", sale_amount="200")
    later = InvestorSoldRow(dataflik_id="1", sold_month="2026-07", transaction_id="c", buyer_full_name="Later Buyer", in_my_records=True)
    rows = [first, second, later, first]
    forward = collapse_property_month_rows(rows)
    backward = collapse_property_month_rows(list(reversed(rows)))
    assert forward[0].to_dict() == backward[0].to_dict()
    assert forward[0].transaction_count == 3
    assert forward[0].buyer_full_name == "Buyer A; Buyer B"
    assert forward[0].sale_amount == ""  # Multiple amounts, no arbitrary price.
    assert forward[0].in_my_records is False
    assert first.transaction_count == 1  # Inputs were not mutated.


def test_unambiguous_missing_property_id_can_join_but_conflicting_ids_cannot():
    missing = InvestorSoldRow(address_key="1 main|hempstead|ny|11550", sold_month="2026-02", transaction_id="early")
    known = InvestorSoldRow(dataflik_id="1", address_key=missing.address_key, sold_month="2026-07", transaction_id="late")
    rows = collapse_property_month_rows([known, missing])
    assert len(rows) == 1
    assert rows[0].dataflik_id == "1"
    assert rows[0].sold_month == "2026-02"
    conflict = InvestorSoldRow(dataflik_id="2", address_key=missing.address_key, sold_month="2026-06")
    assert len(collapse_property_month_rows([known, missing, conflict])) == 3


def test_geography_exclusion_precedes_dedup_and_metrics(sale_case):
    sold, _, _, run = sale_case
    sold["dataflik_id"] = "1"
    sold.loc[1] = sold.iloc[0].copy()
    sold.loc[1, ["period_date", "property_zip"]] = ["2026-02-01", "11743"]
    result = run()
    assert result.sold_rows_scanned == 2
    assert result.sold_rows_excluded_buybox == 1
    assert result.buybox_exclusions == {"excluded_zip": 1}
    assert result.property_rows == result.sold_rows_ingested == 1
    assert result.rows[0].sold_month == "2026-07"


@pytest.fixture
def sold_path():
    return str(FIXTURES / "investor_sold_transactions.csv")


@pytest.fixture
def reisift_path():
    return str(FIXTURES / "investor_sold_reisift.csv")


@pytest.fixture
def ql_path():
    return str(FIXTURES / "investor_sold_ql.csv")


@pytest.fixture
def sf_txn_path():
    return str(FIXTURES / "investor_sold_transactions_sf.csv")


def test_segment_for_matrix():
    assert segment_for(True, True) == "both"
    assert segment_for(True, False) == "investor"
    assert segment_for(False, True) == "in_our_list"
    assert segment_for(False, False) == "neither"


def test_requires_reisift_and_ql(sold_path):
    with pytest.raises(ValueError, match="REISift"):
        analyze(sold_path)
    with pytest.raises(ValueError, match="Qualified Leads"):
        analyze(sold_path, reisift_path=str(FIXTURES / "investor_sold_reisift.csv"))


def test_segment_counts_and_pipeline(sold_path, reisift_path, ql_path):
    result = analyze(sold_path, reisift_path=reisift_path, ql_path=ql_path)
    # 6 CSV txns; Main St has 2 txns same dataflik+month → 5 property rows
    assert result.sold_rows_ingested == 6
    assert result.sold_rows_scanned == 6
    assert result.sold_rows_excluded_buybox == 0
    assert result.buybox_excluded_zip_count == 72
    assert result.property_grain == "property_earliest_sale"
    assert result.property_rows == 5
    assert len(result.rows) == 5
    assert result.unique_addresses == 5
    assert result.investor_count == 3  # main, pine, cedar
    assert result.in_our_list_count == 2  # oak, pine
    assert result.both_count == 1  # pine
    assert result.neither_count == 1  # elm
    assert result.date_window_start == "2026-05"
    assert result.date_window_end == "2026-07"
    assert result.enrichment_enabled is True

    by_street = {r.street.lower(): r for r in result.rows}
    assert by_street["100 main st"].transaction_count == 2
    assert by_street["100 main st"].marketed is True
    assert by_street["100 main st"].cc_touch_count >= 1
    assert by_street["200 oak ave"].prospect_matched is True
    assert by_street["200 oak ave"].lead_matched is True
    assert by_street["200 oak ave"].lead_source == "podio"
    assert by_street["200 oak ave"].prospect_source == "podio"
    assert by_street["200 oak ave"].pipeline_stage == "LEAD"
    assert by_street["300 pine rd"].segment == "both"
    assert by_street["300 pine rd"].qualified_lead_matched is True
    assert by_street["300 pine rd"].prospect_matched is True
    assert by_street["300 pine rd"].prospect_source == "ql"
    assert by_street["300 pine rd"].marketed is True
    assert by_street["300 pine rd"].pipeline_stage in (
        "QUALIFIED_LEAD",
        "OPPORTUNITY",
        "HHB_CLOSED",
    )
    assert by_street["400 elm st"].reisift_matched is False
    assert by_street["400 elm st"].marketed is False

    assert result.marketed_count >= 2
    assert result.lead_matched >= 1
    assert result.qualified_lead_matched >= 1
    assert result.prospect_matched >= 2
    assert result.prospect_sources["podio"] >= 1
    assert result.prospect_sources["ql"] >= 1
    assert result.lead_sources["podio"] >= 1
    # Lost = we had it (list/CRM) + investor + not closed (main, pine, cedar)
    assert result.had_presence_count == 4  # elm has neither scrape nor REISift
    assert result.lost_to_investor_count == 3
    assert result.lost_to_investor_pct == 75.0
    # Primary KPI: never prospected = investor + not closed + no 8020/CA/LIP (cedar only)
    assert result.never_prospected_investor_count == 1
    assert result.never_prospected_investor_pct == pytest.approx(33.3, abs=0.1)
    assert by_street["500 cedar ln"].never_prospected_investor is True
    assert by_street["100 main st"].never_prospected_investor is False
    assert by_street["100 main st"].had_presence is True
    assert by_street["500 cedar ln"].had_presence is True
    assert by_street["400 elm st"].had_presence is False
    assert result.had_presence_investor_count >= 3
    assert result.lost_by_stage
    lost_api = result.to_api_dict()["lost"]
    assert lost_api["never_prospected_investor_count"] == 1
    assert lost_api["lost_to_investor_count"] == 3
    assert any(s["segment"] == "in_our_list" and s["prospects_podio"] >= 1 for s in result.by_segment)
    assert result.pipeline_funnel
    funnel = {r["stage"]: r["count"] for r in result.pipeline_funnel}
    # Cumulative: Prospect >= Marketed (Marketed rows also count as reached Prospect).
    if "PROSPECT" in funnel and "MARKETED" in funnel:
        assert funnel["PROSPECT"] >= funnel["MARKETED"]
    assert result.to_api_dict()["inputs"]["property_rows"] == 5
    assert "marketing" in result.to_api_dict()
    assert "by_segment" in result.to_api_dict()


def test_pipeline_funnel_cumulative_prospect_ge_marketed(sold_path, reisift_path, ql_path):
    result = analyze(sold_path, reisift_path=reisift_path, ql_path=ql_path)
    funnel = {r["stage"]: r["count"] for r in result.pipeline_funnel}
    assert funnel.get("PROSPECT", 0) >= funnel.get("MARKETED", 0)
    assert funnel.get("MARKETED", 0) >= funnel.get("LEAD", 0)
    assert funnel.get("LEAD", 0) >= funnel.get("QUALIFIED_LEAD", 0)
    assert funnel.get("QUALIFIED_LEAD", 0) >= funnel.get("OPPORTUNITY", 0)
    assert funnel.get("OPPORTUNITY", 0) >= funnel.get("HHB_CLOSED", 0)
    marketed_rows = [r for r in result.rows if r.marketed]
    assert marketed_rows
    assert all(
        r.pipeline_stage not in ("NONE",) and r.pipeline_stage != ""
        for r in marketed_rows
    )
    # Marketed rows must be at least MARKETED on the ladder (implies Prospect reached).
    from app.services.sold_properties import _pipeline_rank

    assert all(_pipeline_rank(r.pipeline_stage) >= _pipeline_rank("MARKETED") for r in marketed_rows)
    assert all(_pipeline_rank(r.pipeline_stage) >= _pipeline_rank("PROSPECT") for r in marketed_rows)


def test_never_prospected_uses_history_only_through_each_sold_month(tmp_path, ql_path):
    sold = tmp_path / "sold.csv"
    sold.write_text(
        "period_date,period_label,dataflik_id,transaction_id,buyer_full_name,"
        "property_address,property_city,property_zip,county,state,sale_amount,"
        "investor,in_my_records\n"
        "2026-07-01,Jul 2026,910,t910,Buyer One,10 Old List Rd,Hempstead,11550,"
        "Nassau,NY,300000,TRUE,FALSE\n"
        "2026-07-01,Jul 2026,911,t911,Buyer Two,20 Current List Rd,Hempstead,11550,"
        "Nassau,NY,300000,TRUE,FALSE\n"
        "2026-07-01,Jul 2026,912,t912,Buyer Three,30 Future List Rd,Hempstead,11550,"
        "Nassau,NY,300000,TRUE,FALSE\n",
        encoding="utf-8",
    )
    reisift = tmp_path / "reisift.csv"
    reisift.write_text(
        "Property address,Property city,Property state,Property zip,Lists,Tags\n"
        '10 Old List Rd,Hempstead,NY,11550,8020 Absentee,"List Purchased 8020 1/2026"\n'
        '20 Current List Rd,Hempstead,NY,11550,LI Profiles,"Probates NY Nassau 6-2026"\n'
        '30 Future List Rd,Hempstead,NY,11550,8020 Absentee,"List Purchased 8020 8/2026"\n',
        encoding="utf-8",
    )

    result = analyze(str(sold), reisift_path=str(reisift), ql_path=ql_path)
    by_street = {r.street: r for r in result.rows}

    # History before the report window and before the sale both receive Prospect credit.
    assert by_street["10 Old List Rd"].never_prospected_investor is False
    assert by_street["20 Current List Rd"].never_prospected_investor is False
    # A future dated tag must not be rescued by the row's current undated Lists membership.
    assert by_street["30 Future List Rd"].prospect_list_source == ""
    assert by_street["30 Future List Rd"].never_prospected_investor is True
    assert result.never_prospected_investor_count == 1


def test_sf_txn_pipeline_sets_closed_and_opp(sold_path, reisift_path, ql_path, sf_txn_path):
    result = analyze(
        sold_path,
        reisift_path=reisift_path,
        ql_path=ql_path,
        transactions_path=sf_txn_path,
    )
    by_street = {r.street.lower(): r for r in result.rows}
    main = by_street["100 main st"]
    oak = by_street["200 oak ave"]
    assert main.hhb_closed_date == "2025-04-15"
    assert main.pipeline_stage == "HHB_CLOSED"
    assert oak.under_contract_date == "2025-05-05"
    assert oak.opp_matched is True
    funnel = {r["stage"]: r["count"] for r in result.pipeline_funnel}
    assert funnel.get("HHB_CLOSED", 0) >= 1
    assert funnel.get("OPPORTUNITY", 0) >= funnel.get("HHB_CLOSED", 0)
    assert funnel.get("PROSPECT", 0) >= funnel.get("MARKETED", 0)


def test_reisift_zip_plus_four_does_not_break_matching(tmp_path, ql_path):
    """Real REISift exports carry both "Property zip" (ZIP+4, e.g. "11550-1234") and a clean
    "Property zip5" column. REISIFT_ADDR must prefer zip5 so address keys still line up with
    the sold CSV's plain 5-digit zip — otherwise nearly every REISift row silently fails to
    match (this exact bug was found against the real ~751k-row production export)."""
    sold = tmp_path / "sold.csv"
    sold.write_text(
        "period_date,period_label,dataflik_id,transaction_id,buyer_full_name,"
        "property_address,property_city,property_zip,county,state,sale_amount,"
        "investor,in_my_records\n"
        "2026-07-01,Jul 2026,950,t950,Buyer Inv,1450 Merritts Rd,Farmingdale,11735,"
        "Nassau,NY,300000,TRUE,FALSE\n",
        encoding="utf-8",
    )
    reisift = tmp_path / "reisift.csv"
    reisift.write_text(
        "Property address,Property city,Property state,Property zip,Property zip5,"
        "Created,Lists,Tags\n"
        "1450 Merritts Rd,Farmingdale,NY,11735-1842,11735,2025-01-05,High Equity,"
        '"List Purchased 8020 1/2025,(8020) CC - 2/2025"\n',
        encoding="utf-8",
    )
    result = analyze(str(sold), reisift_path=str(reisift), ql_path=ql_path)
    row = result.rows[0]
    assert row.reisift_matched is True
    assert row.marketed is True
    assert row.prospect_list_source == "8020"


def test_opportunity_closed_lost_not_counted(tmp_path, ql_path):
    """A "Closed Lost" Opportunity sharing a street address must not count as live
    Opportunity-stage evidence via address-only matching — 57% of a real Opportunities
    export sample was Closed Lost, and none of it should inflate opp_matched."""
    sold = tmp_path / "sold.csv"
    sold.write_text(
        "period_date,period_label,dataflik_id,transaction_id,buyer_full_name,"
        "property_address,property_city,property_zip,county,state,sale_amount,"
        "investor,in_my_records\n"
        "2026-07-01,Jul 2026,951,t951,Buyer Inv,5 Dead Deal Ct,Hempstead,11550,"
        "Nassau,NY,300000,TRUE,FALSE\n"
        "2026-07-01,Jul 2026,952,t952,Buyer Inv,6 Live Deal Ct,Hempstead,11550,"
        "Nassau,NY,300000,TRUE,FALSE\n",
        encoding="utf-8",
    )
    reisift = tmp_path / "reisift.csv"
    reisift.write_text(
        "Property address,Property city,Property state,Property zip,Created,Lists,Tags\n"
        "5 Dead Deal Ct,Hempstead,NY,11550,2025-01-05,High Equity,"
        '"List Purchased 8020 1/2025"\n'
        "6 Live Deal Ct,Hempstead,NY,11550,2025-01-05,High Equity,"
        '"List Purchased 8020 1/2025"\n',
        encoding="utf-8",
    )
    opps = tmp_path / "opps.csv"
    opps.write_text(
        "Address (Street),Address (City),Address (State/Province),"
        "Address (ZIP/Postal Code),Stage,Created Date\n"
        "5 Dead Deal Ct,Hempstead,NY,11550,Closed Lost,1/10/2026\n"
        "6 Live Deal Ct,Hempstead,NY,11550,Offer Made,1/10/2026\n",
        encoding="utf-8",
    )
    result = analyze(
        str(sold),
        reisift_path=str(reisift),
        ql_path=ql_path,
        opportunities_path=str(opps),
    )
    by_street = {r.street: r for r in result.rows}
    assert by_street["5 Dead Deal Ct"].opp_matched is False
    assert by_street["6 Live Deal Ct"].opp_matched is True


def test_is_never_prospected_investor_helper():
    base = dict(investor=True, hhb_closed_date="", prospect_list_source="")
    assert is_never_prospected_investor(InvestorSoldRow(**base)) is True
    assert is_never_prospected_investor(InvestorSoldRow(**{**base, "prospect_list_source": "8020"})) is False
    assert is_never_prospected_investor(InvestorSoldRow(**{**base, "prospect_list_source": "lip"})) is False
    assert is_never_prospected_investor(
        InvestorSoldRow(**{**base, "prospect_list_source": "court_alerts"})
    ) is False
    assert is_never_prospected_investor(InvestorSoldRow(**{**base, "hhb_closed_date": "2026-01-01"})) is False
    assert is_never_prospected_investor(InvestorSoldRow(**{**base, "investor": False})) is False


def test_by_month_and_county(sold_path, reisift_path, ql_path):
    result = analyze(sold_path, reisift_path=reisift_path, ql_path=ql_path)
    months = {r["sold_month"]: r for r in result.by_sold_month}
    assert months["2026-07"]["count"] == 2
    assert months["2026-07"]["investor"] == 1
    assert months["2026-07"]["in_our_list"] == 1
    assert months["2026-07"]["marketed"] >= 1
    counties = {r["county"]: r for r in result.by_county}
    assert counties["Nassau"]["count"] == 2
    assert counties["Suffolk"]["both"] == 1


def test_export_workbook_sheets(sold_path, reisift_path, ql_path):
    result = analyze(sold_path, reisift_path=reisift_path, ql_path=ql_path)
    xlsx = build_export_workbook(result)
    assert xlsx[:2] == b"PK"
    restored = result_from_metrics_dict(result.to_api_dict())
    assert restored.sold_rows_ingested == 6
    assert restored.property_rows == 5
    assert restored.both_count == 1
    assert restored.prospect_sources.get("podio", 0) >= 1
    assert restored.lost_to_investor_count == result.lost_to_investor_count
    assert restored.never_prospected_investor_count == result.never_prospected_investor_count
    assert len(restored.rows) == 5
    assert any(r.transaction_count == 2 for r in restored.rows)
    assert any(r.prospect_source == "podio" for r in restored.rows)
    assert any(r.lead_matched for r in restored.rows)
    assert any(r.never_prospected_investor for r in restored.rows)


def test_sf_txn_stale_record_not_credited(tmp_path, reisift_path, ql_path):
    """A Transaction Pipeline row must not reach back to an unrelated historical closing at
    the same street address for a property with no REISift/list evidence to anchor to —
    real addresses resell over the years, and a years-old match would wrongly mark today's
    external sale as one HHB already had/closed."""
    sold = tmp_path / "sold.csv"
    sold.write_text(
        "period_date,period_label,dataflik_id,transaction_id,buyer_full_name,"
        "property_address,property_city,property_zip,county,state,sale_amount,"
        "investor,in_my_records\n"
        "2026-07-01,Jul 2026,900,t900,Buyer Inv,999 Ghost Ave,Hempstead,11550,"
        "Nassau,NY,300000,TRUE,FALSE\n",
        encoding="utf-8",
    )
    txn = tmp_path / "txn.csv"
    txn.write_text(
        "Address (Street),Address (State/Province),Address (ZIP/Postal Code),"
        "Date Contract Signed,Closed Date\n"
        "999 Ghost Ave,NY,11550,1/15/2018,\n",
        encoding="utf-8",
    )
    result = analyze(
        str(sold), reisift_path=reisift_path, ql_path=ql_path, transactions_path=str(txn)
    )
    row = next(r for r in result.rows if r.street == "999 Ghost Ave")
    assert row.under_contract_date == ""
    assert row.opp_matched is False
    assert row.had_presence is False
    assert row.never_prospected_investor is True
    assert result.lost_to_investor_count == 0


def test_sf_txn_contract_date_coalesced_across_columns(tmp_path, reisift_path, ql_path):
    """Both a real "Date Contract Signed" and "Date of Accepted Offer" column can be present
    at once with different fill rates — the earlier-priority, more specific column must win
    per row rather than the first-listed candidate silently shadowing the rest."""
    sold = tmp_path / "sold.csv"
    sold.write_text(
        "period_date,period_label,dataflik_id,transaction_id,buyer_full_name,"
        "property_address,property_city,property_zip,county,state,sale_amount,"
        "investor,in_my_records\n"
        "2026-07-01,Jul 2026,901,t901,Buyer Inv,10 Signed Only Ln,Hempstead,11550,"
        "Nassau,NY,300000,TRUE,FALSE\n"
        "2026-07-01,Jul 2026,902,t902,Buyer Inv,20 Offer Only Ln,Hempstead,11550,"
        "Nassau,NY,300000,TRUE,FALSE\n",
        encoding="utf-8",
    )
    txn = tmp_path / "txn.csv"
    txn.write_text(
        "Address (Street),Address (State/Province),Address (ZIP/Postal Code),"
        "Date Contract Signed,Date of Accepted Offer,Closed Date\n"
        "10 Signed Only Ln,NY,11550,6/1/2026,6/15/2026,\n"
        "20 Offer Only Ln,NY,11550,,6/1/2026,\n",
        encoding="utf-8",
    )
    result = analyze(
        str(sold), reisift_path=reisift_path, ql_path=ql_path, transactions_path=str(txn)
    )
    by_street = {r.street: r for r in result.rows}
    # Contract Signed present and earlier-priority: wins over the later Accepted Offer date.
    assert by_street["10 Signed Only Ln"].under_contract_date == "2026-06-01"
    # Contract Signed absent: falls back to Accepted Offer instead of being silently dropped.
    assert by_street["20 Offer Only Ln"].under_contract_date == "2026-06-01"


def test_missing_flags_raises(tmp_path, reisift_path, ql_path):
    bad = tmp_path / "bad.csv"
    bad.write_text(
        "property_address,property_city,state,property_zip\n1 Main,Buffalo,NY,14201\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="investor"):
        analyze(str(bad), reisift_path=reisift_path, ql_path=ql_path)


@pytest.mark.parametrize("evidence", [
    {"cc_touch_count": 1}, {"sms_touch_count": 2}, {"dm_touch_count": 3},
    {"marketed": True}, {"pipeline_stage": "MARKETED"},
    {"pipeline_stage": "PROSPECT"}, {"lead_matched": True},
    {"qualified_lead_matched": True}, {"opp_matched": True},
    {"first_touch_date": "2024-10-01"},
])
def test_marketing_and_downstream_evidence_imply_prospecting(evidence):
    assert not is_never_prospected_investor(InvestorSoldRow(investor=True, **evidence))


def test_saved_never_prospected_flags_and_rollups_are_refreshed(tmp_path):
    from app.services.investor_sold import refresh_prospecting_metrics
    from app.services.report_store import save_investor_sold_report, load_investor_sold_report
    rows = [InvestorSoldRow(investor=True, street="32 Neslo Dr", sold_month="2026-06",
               county="Suffolk", sms_touch_count=2, dm_touch_count=3,
               pipeline_stage="MARKETED", never_prospected_investor=True).to_dict(),
            InvestorSoldRow(investor=True, sold_month="2026-06", county="Suffolk").to_dict()]
    metrics = {"rows": rows, "lost": {"never_prospected_investor_count": 2},
               "by_sold_month": [{"sold_month": "2026-06", "never_prospected_investor": 2}],
               "by_county": [{"county": "Suffolk", "never_prospected_investor": 2}]}
    save_investor_sold_report("legacy", metrics=metrics, reports_dir=tmp_path)
    actual = load_investor_sold_report("legacy", reports_dir=tmp_path)["metrics"]
    assert [r["never_prospected_investor"] for r in actual["rows"]] == [False, True]
    assert actual["lost"]["never_prospected_investor_count"] == 1
    assert actual["lost"]["never_prospected_investor_pct"] == 50.0
    assert actual["by_sold_month"][0]["never_prospected_investor"] == 1
    assert actual["by_county"][0]["never_prospected_investor"] == 1
    assert refresh_prospecting_metrics(actual) == actual
    restored = result_from_metrics_dict(actual)
    assert restored.never_prospected_investor_count == 1
    sheet = pd.read_excel(BytesIO(build_export_workbook(restored)), sheet_name="Never Prospected Inv")
    assert len(sheet) == 1


@pytest.mark.parametrize("channel", ["CC", "SMS", "DM"])
@pytest.mark.parametrize("month,expected", [("6/2026", False), ("8/2026", True)])
def test_marketing_without_list_tag_uses_sale_cutoff(sale_case, channel, month, expected):
    _, reisift, _, run = sale_case
    reisift.loc[0, ["Property address", "Tags", "Lists"]] = [
        "999 Nowhere Rd", f"(8020) {channel} - {month}", "",
    ]
    row = run().rows[0]
    assert row.never_prospected_investor is expected
    assert row.marketed is (not expected)
