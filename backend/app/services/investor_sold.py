"""
Gate 8 — Investor & In-List Sold (CleanREISift sold_properties_full.csv).

Universe: scraped sold transactions with investor / in_my_records flags.
Optional REISift + QL + Opportunities enrich in-list (and other) rows with
marketing / prospect / opp depth using Gate 6 match helpers.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from io import BytesIO
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

import pandas as pd

from .analysis import _dedupe_parsed_tag_events, parse_tags
from .closing_resolution import resolve_milestones_from_parsed
from .lifecycle import build_events, compute_stage_funnel_open, get_highest_stage
from .marketing_mapper import find_column_name, make_address_key, smart_read_csv
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
)
from .qualified_leads import CREATE_DATE_CANDIDATES
from .sold_properties import (
    PIPELINE_LABELS,
    REISIFT_PHONE_CANDIDATES,
    _contact_touch_stats,
    _earliest_list_purchase,
    _first_podio_crm_date,
    _iso_day,
    _max_pipeline,
    _month_end,
    _pct,
    _pipeline_rank,
    _podio_crm_present,
    _sf_engaged_before,
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
    segment: str = "neither"
    investor_score: str = ""
    distressors: str = ""
    dataflik_id: str = ""
    transaction_id: str = ""
    transaction_count: int = 1
    reisift_matched: bool = False
    marketed: bool = False
    cc_touch_count: int = 0
    sms_touch_count: int = 0
    dm_touch_count: int = 0
    prospect_matched: bool = False
    prospect_date: str = ""
    prospect_source: str = ""
    opp_matched: bool = False
    opp_created_date: str = ""
    under_contract_date: str = ""
    hhb_closed_date: str = ""
    pipeline_stage: str = "NONE"
    pipeline_stage_label: str = ""

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
            "segment": self.segment,
            "investor_score": self.investor_score,
            "distressors": self.distressors,
            "dataflik_id": self.dataflik_id,
            "transaction_id": self.transaction_id,
            "transaction_count": self.transaction_count,
            "reisift_matched": self.reisift_matched,
            "marketed": self.marketed,
            "cc_touch_count": self.cc_touch_count,
            "sms_touch_count": self.sms_touch_count,
            "dm_touch_count": self.dm_touch_count,
            "prospect_matched": self.prospect_matched,
            "prospect_date": self.prospect_date,
            "prospect_source": self.prospect_source,
            "opp_matched": self.opp_matched,
            "opp_created_date": self.opp_created_date,
            "under_contract_date": self.under_contract_date,
            "hhb_closed_date": self.hhb_closed_date,
            "pipeline_stage": self.pipeline_stage,
            "pipeline_stage_label": self.pipeline_stage_label,
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
    reisift_matched_count: int = 0
    marketed_count: int = 0
    prospect_matched: int = 0
    opp_matched: int = 0
    by_sold_month: List[Dict[str, Any]] = field(default_factory=list)
    by_county: List[Dict[str, Any]] = field(default_factory=list)
    rows: List[InvestorSoldRow] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    methodology_note: str = ""
    date_window_start: str = ""
    date_window_end: str = ""
    enrichment_enabled: bool = False

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
            "enrichment": {
                "reisift_matched_count": self.reisift_matched_count,
                "marketed_count": self.marketed_count,
                "prospect_matched": self.prospect_matched,
                "opp_matched": self.opp_matched,
            },
            "by_sold_month": self.by_sold_month,
            "by_county": self.by_county,
            "rows": [r.to_dict() for r in self.rows],
            "warnings": self.warnings,
            "methodology_note": self.methodology_note,
        }


def _collapse_key(row: InvestorSoldRow) -> str:
    """One property × sold month: prefer dataflik_id, else address_key."""
    month = row.sold_month or "(unknown)"
    if row.dataflik_id:
        return f"df:{row.dataflik_id}|{month}"
    if row.address_key:
        return f"ak:{row.address_key}|{month}"
    return f"addr:{row.address.lower()}|{month}|{row.sale_amount}|{row.buyer_full_name}"


def _pipeline_better(a: str, b: str) -> str:
    return a if _pipeline_rank(a) >= _pipeline_rank(b) else b


def collapse_property_month_rows(txn_rows: List[InvestorSoldRow]) -> List[InvestorSoldRow]:
    """Collapse Dataflik multi-txn duplicates to one row per property×sold month."""
    groups: Dict[str, InvestorSoldRow] = {}
    order: List[str] = []
    for row in txn_rows:
        key = _collapse_key(row)
        if key not in groups:
            row.transaction_count = 1
            if not row.pipeline_stage_label and row.pipeline_stage:
                row.pipeline_stage_label = PIPELINE_LABELS.get(
                    row.pipeline_stage, row.pipeline_stage
                )
            groups[key] = row
            order.append(key)
            continue
        base = groups[key]
        base.transaction_count += 1
        base.investor = base.investor or row.investor
        base.in_my_records = base.in_my_records or row.in_my_records
        base.segment = segment_for(base.investor, base.in_my_records)
        base.reisift_matched = base.reisift_matched or row.reisift_matched
        base.marketed = base.marketed or row.marketed
        base.prospect_matched = base.prospect_matched or row.prospect_matched
        base.opp_matched = base.opp_matched or row.opp_matched
        base.cc_touch_count = max(base.cc_touch_count, row.cc_touch_count)
        base.sms_touch_count = max(base.sms_touch_count, row.sms_touch_count)
        base.dm_touch_count = max(base.dm_touch_count, row.dm_touch_count)
        if not base.prospect_date and row.prospect_date:
            base.prospect_date = row.prospect_date
            base.prospect_source = row.prospect_source
        if not base.opp_created_date and row.opp_created_date:
            base.opp_created_date = row.opp_created_date
        if not base.under_contract_date and row.under_contract_date:
            base.under_contract_date = row.under_contract_date
        if not base.hhb_closed_date and row.hhb_closed_date:
            base.hhb_closed_date = row.hhb_closed_date
        better = _pipeline_better(base.pipeline_stage, row.pipeline_stage)
        if better != base.pipeline_stage:
            base.pipeline_stage = better
            base.pipeline_stage_label = PIPELINE_LABELS.get(better, better)
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
        "reisift_matched",
        "marketed",
        "prospect_matched",
        "opp_matched",
    ):
        out[b] = bool(out.get(b))
    for i in ("cc_touch_count", "sms_touch_count", "dm_touch_count", "transaction_count"):
        out[i] = int(out.get(i) or (1 if i == "transaction_count" else 0))
    for s in allowed - {
        "investor",
        "in_my_records",
        "reisift_matched",
        "marketed",
        "prospect_matched",
        "opp_matched",
        "cc_touch_count",
        "sms_touch_count",
        "dm_touch_count",
        "transaction_count",
    }:
        out[s] = str(out.get(s) or "")
    return out


def result_from_metrics_dict(metrics: Dict[str, Any]) -> InvestorSoldResult:
    rows = [InvestorSoldRow(**_row_kwargs(item)) for item in metrics.get("rows") or []]
    inputs = metrics.get("inputs") or {}
    segments = metrics.get("segments") or {}
    enrichment = metrics.get("enrichment") or {}
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
        reisift_matched_count=int(enrichment.get("reisift_matched_count") or 0),
        marketed_count=int(enrichment.get("marketed_count") or 0),
        prospect_matched=int(enrichment.get("prospect_matched") or 0),
        opp_matched=int(enrichment.get("opp_matched") or 0),
        by_sold_month=list(metrics.get("by_sold_month") or []),
        by_county=list(metrics.get("by_county") or []),
        rows=rows,
        warnings=list(metrics.get("warnings") or []),
        methodology_note=str(metrics.get("methodology_note") or ""),
        date_window_start=str(metrics.get("date_window_start") or ""),
        date_window_end=str(metrics.get("date_window_end") or ""),
        enrichment_enabled=bool(inputs.get("enrichment_enabled")),
    )


def _empty_rollup(key_name: str, key: str) -> Dict[str, Any]:
    return {
        key_name: key,
        "count": 0,
        "investor": 0,
        "in_our_list": 0,
        "both": 0,
        "neither": 0,
    }


def _build_reisift_index(
    reisift_df: pd.DataFrame,
) -> Tuple[Dict[str, Dict[str, Any]], Optional[str]]:
    """Map make_address_key → first matching REISift row payload."""
    tags_col = find_column_name(reisift_df, TAGS_CANDIDATES)
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
        tags_val = str(row.get(tags_col, "") or "").strip() if tags_col else ""
        index[key] = {
            "tags": tags_val,
            "phones": _phones_from_row(row, REISIFT_PHONE_CANDIDATES),
        }
    return index, tags_col


def _enrich_row(
    sold_row: InvestorSoldRow,
    *,
    reisift_hit: Optional[Dict[str, Any]],
    ql_index: Optional[MatchIndex],
    opp_index: Optional[MatchIndex],
    sold_ts: Optional[pd.Timestamp],
) -> None:
    if not reisift_hit:
        return
    sold_row.reisift_matched = True
    tags_val = str(reisift_hit.get("tags") or "")
    parsed = _dedupe_parsed_tag_events(parse_tags(tags_val)) if tags_val else []
    phones = list(reisift_hit.get("phones") or [])

    sold_end = _month_end(sold_ts) if sold_ts is not None else None
    sold_end_dt = sold_end.to_pydatetime() if sold_end is not None else None

    touch_counts, _, _ = _contact_touch_stats(parsed, on_or_before=sold_end_dt)
    sold_row.cc_touch_count = touch_counts.get("CC", 0)
    sold_row.sms_touch_count = touch_counts.get("SMS", 0)
    sold_row.dm_touch_count = touch_counts.get("DM", 0)
    sold_row.marketed = sum(touch_counts.values()) > 0

    list_dt = _earliest_list_purchase(parsed)
    first_list_month = (
        pd.Timestamp(year=list_dt.year, month=list_dt.month, day=1) if list_dt else None
    )

    pipeline = "ON_LIST" if list_dt or sold_row.in_my_records else "NONE"
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
        pipeline = _max_pipeline(pipeline, "UNDER_CONTRACT")

    before = (sold_end + pd.Timedelta(days=1)) if sold_end is not None else None
    if ql_index is not None:
        ql_hit = _best_hit(
            ql_index,
            sold_row.address_key,
            phones,
            on_or_after=first_list_month,
            before=before,
        )
        prospect_from_ql = ql_hit is not None and ql_hit.date is not None
    else:
        ql_hit = None
        prospect_from_ql = False

    prospect_from_sf = (
        _sf_engaged_before(parsed, sold_end_dt) if sold_end_dt is not None else False
    )
    prospect_from_podio = _podio_crm_present(parsed)
    sold_row.prospect_matched = prospect_from_ql or prospect_from_sf or prospect_from_podio
    if prospect_from_ql and ql_hit is not None:
        sold_row.prospect_date = _iso_day(ql_hit.date)
        sold_row.prospect_source = "ql"
        pipeline = _max_pipeline(pipeline, "PROSPECT")
    elif prospect_from_sf:
        sold_row.prospect_source = "sf_tag"
        pipeline = _max_pipeline(pipeline, "PROSPECT")
    elif prospect_from_podio:
        sold_row.prospect_date = _first_podio_crm_date(parsed)
        sold_row.prospect_source = "podio"
        pipeline = _max_pipeline(pipeline, "PROSPECT")

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

    highest = get_highest_stage(stages)
    if highest == "CLOSED":
        pipeline = _max_pipeline(pipeline, "HHB_CLOSED")
    sold_row.pipeline_stage = pipeline
    sold_row.pipeline_stage_label = PIPELINE_LABELS.get(pipeline, pipeline)


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

    enrichment_enabled = bool(reisift_path)
    reisift_index: Dict[str, Dict[str, Any]] = {}
    ql_index: Optional[MatchIndex] = None
    opp_index: Optional[MatchIndex] = None

    if reisift_path:
        report(15, "Loading REISift export for enrichment…")
        reisift_df = load_reisift_file(reisift_path)
        reisift_index, _ = _build_reisift_index(reisift_df)
        if not reisift_index:
            warnings.append("REISift upload produced no address keys — enrichment skipped.")
            enrichment_enabled = False
        if ql_path:
            report(22, "Loading Salesforce qualified leads…")
            ql_index = _build_match_index(
                _load_crm_file(ql_path),
                QL_ADDR,
                list(CREATE_DATE_CANDIDATES),
                QL_PHONE_CANDIDATES,
            )
        else:
            warnings.append("QL file not uploaded — Prospect enrichment limited to REISift tags.")
        if opportunities_path:
            report(28, "Loading opportunities…")
            opp_index = _build_match_index(
                _load_crm_file(opportunities_path), OPP_ADDR, OPP_DATE_CANDIDATES
            )
        else:
            warnings.append("Opportunities file not uploaded — Opportunity counts will be zero.")
    else:
        warnings.append(
            "REISift not uploaded — segment counts only (no marketed/prospect enrichment)."
        )
        if ql_path or opportunities_path:
            warnings.append("QL/Opportunities ignored without a REISift export to join on.")

    report(35, "Scoring sold segments…")
    rows: List[InvestorSoldRow] = []
    unique_keys: set[str] = set()
    sold_months: List[pd.Timestamp] = []
    total = len(sold_df)

    for i, (_, row) in enumerate(sold_df.iterrows()):
        if total and i % 2000 == 0:
            report(35 + int(45 * i / max(total, 1)), f"Scanning sold rows… ({i}/{total})")

        street = _col_val(row, addr_cols.get("street"))
        city = _col_val(row, addr_cols.get("city"))
        state = _col_val(row, addr_cols.get("state"))
        zip_code = _col_val(row, addr_cols.get("zip"))
        key = make_address_key(street, city, state, zip_code)
        if key:
            unique_keys.add(key)

        investor = _as_bool(row.get(investor_col))
        in_list = _as_bool(row.get(in_list_col))
        segment = segment_for(investor, in_list)

        period_date = _col_val(row, period_date_col)
        period_label = _col_val(row, period_label_col)
        sold_ts = None
        if period_date:
            sold_ts = parse_sold_month(period_date)
            if sold_ts is None:
                parsed = pd.to_datetime(period_date, errors="coerce")
                if pd.notna(parsed):
                    sold_ts = pd.Timestamp(year=int(parsed.year), month=int(parsed.month), day=1)
        if sold_ts is None and period_label:
            sold_ts = parse_sold_month(period_label)
        if sold_ts is not None:
            sold_months.append(sold_ts)

        sold_month = (
            f"{sold_ts.year:04d}-{sold_ts.month:02d}"
            if sold_ts is not None
            else (period_label or period_date or "")
        )

        parts = [street, city, state, zip_code]
        display = ", ".join(p for p in parts if p)

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
            segment=segment,
            investor_score=_col_val(row, score_col),
            distressors=_col_val(row, distress_col),
            dataflik_id=_col_val(row, dataflik_col),
            transaction_id=_col_val(row, txn_col),
        )

        if enrichment_enabled and key:
            _enrich_row(
                sold_row,
                reisift_hit=reisift_index.get(key),
                ql_index=ql_index,
                opp_index=opp_index,
                sold_ts=sold_ts,
            )

        rows.append(sold_row)

    txn_n = len(rows)
    report(82, "Collapsing multi-txn property rows…")
    rows = collapse_property_month_rows(rows)

    report(88, "Building rollups…")
    n = len(rows)
    investor_n = sum(1 for r in rows if r.investor)
    in_list_n = sum(1 for r in rows if r.in_my_records)
    both_n = sum(1 for r in rows if r.segment == "both")
    neither_n = sum(1 for r in rows if r.segment == "neither")

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

    if sold_months:
        date_window_start = f"{min(sold_months).year:04d}-{min(sold_months).month:02d}"
        date_window_end = f"{max(sold_months).year:04d}-{max(sold_months).month:02d}"
    else:
        date_window_start = ""
        date_window_end = ""

    multi_txn = sum(1 for r in rows if r.transaction_count > 1)
    methodology_note = (
        "Universe = CleanREISift sold_properties_full.csv (Dataflik All Transactions). "
        "Report grain = unique property × sold month (dataflik_id + month, else address_key + month). "
        "Dataflik often returns multiple transaction_ids for the same property sale — those collapse "
        f"into one row with transaction_count (this run: {multi_txn:,} properties had >1 txn). "
        "investor = Investor tab match; in_my_records = In My Records. "
        "Segments: Investor, In Our List, Both, Neither. Optional REISift+QL+Opps enrich matched "
        "addresses with marketing / pipeline depth on/before the sold month (same clocks as Gate 6)."
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
        reisift_matched_count=sum(1 for r in rows if r.reisift_matched),
        marketed_count=sum(1 for r in rows if r.marketed),
        prospect_matched=sum(1 for r in rows if r.prospect_matched),
        opp_matched=sum(1 for r in rows if r.opp_matched),
        by_sold_month=sorted(by_month.values(), key=lambda x: x["sold_month"]),
        by_county=sorted(by_county.values(), key=lambda x: (-x["count"], x["county"])),
        rows=rows,
        warnings=warnings,
        methodology_note=methodology_note,
        date_window_start=date_window_start,
        date_window_end=date_window_end,
        enrichment_enabled=enrichment_enabled,
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
        {"metric": "Investor", "value": result.investor_count},
        {"metric": "Investor %", "value": result.investor_pct},
        {"metric": "In Our List", "value": result.in_our_list_count},
        {"metric": "In Our List %", "value": result.in_our_list_pct},
        {"metric": "Both", "value": result.both_count},
        {"metric": "Both %", "value": result.both_pct},
        {"metric": "Neither", "value": result.neither_count},
        {"metric": "Neither %", "value": result.neither_pct},
        {"metric": "REISift matched", "value": result.reisift_matched_count},
        {"metric": "Marketed", "value": result.marketed_count},
        {"metric": "Prospect matched", "value": result.prospect_matched},
        {"metric": "Opp matched", "value": result.opp_matched},
        {"metric": "Date window start", "value": result.date_window_start},
        {"metric": "Date window end", "value": result.date_window_end},
        {"metric": "Methodology", "value": result.methodology_note},
    ]

    bio = BytesIO()
    with pd.ExcelWriter(bio, engine="openpyxl") as writer:
        pd.DataFrame(summary_rows).to_excel(writer, sheet_name="Summary", index=False)
        pd.DataFrame(result.by_sold_month).to_excel(writer, sheet_name="By Month", index=False)
        pd.DataFrame(result.by_county).to_excel(writer, sheet_name="By County", index=False)
        pd.DataFrame([r for r in all_rows if r.get("investor")]).to_excel(
            writer, sheet_name="Investor", index=False
        )
        pd.DataFrame([r for r in all_rows if r.get("in_my_records")]).to_excel(
            writer, sheet_name="In Our List", index=False
        )
        pd.DataFrame([r for r in all_rows if r.get("segment") == "both"]).to_excel(
            writer, sheet_name="Both", index=False
        )
        pd.DataFrame(all_rows).to_excel(writer, sheet_name="All Rows", index=False)
    return bio.getvalue()
