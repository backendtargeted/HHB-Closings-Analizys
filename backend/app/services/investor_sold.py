"""
Gate 7 — Investor & In-List Sold + canonical pipeline depth.

Universe: CleanREISift sold_properties_full.csv (property × sold month).
Requires REISift + Salesforce QL. Opportunities optional.
Lost to investor = we had it (In My Records OR REISift/CRM presence) AND investor
AND not HHB closed. Loss rate denominator = properties we had.
Pipeline: Prospect (8020 / Court Alerts / LI Profiles) → Marketed (CC/DM/SMS) →
Lead (SF/Podio) → Qualified Lead → Opportunity → Closed.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from io import BytesIO
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

import pandas as pd

from .analysis import _dedupe_parsed_tag_events, parse_tags
from .closing_resolution import resolve_milestones_from_parsed
from .lifecycle import ENGAGED_LABELS, build_events, compute_stage_funnel_open, get_highest_stage
from .marketing_mapper import find_column_name, make_address_key, normalize_status, smart_read_csv
from .monthly_consolidated import REISIFT_ADDR, TAGS_CANDIDATES, load_reisift_file
from .probate import (
    OPP_ADDR,
    OPP_DATE_CANDIDATES,
    QL_ADDR,
    QL_PHONE_CANDIDATES,
    MatchIndex,
    _best_hit,
    _build_match_index,
    _load_crm_file,
    _phones_from_row,
    months_between,
)
from .qualified_leads import CREATE_DATE_CANDIDATES
from .sold_properties import (
    CANONICAL_PIPELINE,
    LISTS_CANDIDATES,
    PIPELINE_FUNNEL_ALWAYS,
    PIPELINE_LABELS,
    PIPELINE_ORDER,
    REISIFT_PHONE_CANDIDATES,
    TOUCH_CHANNELS,
    _contact_touch_stats,
    _first_podio_crm_date,
    _iso_day,
    _lists_has_prospect_source,
    _max_pipeline,
    _mean_median,
    _month_end,
    _parse_iso_dt,
    _pct,
    _podio_crm_present,
    _sf_engaged_before,
    earliest_prospect_list,
    parse_sold_month,
)

REPORT_TYPE = "investor_sold"

ProgressCallback = Callable[[int, str], None]

SOLD_ADDR = {
    "street": ["property_address", "Property address", "Property Address", "address", "Address"],
    "city": ["property_city", "Property city", "Property City", "city", "City"],
    "state": ["state", "State", "property_state", "Property state"],
    "zip": ["property_zip", "Property zip", "Property Zip", "zip", "Zip", "zip_code"],
}

PERIOD_DATE_CANDIDATES = ["period_date", "Period Date", "sold_date", "Sold Date"]
PERIOD_LABEL_CANDIDATES = ["period_label", "Period Label", "sold_month", "Sold Month"]
INVESTOR_CANDIDATES = ["investor", "Investor", "is_investor_sale"]
IN_LIST_CANDIDATES = ["in_my_records", "In My Records", "in_my_list", "is_in_my_records"]
BUYER_CANDIDATES = ["buyer_full_name", "Buyer", "buyer"]
SALE_AMOUNT_CANDIDATES = ["sale_amount", "Sale Amount", "sale_price"]
COUNTY_CANDIDATES = ["county", "County", "property_county"]
SCORE_CANDIDATES = ["investor_score", "Investor Score"]
DISTRESSOR_CANDIDATES = ["distressors", "Distressors", "Tags"]
DATAFLIK_CANDIDATES = ["dataflik_id", "Dataflik ID"]
TRANSACTION_CANDIDATES = ["transaction_id", "Transaction ID"]

SEGMENT_IDS = ("investor", "in_our_list", "both", "neither")


def _col_val(row: pd.Series, col: Optional[str]) -> str:
    if not col or col not in row.index or pd.isna(row[col]):
        return ""
    return str(row[col]).strip()


def _as_bool(raw: object) -> bool:
    if raw is None or (isinstance(raw, float) and pd.isna(raw)):
        return False
    if isinstance(raw, bool):
        return raw
    text = str(raw).strip().lower()
    return text in ("true", "1", "yes", "y", "t")


def _discover_cols(df: pd.DataFrame, mapping: Dict[str, List[str]]) -> Dict[str, Optional[str]]:
    return {k: find_column_name(df, v) for k, v in mapping.items()}


def load_sold_transactions_file(file_path: str) -> pd.DataFrame:
    path = Path(file_path)
    suffix = path.suffix.lower()
    if suffix in (".xlsx", ".xls"):
        return pd.read_excel(file_path, engine="openpyxl", dtype=str)
    return smart_read_csv(file_path, dtype=str)


def segment_for(investor: bool, in_my_records: bool) -> str:
    if investor and in_my_records:
        return "both"
    if investor:
        return "investor"
    if in_my_records:
        return "in_our_list"
    return "neither"


def had_presence(row: "InvestorSoldRow") -> bool:
    """True when we had the property on list and/or in REISift/CRM before/at sale."""
    return bool(
        row.in_my_records
        or row.reisift_matched
        or row.marketed
        or row.lead_matched
        or row.qualified_lead_matched
        or row.prospect_matched
        or row.opp_matched
        or row.list_purchase_date
        or row.under_contract_date
        or row.hhb_closed_date
        or (row.pipeline_stage and row.pipeline_stage != "NONE")
    )


def is_lost_to_investor(row: "InvestorSoldRow") -> bool:
    """Investor bought a property we had; we did not HHB-close it."""
    return bool(had_presence(row) and row.investor and not row.hhb_closed_date)


def _parse_sold_ts(period_date: str, period_label: str) -> Optional[pd.Timestamp]:
    sold_ts = None
    if period_date:
        sold_ts = parse_sold_month(period_date)
        if sold_ts is None:
            parsed = pd.to_datetime(period_date, errors="coerce")
            if pd.notna(parsed):
                sold_ts = pd.Timestamp(year=int(parsed.year), month=int(parsed.month), day=1)
    if sold_ts is None and period_label:
        sold_ts = parse_sold_month(period_label)
    return sold_ts


@dataclass
class InvestorSoldRow:
    address: str = ""
    address_key: str = ""
    street: str = ""
    city: str = ""
    state: str = ""
    zip: str = ""
    county: str = ""
    period_date: str = ""
    period_label: str = ""
    sold_month: str = ""
    buyer_full_name: str = ""
    sale_amount: str = ""
    investor: bool = False
    in_my_records: bool = False
    had_presence: bool = False
    segment: str = "neither"
    investor_score: str = ""
    distressors: str = ""
    dataflik_id: str = ""
    transaction_id: str = ""
    transaction_count: int = 1
    list_purchase_date: str = ""
    reisift_matched: bool = False
    marketed: bool = False
    cc_touch_count: int = 0
    sms_touch_count: int = 0
    dm_touch_count: int = 0
    first_touch_channel: str = ""
    first_touch_date: str = ""
    lead_matched: bool = False
    lead_date: str = ""
    lead_source: str = ""
    qualified_lead_matched: bool = False
    qualified_lead_date: str = ""
    prospect_matched: bool = False
    prospect_date: str = ""
    prospect_source: str = ""
    opp_matched: bool = False
    opp_created_date: str = ""
    under_contract_date: str = ""
    hhb_closed_date: str = ""
    pipeline_stage: str = "NONE"
    pipeline_stage_label: str = ""
    months_list_to_sold: Optional[int] = None
    months_list_to_qualified_lead: Optional[int] = None
    months_list_to_prospect: Optional[int] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "address": self.address,
            "address_key": self.address_key,
            "street": self.street,
            "city": self.city,
            "state": self.state,
            "zip": self.zip,
            "county": self.county,
            "period_date": self.period_date,
            "period_label": self.period_label,
            "sold_month": self.sold_month,
            "buyer_full_name": self.buyer_full_name,
            "sale_amount": self.sale_amount,
            "investor": self.investor,
            "in_my_records": self.in_my_records,
            "had_presence": self.had_presence,
            "segment": self.segment,
            "investor_score": self.investor_score,
            "distressors": self.distressors,
            "dataflik_id": self.dataflik_id,
            "transaction_id": self.transaction_id,
            "transaction_count": self.transaction_count,
            "list_purchase_date": self.list_purchase_date,
            "reisift_matched": self.reisift_matched,
            "marketed": self.marketed,
            "cc_touch_count": self.cc_touch_count,
            "sms_touch_count": self.sms_touch_count,
            "dm_touch_count": self.dm_touch_count,
            "first_touch_channel": self.first_touch_channel,
            "first_touch_date": self.first_touch_date,
            "lead_matched": self.lead_matched,
            "lead_date": self.lead_date,
            "lead_source": self.lead_source,
            "qualified_lead_matched": self.qualified_lead_matched,
            "qualified_lead_date": self.qualified_lead_date,
            "prospect_matched": self.prospect_matched,
            "prospect_date": self.prospect_date,
            "prospect_source": self.prospect_source,
            "opp_matched": self.opp_matched,
            "opp_created_date": self.opp_created_date,
            "under_contract_date": self.under_contract_date,
            "hhb_closed_date": self.hhb_closed_date,
            "pipeline_stage": self.pipeline_stage,
            "pipeline_stage_label": self.pipeline_stage_label,
            "months_list_to_sold": self.months_list_to_sold,
            "months_list_to_qualified_lead": self.months_list_to_qualified_lead,
            "months_list_to_prospect": self.months_list_to_prospect,
        }


@dataclass
class InvestorSoldResult:
    sold_rows_ingested: int = 0
    property_rows: int = 0
    unique_addresses: int = 0
    investor_count: int = 0
    investor_pct: float = 0.0
    in_our_list_count: int = 0
    in_our_list_pct: float = 0.0
    both_count: int = 0
    both_pct: float = 0.0
    neither_count: int = 0
    neither_pct: float = 0.0
    marketed_count: int = 0
    marketed_pct: float = 0.0
    never_marketed_count: int = 0
    lead_matched: int = 0
    lead_rate_pct: float = 0.0
    qualified_lead_matched: int = 0
    qualified_lead_rate_pct: float = 0.0
    prospect_matched: int = 0
    prospect_rate_pct: float = 0.0
    opp_matched: int = 0
    opp_rate_pct: float = 0.0
    under_contract_count: int = 0
    hhb_closed_count: int = 0
    reisift_matched_count: int = 0
    lost_to_investor_count: int = 0
    lost_to_investor_pct: float = 0.0
    had_presence_count: int = 0
    had_presence_investor_count: int = 0
    had_presence_non_investor_count: int = 0
    lost_by_stage: List[Dict[str, Any]] = field(default_factory=list)
    had_presence_exits_by_buyer: Dict[str, int] = field(default_factory=dict)
    total_touch_counts: Dict[str, int] = field(default_factory=dict)
    avg_touches_per_marketed: Optional[float] = None
    mean_months_list_to_sold: Optional[float] = None
    median_months_list_to_sold: Optional[float] = None
    mean_months_list_to_qualified_lead: Optional[float] = None
    median_months_list_to_qualified_lead: Optional[float] = None
    mean_months_list_to_prospect: Optional[float] = None
    median_months_list_to_prospect: Optional[float] = None
    pipeline_funnel: List[Dict[str, Any]] = field(default_factory=list)
    prospect_sources: Dict[str, int] = field(default_factory=dict)
    lead_sources: Dict[str, int] = field(default_factory=dict)
    by_segment: List[Dict[str, Any]] = field(default_factory=list)
    by_sold_month: List[Dict[str, Any]] = field(default_factory=list)
    by_county: List[Dict[str, Any]] = field(default_factory=list)
    rows: List[InvestorSoldRow] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    methodology_note: str = ""
    date_window_start: str = ""
    date_window_end: str = ""
    enrichment_enabled: bool = True

    def to_api_dict(self) -> Dict[str, Any]:
        return {
            "report_type": REPORT_TYPE,
            "date_window_start": self.date_window_start,
            "date_window_end": self.date_window_end,
            "inputs": {
                "sold_rows_ingested": self.sold_rows_ingested,
                "property_rows": self.property_rows,
                "unique_addresses": self.unique_addresses,
                "enrichment_enabled": self.enrichment_enabled,
            },
            "segments": {
                "investor_count": self.investor_count,
                "investor_pct": self.investor_pct,
                "in_our_list_count": self.in_our_list_count,
                "in_our_list_pct": self.in_our_list_pct,
                "both_count": self.both_count,
                "both_pct": self.both_pct,
                "neither_count": self.neither_count,
                "neither_pct": self.neither_pct,
            },
            "lost": {
                "lost_to_investor_count": self.lost_to_investor_count,
                "lost_to_investor_pct": self.lost_to_investor_pct,
                "had_presence_count": self.had_presence_count,
                "had_presence_investor_count": self.had_presence_investor_count,
                "had_presence_non_investor_count": self.had_presence_non_investor_count,
                "lost_by_stage": self.lost_by_stage,
                "had_presence_exits_by_buyer": self.had_presence_exits_by_buyer,
            },
            "marketing": {
                "marketed_count": self.marketed_count,
                "marketed_pct": self.marketed_pct,
                "never_marketed_count": self.never_marketed_count,
                "total_touch_counts": self.total_touch_counts,
                "avg_touches_per_marketed": self.avg_touches_per_marketed,
            },
            "match": {
                "lead_matched": self.lead_matched,
                "lead_rate_pct": self.lead_rate_pct,
                "qualified_lead_matched": self.qualified_lead_matched,
                "qualified_lead_rate_pct": self.qualified_lead_rate_pct,
                "prospect_matched": self.prospect_matched,
                "prospect_rate_pct": self.prospect_rate_pct,
                "opp_matched": self.opp_matched,
                "opp_rate_pct": self.opp_rate_pct,
                "under_contract_count": self.under_contract_count,
                "hhb_closed_count": self.hhb_closed_count,
                "reisift_matched_count": self.reisift_matched_count,
            },
            "lag": {
                "mean_months_list_to_sold": self.mean_months_list_to_sold,
                "median_months_list_to_sold": self.median_months_list_to_sold,
                "mean_months_list_to_qualified_lead": self.mean_months_list_to_qualified_lead,
                "median_months_list_to_qualified_lead": self.median_months_list_to_qualified_lead,
                "mean_months_list_to_prospect": self.mean_months_list_to_prospect,
                "median_months_list_to_prospect": self.median_months_list_to_prospect,
            },
            "pipeline_funnel": self.pipeline_funnel,
            "prospect_sources": self.prospect_sources,
            "lead_sources": self.lead_sources,
            "by_segment": self.by_segment,
            "by_sold_month": self.by_sold_month,
            "by_county": self.by_county,
            "rows": [r.to_dict() for r in self.rows],
            "warnings": self.warnings,
            "methodology_note": self.methodology_note,
            "enrichment": {
                "reisift_matched_count": self.reisift_matched_count,
                "marketed_count": self.marketed_count,
                "lead_matched": self.lead_matched,
                "qualified_lead_matched": self.qualified_lead_matched,
                "prospect_matched": self.prospect_matched,
                "opp_matched": self.opp_matched,
            },
        }


def _collapse_key(row: InvestorSoldRow) -> str:
    month = row.sold_month or "(unknown)"
    if row.dataflik_id:
        return f"df:{row.dataflik_id}|{month}"
    if row.address_key:
        return f"ak:{row.address_key}|{month}"
    return f"addr:{row.address.lower()}|{month}|{row.sale_amount}|{row.buyer_full_name}"


def collapse_property_month_rows(txn_rows: List[InvestorSoldRow]) -> List[InvestorSoldRow]:
    groups: Dict[str, InvestorSoldRow] = {}
    order: List[str] = []
    for row in txn_rows:
        key = _collapse_key(row)
        if key not in groups:
            row.transaction_count = 1
            groups[key] = row
            order.append(key)
            continue
        base = groups[key]
        base.transaction_count += 1
        base.investor = base.investor or row.investor
        base.in_my_records = base.in_my_records or row.in_my_records
        base.segment = segment_for(base.investor, base.in_my_records)
        if not base.investor_score and row.investor_score:
            base.investor_score = row.investor_score
        if not base.distressors and row.distressors:
            base.distressors = row.distressors
    return [groups[k] for k in order]


def _row_kwargs(item: Dict[str, Any]) -> Dict[str, Any]:
    allowed = {f.name for f in InvestorSoldRow.__dataclass_fields__.values()}  # type: ignore[attr-defined]
    out: Dict[str, Any] = {}
    for k in allowed:
        out[k] = item.get(k)
    for b in (
        "investor",
        "in_my_records",
        "had_presence",
        "reisift_matched",
        "marketed",
        "lead_matched",
        "qualified_lead_matched",
        "prospect_matched",
        "opp_matched",
    ):
        out[b] = bool(out.get(b))
    for i in ("cc_touch_count", "sms_touch_count", "dm_touch_count", "transaction_count"):
        out[i] = int(out.get(i) or (1 if i == "transaction_count" else 0))
    for opt in (
        "months_list_to_sold",
        "months_list_to_qualified_lead",
        "months_list_to_prospect",
    ):
        raw = out.get(opt)
        if raw is None or raw == "":
            out[opt] = None
        else:
            try:
                out[opt] = int(raw)
            except (TypeError, ValueError):
                out[opt] = None
    str_keys = allowed - {
        "investor",
        "in_my_records",
        "reisift_matched",
        "marketed",
        "lead_matched",
        "qualified_lead_matched",
        "prospect_matched",
        "opp_matched",
        "cc_touch_count",
        "sms_touch_count",
        "dm_touch_count",
        "transaction_count",
        "months_list_to_sold",
        "months_list_to_qualified_lead",
        "months_list_to_prospect",
    }
    for s in str_keys:
        out[s] = str(out.get(s) or "")
    return out


def result_from_metrics_dict(metrics: Dict[str, Any]) -> InvestorSoldResult:
    rows = [InvestorSoldRow(**_row_kwargs(item)) for item in metrics.get("rows") or []]
    for row in rows:
        row.had_presence = had_presence(row)
    inputs = metrics.get("inputs") or {}
    segments = metrics.get("segments") or {}
    marketing = metrics.get("marketing") or {}
    match = metrics.get("match") or metrics.get("enrichment") or {}
    lag = metrics.get("lag") or {}
    property_rows = int(inputs.get("property_rows") or len(rows) or 0)
    return InvestorSoldResult(
        sold_rows_ingested=int(inputs.get("sold_rows_ingested") or 0),
        property_rows=property_rows,
        unique_addresses=int(inputs.get("unique_addresses") or 0),
        investor_count=int(segments.get("investor_count") or 0),
        investor_pct=float(segments.get("investor_pct") or 0),
        in_our_list_count=int(segments.get("in_our_list_count") or 0),
        in_our_list_pct=float(segments.get("in_our_list_pct") or 0),
        both_count=int(segments.get("both_count") or 0),
        both_pct=float(segments.get("both_pct") or 0),
        neither_count=int(segments.get("neither_count") or 0),
        neither_pct=float(segments.get("neither_pct") or 0),
        marketed_count=int(marketing.get("marketed_count") or match.get("marketed_count") or 0),
        marketed_pct=float(marketing.get("marketed_pct") or 0),
        never_marketed_count=int(marketing.get("never_marketed_count") or 0),
        lead_matched=int(match.get("lead_matched") or 0),
        lead_rate_pct=float(match.get("lead_rate_pct") or 0),
        qualified_lead_matched=int(match.get("qualified_lead_matched") or 0),
        qualified_lead_rate_pct=float(match.get("qualified_lead_rate_pct") or 0),
        prospect_matched=int(match.get("prospect_matched") or 0),
        prospect_rate_pct=float(match.get("prospect_rate_pct") or 0),
        opp_matched=int(match.get("opp_matched") or 0),
        opp_rate_pct=float(match.get("opp_rate_pct") or 0),
        under_contract_count=int(match.get("under_contract_count") or 0),
        hhb_closed_count=int(match.get("hhb_closed_count") or 0),
        reisift_matched_count=int(match.get("reisift_matched_count") or 0),
        lost_to_investor_count=int((metrics.get("lost") or {}).get("lost_to_investor_count") or 0),
        lost_to_investor_pct=float((metrics.get("lost") or {}).get("lost_to_investor_pct") or 0),
        had_presence_count=int(
            (metrics.get("lost") or {}).get("had_presence_count")
            or (metrics.get("lost") or {}).get("in_list_count")
            or 0
        ),
        had_presence_investor_count=int(
            (metrics.get("lost") or {}).get("had_presence_investor_count")
            or (metrics.get("lost") or {}).get("in_list_investor_count")
            or 0
        ),
        had_presence_non_investor_count=int(
            (metrics.get("lost") or {}).get("had_presence_non_investor_count")
            or (metrics.get("lost") or {}).get("in_list_non_investor_count")
            or 0
        ),
        lost_by_stage=list((metrics.get("lost") or {}).get("lost_by_stage") or []),
        had_presence_exits_by_buyer=dict(
            (metrics.get("lost") or {}).get("had_presence_exits_by_buyer")
            or (metrics.get("lost") or {}).get("in_list_exits_by_buyer")
            or {}
        ),
        total_touch_counts=dict(marketing.get("total_touch_counts") or {}),
        avg_touches_per_marketed=marketing.get("avg_touches_per_marketed"),
        mean_months_list_to_sold=lag.get("mean_months_list_to_sold"),
        median_months_list_to_sold=lag.get("median_months_list_to_sold"),
        mean_months_list_to_qualified_lead=lag.get("mean_months_list_to_qualified_lead"),
        median_months_list_to_qualified_lead=lag.get("median_months_list_to_qualified_lead"),
        mean_months_list_to_prospect=lag.get("mean_months_list_to_prospect"),
        median_months_list_to_prospect=lag.get("median_months_list_to_prospect"),
        pipeline_funnel=list(metrics.get("pipeline_funnel") or []),
        prospect_sources=dict(metrics.get("prospect_sources") or {}),
        lead_sources=dict(metrics.get("lead_sources") or {}),
        by_segment=list(metrics.get("by_segment") or []),
        by_sold_month=list(metrics.get("by_sold_month") or []),
        by_county=list(metrics.get("by_county") or []),
        rows=rows,
        warnings=list(metrics.get("warnings") or []),
        methodology_note=str(metrics.get("methodology_note") or ""),
        date_window_start=str(metrics.get("date_window_start") or ""),
        date_window_end=str(metrics.get("date_window_end") or ""),
        enrichment_enabled=bool(inputs.get("enrichment_enabled", True)),
    )


def _empty_segment_rollup(segment: str) -> Dict[str, Any]:
    return {
        "segment": segment,
        "count": 0,
        "marketed": 0,
        "never_marketed": 0,
        "leads": 0,
        "qualified_leads": 0,
        "prospects": 0,
        "prospects_podio": 0,
        "prospects_ql": 0,
        "prospects_sf": 0,
        "opportunities": 0,
        "under_contract": 0,
        "hhb_closed": 0,
        "median_months_list_to_sold": None,
    }


def _empty_rollup(key_name: str, key: str) -> Dict[str, Any]:
    return {
        key_name: key,
        "count": 0,
        "investor": 0,
        "in_our_list": 0,
        "both": 0,
        "neither": 0,
        "marketed": 0,
        "leads": 0,
        "qualified_leads": 0,
        "prospects": 0,
        "had_presence": 0,
        "lost_to_investor": 0,
    }


def _build_reisift_index(reisift_df: pd.DataFrame) -> Dict[str, Dict[str, Any]]:
    tags_col = find_column_name(reisift_df, TAGS_CANDIDATES)
    if not tags_col:
        raise ValueError("Missing required column: Tags")
    lists_col = find_column_name(reisift_df, LISTS_CANDIDATES)
    addr_cols = {k: find_column_name(reisift_df, v) for k, v in REISIFT_ADDR.items()}
    index: Dict[str, Dict[str, Any]] = {}
    for _, row in reisift_df.iterrows():
        key = make_address_key(
            _col_val(row, addr_cols.get("street")),
            _col_val(row, addr_cols.get("city")),
            _col_val(row, addr_cols.get("state")),
            _col_val(row, addr_cols.get("zip")),
        )
        if not key or key in index:
            continue
        index[key] = {
            "tags": str(row.get(tags_col, "") or "").strip(),
            "lists": str(row.get(lists_col, "") or "").strip() if lists_col else "",
            "phones": _phones_from_row(row, REISIFT_PHONE_CANDIDATES),
        }
    return index


def _enrich_row(
    sold_row: InvestorSoldRow,
    *,
    reisift_hit: Optional[Dict[str, Any]],
    ql_index: MatchIndex,
    opp_index: Optional[MatchIndex],
    sold_ts: Optional[pd.Timestamp],
) -> None:
    if not reisift_hit:
        return
    sold_row.reisift_matched = True
    tags_val = str(reisift_hit.get("tags") or "")
    lists_val = str(reisift_hit.get("lists") or "")
    parsed = _dedupe_parsed_tag_events(parse_tags(tags_val)) if tags_val else []
    phones = list(reisift_hit.get("phones") or [])

    sold_end = _month_end(sold_ts) if sold_ts is not None else None
    sold_end_dt = sold_end.to_pydatetime() if sold_end is not None else None

    touch_counts, first_ch, first_date = _contact_touch_stats(
        parsed, on_or_before=sold_end_dt
    )
    sold_row.cc_touch_count = touch_counts.get("CC", 0)
    sold_row.sms_touch_count = touch_counts.get("SMS", 0)
    sold_row.dm_touch_count = touch_counts.get("DM", 0)
    sold_row.marketed = sum(touch_counts.values()) > 0
    sold_row.first_touch_channel = first_ch or ""
    sold_row.first_touch_date = first_date or ""

    list_dt, prospect_list_source = earliest_prospect_list(parsed, tags_val, lists_val)
    list_purchase_ymd = list_dt.date().isoformat() if list_dt else ""
    sold_row.list_purchase_date = list_purchase_ymd
    first_list_month = (
        pd.Timestamp(year=list_dt.year, month=list_dt.month, day=1) if list_dt else None
    )
    lists_src = _lists_has_prospect_source(lists_val)
    if not prospect_list_source and lists_src:
        prospect_list_source = lists_src

    pipeline = "NONE"
    if list_dt is not None or sold_row.in_my_records or prospect_list_source or lists_src:
        pipeline = "PROSPECT"
    if sold_row.marketed:
        pipeline = _max_pipeline(pipeline, "MARKETED")

    events = build_events(parsed)
    if sold_end is not None:
        stages = compute_stage_funnel_open(events, sold_end)
    else:
        stages = compute_stage_funnel_open(events, pd.Timestamp.now().normalize())
    milestones = resolve_milestones_from_parsed(parsed)

    hhb_closed = milestones.date_closed
    if sold_end_dt is not None and hhb_closed is not None and hhb_closed > sold_end_dt:
        hhb_closed = None
    if hhb_closed is not None:
        stages["CLOSED"] = {"reached": True, "date": hhb_closed.date().isoformat()}
        sold_row.hhb_closed_date = hhb_closed.date().isoformat()
        pipeline = _max_pipeline(pipeline, "HHB_CLOSED")

    uc = milestones.date_under_contract
    if sold_end_dt is not None and uc is not None and uc > sold_end_dt:
        uc = None
    if uc is not None:
        sold_row.under_contract_date = uc.date().isoformat()

    before = (sold_end + pd.Timedelta(days=1)) if sold_end is not None else None
    ql_hit = _best_hit(
        ql_index,
        sold_row.address_key,
        phones,
        on_or_after=first_list_month,
        before=before,
    )
    from_ql = ql_hit is not None and ql_hit.date is not None
    from_sf = (
        _sf_engaged_before(parsed, sold_end_dt) if sold_end_dt is not None else False
    )
    from_podio = _podio_crm_present(parsed)

    sold_row.lead_matched = from_sf or from_podio
    sold_row.qualified_lead_matched = from_ql
    sold_row.prospect_matched = sold_row.lead_matched or sold_row.qualified_lead_matched

    if from_sf and sold_end_dt is not None:
        for p in parsed:
            if p.get("type") not in ("sf_updated", "sf_status"):
                continue
            label = normalize_status(str(p.get("label", "")))
            if label not in ENGAGED_LABELS:
                continue
            dt = _parse_iso_dt(str(p.get("date", "")))
            if dt is not None and dt <= sold_end_dt:
                sold_row.lead_date = dt.date().isoformat()
                sold_row.lead_source = "sf_tag"
                break
        if not sold_row.lead_source:
            sold_row.lead_source = "sf_tag"
    if from_podio and not sold_row.lead_source:
        sold_row.lead_date = _first_podio_crm_date(parsed)
        sold_row.lead_source = "podio"

    if from_ql and ql_hit is not None:
        sold_row.qualified_lead_date = _iso_day(ql_hit.date)
        sold_row.prospect_date = sold_row.qualified_lead_date
        sold_row.prospect_source = "ql"
    elif sold_row.lead_source:
        sold_row.prospect_date = sold_row.lead_date
        sold_row.prospect_source = sold_row.lead_source

    if sold_row.lead_matched:
        pipeline = _max_pipeline(pipeline, "LEAD")
    if sold_row.qualified_lead_matched:
        pipeline = _max_pipeline(pipeline, "QUALIFIED_LEAD")

    if opp_index is not None:
        opp_hit = _best_hit(
            opp_index,
            sold_row.address_key,
            phones,
            on_or_after=first_list_month,
            before=before,
        )
        if opp_hit is not None and opp_hit.date is not None:
            sold_row.opp_matched = True
            sold_row.opp_created_date = _iso_day(opp_hit.date)
            pipeline = _max_pipeline(pipeline, "OPPORTUNITY")

    # Under contract is Opportunity (not a separate ladder stage).
    if sold_row.under_contract_date:
        sold_row.opp_matched = True
        pipeline = _max_pipeline(pipeline, "OPPORTUNITY")

    highest = get_highest_stage(stages)
    if highest == "CLOSED":
        pipeline = _max_pipeline(pipeline, "HHB_CLOSED")
    sold_row.pipeline_stage = pipeline
    sold_row.pipeline_stage_label = PIPELINE_LABELS.get(pipeline, pipeline)
    sold_row.had_presence = had_presence(sold_row)

    if list_dt is not None and sold_ts is not None:
        sold_row.months_list_to_sold = months_between(pd.Timestamp(list_dt), sold_ts)
    ql_dt = (
        _parse_iso_dt(sold_row.qualified_lead_date)
        if sold_row.qualified_lead_date
        else None
    )
    if list_dt is not None and ql_dt is not None:
        sold_row.months_list_to_qualified_lead = months_between(
            pd.Timestamp(list_dt), pd.Timestamp(ql_dt)
        )
        sold_row.months_list_to_prospect = sold_row.months_list_to_qualified_lead


def analyze(
    sold_path: str,
    reisift_path: Optional[str] = None,
    ql_path: Optional[str] = None,
    opportunities_path: Optional[str] = None,
    on_progress: Optional[ProgressCallback] = None,
) -> InvestorSoldResult:
    def report(pct: int, message: str) -> None:
        if on_progress:
            on_progress(pct, message)

    if not reisift_path:
        raise ValueError("REISift export is required for Gate 7 pipeline enrichment")
    if not ql_path:
        raise ValueError("Salesforce Total Qualified Leads is required for Gate 7")

    warnings: List[str] = []
    report(5, "Loading sold transactions CSV…")
    sold_df = load_sold_transactions_file(sold_path)
    if sold_df.empty:
        raise ValueError("Sold transactions file is empty")

    addr_cols = _discover_cols(sold_df, SOLD_ADDR)
    if not addr_cols.get("street"):
        raise ValueError("Missing required column: property_address")

    investor_col = find_column_name(sold_df, INVESTOR_CANDIDATES)
    in_list_col = find_column_name(sold_df, IN_LIST_CANDIDATES)
    if not investor_col or not in_list_col:
        raise ValueError(
            "Missing required columns: investor and in_my_records "
            "(CleanREISift sold_properties_full.csv)"
        )

    period_date_col = find_column_name(sold_df, PERIOD_DATE_CANDIDATES)
    period_label_col = find_column_name(sold_df, PERIOD_LABEL_CANDIDATES)
    buyer_col = find_column_name(sold_df, BUYER_CANDIDATES)
    amount_col = find_column_name(sold_df, SALE_AMOUNT_CANDIDATES)
    county_col = find_column_name(sold_df, COUNTY_CANDIDATES)
    score_col = find_column_name(sold_df, SCORE_CANDIDATES)
    distress_col = find_column_name(sold_df, DISTRESSOR_CANDIDATES)
    dataflik_col = find_column_name(sold_df, DATAFLIK_CANDIDATES)
    txn_col = find_column_name(sold_df, TRANSACTION_CANDIDATES)

    report(12, "Loading REISift export…")
    reisift_df = load_reisift_file(reisift_path)
    reisift_index = _build_reisift_index(reisift_df)
    if not reisift_index:
        raise ValueError("REISift export produced no address keys")

    report(20, "Loading Salesforce qualified leads…")
    ql_index = _build_match_index(
        _load_crm_file(ql_path),
        QL_ADDR,
        list(CREATE_DATE_CANDIDATES),
        QL_PHONE_CANDIDATES,
    )

    opp_index: Optional[MatchIndex] = None
    if opportunities_path:
        report(26, "Loading opportunities…")
        opp_index = _build_match_index(
            _load_crm_file(opportunities_path), OPP_ADDR, OPP_DATE_CANDIDATES
        )
    else:
        warnings.append("Opportunities file not uploaded — Opportunity stage counts will be zero.")

    report(35, "Building sold property rows…")
    txn_rows: List[InvestorSoldRow] = []
    unique_keys: set[str] = set()
    sold_months: List[pd.Timestamp] = []
    sold_ts_by_collapse: Dict[str, Optional[pd.Timestamp]] = {}
    total = len(sold_df)

    for i, (_, row) in enumerate(sold_df.iterrows()):
        if total and i % 2000 == 0:
            report(35 + int(25 * i / max(total, 1)), f"Scanning sold rows… ({i}/{total})")

        street = _col_val(row, addr_cols.get("street"))
        city = _col_val(row, addr_cols.get("city"))
        state = _col_val(row, addr_cols.get("state"))
        zip_code = _col_val(row, addr_cols.get("zip"))
        key = make_address_key(street, city, state, zip_code)
        if key:
            unique_keys.add(key)

        investor = _as_bool(row.get(investor_col))
        in_list = _as_bool(row.get(in_list_col))
        period_date = _col_val(row, period_date_col)
        period_label = _col_val(row, period_label_col)
        sold_ts = _parse_sold_ts(period_date, period_label)
        if sold_ts is not None:
            sold_months.append(sold_ts)
        sold_month = (
            f"{sold_ts.year:04d}-{sold_ts.month:02d}"
            if sold_ts is not None
            else (period_label or period_date or "")
        )
        display = ", ".join(p for p in [street, city, state, zip_code] if p)
        sold_row = InvestorSoldRow(
            address=display,
            address_key=key,
            street=street,
            city=city,
            state=state,
            zip=zip_code,
            county=_col_val(row, county_col),
            period_date=period_date,
            period_label=period_label,
            sold_month=sold_month,
            buyer_full_name=_col_val(row, buyer_col),
            sale_amount=_col_val(row, amount_col),
            investor=investor,
            in_my_records=in_list,
            segment=segment_for(investor, in_list),
            investor_score=_col_val(row, score_col),
            distressors=_col_val(row, distress_col),
            dataflik_id=_col_val(row, dataflik_col),
            transaction_id=_col_val(row, txn_col),
        )
        ck = _collapse_key(sold_row)
        if ck not in sold_ts_by_collapse or sold_ts_by_collapse[ck] is None:
            sold_ts_by_collapse[ck] = sold_ts
        txn_rows.append(sold_row)

    txn_n = len(txn_rows)
    report(62, "Collapsing multi-txn property rows…")
    rows = collapse_property_month_rows(txn_rows)

    report(68, "Enriching with REISift / QL pipeline…")
    for i, sold_row in enumerate(rows):
        if i % 500 == 0:
            report(68 + int(20 * i / max(len(rows), 1)), f"Enriching… ({i}/{len(rows)})")
        ck = _collapse_key(sold_row)
        hit = reisift_index.get(sold_row.address_key) if sold_row.address_key else None
        _enrich_row(
            sold_row,
            reisift_hit=hit,
            ql_index=ql_index,
            opp_index=opp_index,
            sold_ts=sold_ts_by_collapse.get(ck),
        )

    report(90, "Building rollups…")
    n = len(rows)
    investor_n = sum(1 for r in rows if r.investor)
    in_list_n = sum(1 for r in rows if r.in_my_records)
    both_n = sum(1 for r in rows if r.segment == "both")
    neither_n = sum(1 for r in rows if r.segment == "neither")

    marketed_n = sum(1 for r in rows if r.marketed)
    never_n = n - marketed_n
    lead_n = sum(1 for r in rows if r.lead_matched)
    ql_n = sum(1 for r in rows if r.qualified_lead_matched)
    prospect_n = sum(1 for r in rows if r.prospect_matched)
    opp_n = sum(1 for r in rows if r.opp_matched)
    uc_n = sum(1 for r in rows if r.under_contract_date)
    closed_n = sum(1 for r in rows if r.hhb_closed_date)
    reisift_n = sum(1 for r in rows if r.reisift_matched)

    in_list_investor_n = sum(1 for r in rows if r.in_my_records and r.investor)
    in_list_non_investor_n = sum(1 for r in rows if r.in_my_records and not r.investor)
    had_n = sum(1 for r in rows if r.had_presence)
    had_investor_n = sum(1 for r in rows if r.had_presence and r.investor)
    had_non_investor_n = sum(1 for r in rows if r.had_presence and not r.investor)
    lost_rows = [r for r in rows if is_lost_to_investor(r)]
    lost_n = len(lost_rows)
    lost_pct = _pct(lost_n, had_n)
    lost_stage_counter: Counter[str] = Counter(r.pipeline_stage for r in lost_rows)
    lost_by_stage = [
        {
            "stage": stage,
            "label": PIPELINE_LABELS.get(stage, stage),
            "count": lost_stage_counter.get(stage, 0),
            "share_pct": _pct(lost_stage_counter.get(stage, 0), lost_n),
        }
        for stage in PIPELINE_ORDER
        if lost_stage_counter.get(stage, 0) > 0 or stage in PIPELINE_FUNNEL_ALWAYS
    ]
    had_presence_exits_by_buyer = {
        "investor": had_investor_n,
        "non_investor": had_non_investor_n,
        "lost_to_investor": lost_n,
        "hhb_closed_investor": sum(
            1 for r in rows if r.had_presence and r.investor and r.hhb_closed_date
        ),
        "scrape_in_list_investor": in_list_investor_n,
        "scrape_in_list_non_investor": in_list_non_investor_n,
    }

    total_touches = {
        ch: sum(int(getattr(r, f"{ch.lower()}_touch_count")) for r in rows)
        for ch in TOUCH_CHANNELS
    }
    touch_sum = sum(total_touches.values())
    avg_touches = round(touch_sum / marketed_n, 2) if marketed_n else None

    src_counter = Counter(r.prospect_source for r in rows if r.prospect_matched)
    prospect_sources = {
        "ql": int(src_counter.get("ql", 0)),
        "sf_tag": int(src_counter.get("sf_tag", 0)),
        "podio": int(src_counter.get("podio", 0)),
        "unmatched": n - prospect_n,
    }
    lead_src = Counter(r.lead_source for r in rows if r.lead_matched)
    lead_sources = {
        "sf_tag": int(lead_src.get("sf_tag", 0)),
        "podio": int(lead_src.get("podio", 0)),
    }

    pipe_counter: Counter[str] = Counter(r.pipeline_stage for r in rows)
    pipeline_funnel = [
        {
            "stage": stage,
            "label": PIPELINE_LABELS.get(stage, stage),
            "count": pipe_counter.get(stage, 0),
            "share_pct": _pct(pipe_counter.get(stage, 0), n),
        }
        for stage in PIPELINE_ORDER
        if pipe_counter.get(stage, 0) > 0 or stage in PIPELINE_FUNNEL_ALWAYS
    ]

    by_seg: Dict[str, Dict[str, Any]] = {s: _empty_segment_rollup(s) for s in SEGMENT_IDS}
    lag_by_seg: Dict[str, List[int]] = {s: [] for s in SEGMENT_IDS}
    for r in rows:
        bucket = by_seg[r.segment]
        bucket["count"] += 1
        if r.marketed:
            bucket["marketed"] += 1
        else:
            bucket["never_marketed"] += 1
        if r.lead_matched:
            bucket["leads"] += 1
        if r.qualified_lead_matched:
            bucket["qualified_leads"] += 1
        if r.prospect_matched:
            bucket["prospects"] += 1
            if r.prospect_source == "podio":
                bucket["prospects_podio"] += 1
            elif r.prospect_source == "ql":
                bucket["prospects_ql"] += 1
            elif r.prospect_source == "sf_tag":
                bucket["prospects_sf"] += 1
        if r.opp_matched:
            bucket["opportunities"] += 1
        if r.under_contract_date:
            bucket["under_contract"] += 1
        if r.hhb_closed_date:
            bucket["hhb_closed"] += 1
        if r.months_list_to_sold is not None:
            lag_by_seg[r.segment].append(int(r.months_list_to_sold))
    for seg, bucket in by_seg.items():
        _, med = _mean_median(lag_by_seg[seg])
        bucket["median_months_list_to_sold"] = med
        bucket["marketed_pct"] = _pct(bucket["marketed"], bucket["count"])
        bucket["lead_pct"] = _pct(bucket["leads"], bucket["count"])
        bucket["qualified_lead_pct"] = _pct(bucket["qualified_leads"], bucket["count"])
        bucket["prospect_pct"] = _pct(bucket["prospects"], bucket["count"])

    by_month: Dict[str, Dict[str, Any]] = {}
    by_county: Dict[str, Dict[str, Any]] = {}
    for r in rows:
        mk = r.sold_month or "(unknown)"
        bucket = by_month.setdefault(mk, _empty_rollup("sold_month", mk))
        bucket["count"] += 1
        if r.investor:
            bucket["investor"] += 1
        if r.in_my_records:
            bucket["in_our_list"] += 1
        if r.segment == "both":
            bucket["both"] += 1
        if r.segment == "neither":
            bucket["neither"] += 1
        if r.marketed:
            bucket["marketed"] += 1
        if r.lead_matched:
            bucket["leads"] += 1
        if r.qualified_lead_matched:
            bucket["qualified_leads"] += 1
        if r.prospect_matched:
            bucket["prospects"] += 1
        if r.had_presence:
            bucket["had_presence"] += 1
        if is_lost_to_investor(r):
            bucket["lost_to_investor"] += 1

        ck = r.county or "(unknown)"
        cb = by_county.setdefault(ck, _empty_rollup("county", ck))
        cb["count"] += 1
        if r.investor:
            cb["investor"] += 1
        if r.in_my_records:
            cb["in_our_list"] += 1
        if r.segment == "both":
            cb["both"] += 1
        if r.segment == "neither":
            cb["neither"] += 1
        if r.marketed:
            cb["marketed"] += 1
        if r.lead_matched:
            cb["leads"] += 1
        if r.qualified_lead_matched:
            cb["qualified_leads"] += 1
        if r.prospect_matched:
            cb["prospects"] += 1
        if r.had_presence:
            cb["had_presence"] += 1
        if is_lost_to_investor(r):
            cb["lost_to_investor"] += 1

    months_to_sold = [m for m in (r.months_list_to_sold for r in rows) if m is not None]
    months_to_ql = [
        m for m in (r.months_list_to_qualified_lead for r in rows) if m is not None
    ]
    mean_sold, median_sold = _mean_median(months_to_sold)
    mean_ql, median_ql = _mean_median(months_to_ql)

    if sold_months:
        date_window_start = f"{min(sold_months).year:04d}-{min(sold_months).month:02d}"
        date_window_end = f"{max(sold_months).year:04d}-{max(sold_months).month:02d}"
    else:
        date_window_start = ""
        date_window_end = ""

    multi_txn = sum(1 for r in rows if r.transaction_count > 1)
    methodology_note = (
        "Primary question: lost to another investor = we had it (In My Records scrape OR "
        "REISift/CRM presence: list tags, marketed, Podio/SF lead, QL, opp, UC, Closed) AND "
        "investor AND not HHB closed. Loss rate denominator = properties we had. "
        "Universe = CleanREISift sold_properties_full.csv. Grain = unique property × sold month "
        f"(multi-txn Dataflik rows collapse; {multi_txn:,} properties had >1 txn). "
        f"Canonical pipeline: {CANONICAL_PIPELINE}."
    )

    report(100, "Done")
    return InvestorSoldResult(
        sold_rows_ingested=txn_n,
        property_rows=n,
        unique_addresses=len(unique_keys),
        investor_count=investor_n,
        investor_pct=_pct(investor_n, n),
        in_our_list_count=in_list_n,
        in_our_list_pct=_pct(in_list_n, n),
        both_count=both_n,
        both_pct=_pct(both_n, n),
        neither_count=neither_n,
        neither_pct=_pct(neither_n, n),
        marketed_count=marketed_n,
        marketed_pct=_pct(marketed_n, n),
        never_marketed_count=never_n,
        lead_matched=lead_n,
        lead_rate_pct=_pct(lead_n, n),
        qualified_lead_matched=ql_n,
        qualified_lead_rate_pct=_pct(ql_n, n),
        prospect_matched=prospect_n,
        prospect_rate_pct=_pct(prospect_n, n),
        opp_matched=opp_n,
        opp_rate_pct=_pct(opp_n, n),
        under_contract_count=uc_n,
        hhb_closed_count=closed_n,
        reisift_matched_count=reisift_n,
        lost_to_investor_count=lost_n,
        lost_to_investor_pct=lost_pct,
        had_presence_count=had_n,
        had_presence_investor_count=had_investor_n,
        had_presence_non_investor_count=had_non_investor_n,
        lost_by_stage=lost_by_stage,
        had_presence_exits_by_buyer=had_presence_exits_by_buyer,
        total_touch_counts=total_touches,
        avg_touches_per_marketed=avg_touches,
        mean_months_list_to_sold=mean_sold,
        median_months_list_to_sold=median_sold,
        mean_months_list_to_qualified_lead=mean_ql,
        median_months_list_to_qualified_lead=median_ql,
        mean_months_list_to_prospect=mean_ql,
        median_months_list_to_prospect=median_ql,
        pipeline_funnel=pipeline_funnel,
        prospect_sources=prospect_sources,
        lead_sources=lead_sources,
        by_segment=[by_seg[s] for s in SEGMENT_IDS],
        by_sold_month=sorted(by_month.values(), key=lambda x: x["sold_month"]),
        by_county=sorted(by_county.values(), key=lambda x: (-x["count"], x["county"])),
        rows=rows,
        warnings=warnings,
        methodology_note=methodology_note,
        date_window_start=date_window_start,
        date_window_end=date_window_end,
        enrichment_enabled=True,
    )


def build_export_workbook(result: InvestorSoldResult) -> bytes:
    try:
        import openpyxl  # noqa: F401
    except ImportError as exc:
        raise ValueError("Export requires openpyxl") from exc

    all_rows = [r.to_dict() for r in result.rows]
    summary_rows = [
        {"metric": "Sold transactions ingested", "value": result.sold_rows_ingested},
        {"metric": "Property × month rows", "value": result.property_rows},
        {"metric": "Unique addresses", "value": result.unique_addresses},
        {"metric": "Properties we had (list or CRM)", "value": result.had_presence_count},
        {"metric": "Lost to investor", "value": result.lost_to_investor_count},
        {"metric": "Lost to investor % of we-had", "value": result.lost_to_investor_pct},
        {"metric": "We-had sold to investor", "value": result.had_presence_investor_count},
        {"metric": "We-had sold non-investor", "value": result.had_presence_non_investor_count},
        {"metric": "In Our List (scrape flag)", "value": result.in_our_list_count},
        {"metric": "Investor (market)", "value": result.investor_count},
        {"metric": "Both", "value": result.both_count},
        {"metric": "Neither", "value": result.neither_count},
        {"metric": "Marketed", "value": result.marketed_count},
        {"metric": "Never marketed", "value": result.never_marketed_count},
        {"metric": "Lead matched", "value": result.lead_matched},
        {"metric": "Qualified Lead matched", "value": result.qualified_lead_matched},
        {"metric": "Leads via SF tag", "value": result.lead_sources.get("sf_tag", 0)},
        {"metric": "Leads via Podio", "value": result.lead_sources.get("podio", 0)},
        {"metric": "Opportunity matched", "value": result.opp_matched},
        {"metric": "Under contract", "value": result.under_contract_count},
        {"metric": "Closed", "value": result.hhb_closed_count},
        {"metric": "Median mo list→sold", "value": result.median_months_list_to_sold},
        {"metric": "Methodology", "value": result.methodology_note},
    ]

    bio = BytesIO()
    with pd.ExcelWriter(bio, engine="openpyxl") as writer:
        pd.DataFrame(summary_rows).to_excel(writer, sheet_name="Summary", index=False)
        pd.DataFrame(result.lost_by_stage).to_excel(
            writer, sheet_name="Lost By Stage", index=False
        )
        pd.DataFrame(result.by_segment).to_excel(writer, sheet_name="By Segment", index=False)
        pd.DataFrame(result.pipeline_funnel).to_excel(
            writer, sheet_name="Pipeline Funnel", index=False
        )
        pd.DataFrame(result.by_sold_month).to_excel(writer, sheet_name="By Month", index=False)
        pd.DataFrame(all_rows).to_excel(writer, sheet_name="Journey", index=False)
        pd.DataFrame(
            [r for r in all_rows if r.get("had_presence") and r.get("investor") and not r.get("hhb_closed_date")]
        ).to_excel(writer, sheet_name="Lost To Investor", index=False)
        pd.DataFrame([r for r in all_rows if r.get("investor")]).to_excel(
            writer, sheet_name="Investor", index=False
        )
        pd.DataFrame([r for r in all_rows if r.get("had_presence")]).to_excel(
            writer, sheet_name="We Had", index=False
        )
        pd.DataFrame([r for r in all_rows if r.get("in_my_records")]).to_excel(
            writer, sheet_name="In Our List", index=False
        )
        pd.DataFrame([r for r in all_rows if r.get("segment") == "both"]).to_excel(
            writer, sheet_name="Both", index=False
        )
        pd.DataFrame([r for r in all_rows if not r.get("marketed")]).to_excel(
            writer, sheet_name="Never Marketed", index=False
        )
    return bio.getvalue()
