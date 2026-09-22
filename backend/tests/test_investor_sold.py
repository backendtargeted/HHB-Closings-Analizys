"""Tests for Gate 7 investor & in-list sold + pipeline depth."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.services.investor_sold import (
    InvestorSoldRow,
    analyze,
    build_export_workbook,
    is_never_prospected_investor,
    result_from_metrics_dict,
    segment_for,
)

FIXTURES = Path(__file__).parent / "fixtures"


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
    assert result.buybox_town_count >= 200
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
