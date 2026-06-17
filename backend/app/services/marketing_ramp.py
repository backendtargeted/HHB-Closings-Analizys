"""
Marketing ramp report: QL + closings population union merged by address, enriched with REISift tags.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

from .analysis import parse_tags, _dedupe_parsed_tag_events
from .closing_resolution import filter_closings_by_stage, resolve_milestones_from_parsed
from .marketing_mapper import find_column_name, make_address_key, smart_read_csv
from .monthly_consolidated import load_reisift_file, REISIFT_ADDR
from .qualified_leads import (
    file_span_from_df,
    load_qualified_leads_file,
    parse_ymd_param,
    rollup_channel,
    validate_and_prepare,
)

REPORT_TYPE = "marketing_ramp"

NO_CLEAR_SOURCE = "No Clear Source"
TOUCH_CHANNELS = ("CC", "SMS", "DM")

SF_ADDR = {
    "street": ["Street", "Mailing address", "Property address", "Property Address"],
    "city": ["City", "Mailing city", "Property city"],
    "state": ["State/Province", "State", "Mailing state", "Property state"],
    "zip": ["Zip/Postal Code", "Zip", "Mailing zip", "Property zip"],
}

CLOSINGS_ADDR = {
    "street": ["Address", "Property address", "Street", "Property Address"],
    "city": ["City", "Property city", "Mailing city"],
    "state": ["State", "Property state", "State/Province", "Mailing state"],
    "zip": ["Zip", "Zip Code", "Property zip", "Zip/Postal Code", "Mailing zip"],
}

DATE_CLOSED_CANDIDATES = ["Date Closed", "Closing Date", "Close Date", "date closed"]
STAGE_CANDIDATES = ["Stage", "stage", "Deal Stage", "Status", "Opportunity Stage"]


def _date_to_ymd(d: date) -> str:
    return d.isoformat()


def _parse_iso_dt(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def _days_between(start: Optional[datetime], end: Optional[datetime]) -> Optional[int]:
    if start is None or end is None:
        return None
    return (end - start).days


def _col_val(row: pd.Series, col: Optional[str]) -> str:
    if not col or col not in row.index or pd.isna(row[col]):
        return ""
    return str(row[col]).strip()


def _discover_addr_cols(df: pd.DataFrame, mapping: Dict[str, List[str]]) -> Dict[str, Optional[str]]:
    return {k: find_column_name(df, v) for k, v in mapping.items()}


def _address_key_from_row(row: pd.Series, cols: Dict[str, Optional[str]]) -> str:
    return make_address_key(
        _col_val(row, cols.get("street")),
        _col_val(row, cols.get("city")),
        _col_val(row, cols.get("state")),
        _col_val(row, cols.get("zip")),
    )


def load_closings_file(file_path: str) -> pd.DataFrame:
    path = Path(file_path)
    suffix = path.suffix.lower()
    if suffix in (".xlsx", ".xls"):
        try:
            return pd.read_excel(file_path, engine="openpyxl")
        except ImportError as exc:
            raise ValueError("Reading Excel requires openpyxl: pip install openpyxl") from exc
    if suffix == ".csv":
        return smart_read_csv(file_path)
    raise ValueError(f"Unsupported closings file type: {suffix or '(none)'}. Use .xlsx or .csv")


def _parse_tags_merged(tags_str: str) -> List[Dict[str, Any]]:
    return _dedupe_parsed_tag_events(parse_tags(tags_str))


def _earliest_list_purchase(parsed: List[Dict[str, Any]]) -> Optional[datetime]:
    dates: List[datetime] = []
    for p in parsed:
        if p.get("type") != "list_purchase":
            continue
        dt = _parse_iso_dt(str(p.get("date", "")))
        if dt is not None:
            dates.append(dt)
    return min(dates) if dates else None


def _contact_touch_stats(parsed: List[Dict[str, Any]]) -> Tuple[Dict[str, int], Optional[str], Optional[str]]:
    """Count CC/SMS/DM contact tags; return first touch channel and date (earliest)."""
    counts = {ch: 0 for ch in TOUCH_CHANNELS}
    touches: List[Tuple[datetime, str]] = []
    for p in parsed:
        if p.get("type") != "contact":
            continue
        ch = str(p.get("channel") or p.get("label") or "").upper()
        if ch not in counts:
            continue
        counts[ch] += 1
        dt = _parse_iso_dt(str(p.get("date", "")))
        if dt is not None:
            touches.append((dt, ch))
    if not touches:
        return counts, None, None
    touches.sort(key=lambda x: x[0])
    first_dt, first_ch = touches[0]
    return counts, first_ch, first_dt.isoformat()


def _merge_reisift_index(df: pd.DataFrame) -> Dict[str, Dict[str, Any]]:
    """Full-file REISift index: address_key -> merged tags + address fields."""
    tags_col = find_column_name(df, ["Tags"])
    if not tags_col:
        raise ValueError("Missing required column: Tags")
    addr_cols = _discover_addr_cols(df, REISIFT_ADDR)
    index: Dict[str, Dict[str, Any]] = {}
    for _, row in df.iterrows():
        key = _address_key_from_row(row, addr_cols)
        if not key or key == "|||":
            continue
        tags_part = str(row[tags_col]).strip() if pd.notna(row[tags_col]) else ""
        entry = index.get(key)
        if entry is None:
            index[key] = {
                "tags": tags_part,
                "street": _col_val(row, addr_cols.get("street")),
                "city": _col_val(row, addr_cols.get("city")),
                "state": _col_val(row, addr_cols.get("state")),
                "zip": _col_val(row, addr_cols.get("zip")),
            }
        else:
            if tags_part:
                existing = entry["tags"]
                entry["tags"] = f"{existing},{tags_part}" if existing else tags_part
            for fld in ("street", "city", "state", "zip"):
                if not entry.get(fld):
                    entry[fld] = _col_val(row, addr_cols.get(fld))
    return index


def _build_ql_population(
    df: pd.DataFrame,
    start: date,
    end: date,
) -> Tuple[Dict[str, Dict[str, Any]], int, int]:
    prepared, lead_col, create_col = validate_and_prepare(df)
    addr_cols = _discover_addr_cols(prepared, SF_ADDR)
    window_start = pd.Timestamp(start)
    window_end = pd.Timestamp(end) + pd.Timedelta(days=1) - pd.Timedelta(microseconds=1)

    valid_mask = prepared["_create_date_parsed"].notna()
    in_window = valid_mask & (
        prepared["_create_date_parsed"] >= window_start
    ) & (prepared["_create_date_parsed"] <= window_end)

    pop: Dict[str, Dict[str, Any]] = {}
    for idx, row in prepared.loc[in_window].iterrows():
        key = _address_key_from_row(row, addr_cols)
        if not key or key == "|||":
            continue
        create_dt = row["_create_date_parsed"]
        create_ymd = _date_to_ymd(create_dt.date())
        channel = row["_reporting_channel"]
        lead_source = row["_lead_source_raw"]
        entry = {
            "address_key": key,
            "street": _col_val(row, addr_cols.get("street")),
            "city": _col_val(row, addr_cols.get("city")),
            "state": _col_val(row, addr_cols.get("state")),
            "zip": _col_val(row, addr_cols.get("zip")),
            "create_date": create_ymd,
            "reporting_channel": str(channel),
            "lead_source_raw": lead_source,
            "create_dt": create_dt,
        }
        existing = pop.get(key)
        if existing is None or create_dt < existing["create_dt"]:
            pop[key] = entry

    total_file = len(prepared)
    in_window_count = int(in_window.sum())
    return pop, total_file, in_window_count


def _build_closings_population(
    df: pd.DataFrame,
    start: date,
    end: date,
) -> Tuple[Dict[str, Dict[str, Any]], int, int]:
    filtered = filter_closings_by_stage(df)
    date_col = find_column_name(filtered, DATE_CLOSED_CANDIDATES)
    if not date_col:
        raise ValueError("Closings file must include Date Closed (or Closing Date / Close Date).")
    addr_cols = _discover_addr_cols(filtered, CLOSINGS_ADDR)
    if not addr_cols.get("street"):
        raise ValueError("Closings file must include Address (or Property address / Street).")

    window_start = pd.Timestamp(start)
    window_end = pd.Timestamp(end) + pd.Timedelta(days=1) - pd.Timedelta(microseconds=1)

    pop: Dict[str, Dict[str, Any]] = {}
    in_window_count = 0
    for _, row in filtered.iterrows():
        closed = pd.to_datetime(row[date_col], errors="coerce")
        if pd.isna(closed):
            continue
        if closed < window_start or closed > window_end:
            continue
        in_window_count += 1
        key = _address_key_from_row(row, addr_cols)
        if not key or key == "|||":
            continue
        stage_col = find_column_name(filtered, STAGE_CANDIDATES)
        stage_val = _col_val(row, stage_col) if stage_col else ""
        entry = {
            "address_key": key,
            "street": _col_val(row, addr_cols.get("street")),
            "city": _col_val(row, addr_cols.get("city")),
            "state": _col_val(row, addr_cols.get("state")),
            "zip": _col_val(row, addr_cols.get("zip")),
            "date_closed": closed,
            "date_closed_ymd": _date_to_ymd(closed.date()),
            "stage": stage_val,
        }
        existing = pop.get(key)
        if existing is None or closed < existing["date_closed"]:
            pop[key] = entry

    return pop, len(filtered), in_window_count


@dataclass
class MarketingRampResult:
    metrics: Dict[str, Any]
    rows: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {"metrics": self.metrics, "rows": self.rows}


def analyze(
    qualified_leads_path: str,
    reisift_path: str,
    closings_path: str,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    use_full_file_span: bool = False,
) -> MarketingRampResult:
    ql_df = load_qualified_leads_file(qualified_leads_path)
    closings_df = load_closings_file(closings_path)
    reisift_df = load_reisift_file(reisift_path)

    if use_full_file_span:
        span_min, span_max = file_span_from_df(ql_df)
        closings_filtered = filter_closings_by_stage(closings_df)
        date_col = find_column_name(closings_filtered, DATE_CLOSED_CANDIDATES)
        if date_col:
            closed_series = pd.to_datetime(closings_filtered[date_col], errors="coerce").dropna()
            if not closed_series.empty:
                cmin, cmax = closed_series.min().date(), closed_series.max().date()
                if span_min is None:
                    span_min = cmin
                else:
                    span_min = min(span_min, cmin)
                if span_max is None:
                    span_max = cmax
                else:
                    span_max = max(span_max, cmax)
        if span_min is None or span_max is None:
            raise ValueError(
                "No parseable Create Date or Date Closed values; cannot use full file span"
            )
        start_date = span_min
        end_date = span_max

    if start_date is None or end_date is None:
        raise ValueError("start_date and end_date are required unless use_full_file_span is true")
    if start_date > end_date:
        raise ValueError("start_date must be on or before end_date")

    ql_pop, ql_total, ql_in_window = _build_ql_population(ql_df, start_date, end_date)
    closings_pop, closings_total, closings_in_window = _build_closings_population(
        closings_df, start_date, end_date
    )
    reisift_index = _merge_reisift_index(reisift_df)

    all_keys = set(ql_pop.keys()) | set(closings_pop.keys())
    anchor_dt = datetime.combine(end_date, datetime.min.time())
    anchor_ymd = _date_to_ymd(end_date)

    rows: List[Dict[str, Any]] = []
    channel_counts: Dict[str, int] = {}
    touch_counts: Dict[str, int] = {ch: 0 for ch in TOUCH_CHANNELS}
    opportunity_counts: Dict[str, int] = {"under_contract": 0}
    reisift_matched = 0
    warnings: List[str] = []

    for key in sorted(all_keys):
        in_ql = key in ql_pop
        in_closing = key in closings_pop
        if in_ql and in_closing:
            population_kind = "both"
        elif in_ql:
            population_kind = "qualified_only"
        else:
            population_kind = "closing_only"

        ql_entry = ql_pop.get(key)
        closing_entry = closings_pop.get(key)
        reisift_entry = reisift_index.get(key)

        street = ""
        city = ""
        state = ""
        zip_code = ""
        for src in (ql_entry, closing_entry, reisift_entry):
            if not src:
                continue
            street = street or src.get("street", "")
            city = city or src.get("city", "")
            state = state or src.get("state", "")
            zip_code = zip_code or src.get("zip", "")

        if population_kind == "closing_only":
            reporting_channel = NO_CLEAR_SOURCE
            create_date = ""
            create_dt: Optional[pd.Timestamp] = None
        else:
            reporting_channel = ql_entry["reporting_channel"]
            create_date = ql_entry["create_date"]
            create_dt = ql_entry["create_dt"]

        channel_counts[reporting_channel] = channel_counts.get(reporting_channel, 0) + 1

        workbook_close: Optional[datetime] = None
        date_closed_ymd = ""
        close_date_source = ""
        if closing_entry:
            workbook_close = closing_entry["date_closed"].to_pydatetime()
            date_closed_ymd = closing_entry["date_closed_ymd"]
            close_date_source = "closings_workbook"

        parsed: List[Dict[str, Any]] = []
        if reisift_entry and reisift_entry.get("tags"):
            parsed = _parse_tags_merged(reisift_entry["tags"])
            reisift_matched += 1

        milestones = resolve_milestones_from_parsed(
            parsed,
            workbook_close=workbook_close,
        )
        if milestones.date_closed and not date_closed_ymd:
            date_closed_ymd = milestones.date_closed.date().isoformat()
            close_date_source = milestones.close_source or "closed_tag"
        elif milestones.date_closed and workbook_close:
            close_date_source = milestones.close_source or close_date_source

        date_under_contract_ymd = ""
        if milestones.date_under_contract:
            date_under_contract_ymd = milestones.date_under_contract.date().isoformat()
            opportunity_counts["under_contract"] += 1

        list_dt = _earliest_list_purchase(parsed)
        list_purchase_ymd = list_dt.date().isoformat() if list_dt else ""

        touch_channel_counts, first_touch_channel, first_touch_date = _contact_touch_stats(parsed)
        if first_touch_channel:
            touch_counts[first_touch_channel] += 1

        create_dt_py: Optional[datetime] = None
        if create_dt is not None and not pd.isna(create_dt):
            create_dt_py = create_dt.to_pydatetime()

        close_dt_py = milestones.date_closed or workbook_close
        contract_dt_py = milestones.date_under_contract
        first_touch_dt_py = _parse_iso_dt(first_touch_date)

        row: Dict[str, Any] = {
            "address_key": key,
            "street": street,
            "city": city,
            "state": state,
            "zip": zip_code,
            "population_kind": population_kind,
            "reporting_channel": reporting_channel,
            "create_date": create_date,
            "date_closed": date_closed_ymd,
            "date_under_contract": date_under_contract_ymd,
            "list_purchase_date": list_purchase_ymd,
            "report_anchor_date": anchor_ymd,
            "first_touch_channel": first_touch_channel or "",
            "first_touch_date": first_touch_date or "",
            "cc_touch_count": touch_channel_counts["CC"],
            "sms_touch_count": touch_channel_counts["SMS"],
            "dm_touch_count": touch_channel_counts["DM"],
            "days_list_to_first_touch": _days_between(list_dt, first_touch_dt_py),
            "days_list_to_create_date": _days_between(list_dt, create_dt_py),
            "days_list_to_under_contract": _days_between(list_dt, contract_dt_py),
            "days_list_to_close": _days_between(list_dt, close_dt_py),
            "days_create_to_close": _days_between(create_dt_py, close_dt_py),
            "days_since_list_to_anchor": _days_between(list_dt, anchor_dt),
            "has_reisift_match": bool(reisift_entry),
            "close_date_source": close_date_source,
            "has_contract_sf_tag": milestones.has_contract_sf_tag,
        }
        rows.append(row)

    population_total = len(all_keys)
    reisift_unmatched = population_total - reisift_matched
    match_rate = round(100.0 * reisift_matched / population_total, 2) if population_total else 0.0

    total_touch_counts = {
        ch: sum(int(r[f"{ch.lower()}_touch_count"]) for r in rows) for ch in TOUCH_CHANNELS
    }

    metrics = {
        "report_type": REPORT_TYPE,
        "date_window_start": _date_to_ymd(start_date),
        "date_window_end": _date_to_ymd(end_date),
        "population_counts": {
            "qualified_leads_total": ql_total,
            "qualified_leads_in_window": ql_in_window,
            "closings_total": closings_total,
            "closings_in_window": closings_in_window,
            "population_rows": population_total,
            "qualified_only": sum(1 for r in rows if r["population_kind"] == "qualified_only"),
            "closing_only": sum(1 for r in rows if r["population_kind"] == "closing_only"),
            "both": sum(1 for r in rows if r["population_kind"] == "both"),
            "reisift_rows": len(reisift_df),
        },
        "reisift_match": {
            "matched": reisift_matched,
            "unmatched": reisift_unmatched,
            "match_rate_pct": match_rate,
        },
        "channel_counts": channel_counts,
        "touch_counts": touch_counts,
        "total_touch_counts": total_touch_counts,
        "opportunity_counts": opportunity_counts,
        "warnings": warnings,
        "methodology_note": (
            "Population is the union of qualified leads (Create Date in window) and closings "
            "(Date Closed in window, Closed Lost excluded), merged by normalized address. "
            "REISift tags are indexed from the full export. Total touches sum all (8020) CC/SMS/DM "
            "contact tags per address; touch_counts is first-touch distribution per population row. "
            "Under contract uses SF converted/under contract labels only. "
            "Close date prefers closings workbook Date Closed, then (CLOSED) tag. "
            "Recency anchor is earliest List Purchased 8020 tag; report_anchor_date is window end."
        ),
    }
    return MarketingRampResult(metrics=metrics, rows=rows)


def analyze_files(
    qualified_leads_path: str,
    reisift_path: str,
    closings_path: str,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    use_full_file_span: bool = False,
) -> MarketingRampResult:
    return analyze(
        qualified_leads_path,
        reisift_path,
        closings_path,
        start_date=start_date,
        end_date=end_date,
        use_full_file_span=use_full_file_span,
    )


def rows_to_export_csv(rows: List[Dict[str, Any]]) -> str:
    if not rows:
        return ""
    return pd.DataFrame(rows).to_csv(index=False)
