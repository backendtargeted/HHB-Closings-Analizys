"""
Salesforce Total Qualified Leads export — one-time consolidation metrics.

Every row in the export counts as one qualified lead (report boundary).
Rates are channel share of posted-in-window leads (Create Date filter).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

from .marketing_mapper import find_column_name, smart_read_csv

REPORTING_CHANNELS: Tuple[str, ...] = (
    "CC",
    "SMS",
    "DM",
    "Website",
    "PPC",
    "SEO",
    "Other",
)

IN_SCOPE_CHANNELS: Tuple[str, ...] = ("CC", "SMS", "DM", "Website", "PPC", "SEO")

LEAD_SOURCE_CANDIDATES = ["Lead Source", "Lead source", "LeadSource"]
CREATE_DATE_CANDIDATES = [
    "Create Date",
    "Created Date",
    "Lead Created Date",
    "CreatedDate",
]

# Normalized lead source (lowercase, collapsed whitespace) -> reporting channel
_SOURCE_TO_CHANNEL: Dict[str, str] = {
    "cold calling": "CC",
    "sms": "SMS",
    "res-va sms": "SMS",
    "direct mail": "DM",
    "website": "Website",
    "ppc": "PPC",
    "seo": "SEO",
}


def _normalize_lead_source(raw: object) -> str:
    if pd.isna(raw):
        return ""
    text = re.sub(r"\s+", " ", str(raw).strip())
    return text


def rollup_channel(lead_source: object) -> str:
    """Map raw Lead Source to reporting channel (RES-VA SMS rolls into SMS)."""
    text = _normalize_lead_source(lead_source)
    if not text:
        return "Other"
    key = text.lower()
    return _SOURCE_TO_CHANNEL.get(key, "Other")


def load_qualified_leads_file(file_path: str) -> pd.DataFrame:
    """Load SF Total Qualified Leads export (CSV or XLSX)."""
    path = Path(file_path)
    suffix = path.suffix.lower()
    if suffix in (".xlsx", ".xls"):
        try:
            return pd.read_excel(file_path, engine="openpyxl")
        except ImportError as exc:
            raise ValueError("Reading Excel requires openpyxl: pip install openpyxl") from exc
    if suffix == ".csv" or suffix == "":
        return smart_read_csv(file_path)
    raise ValueError(f"Unsupported file type: {suffix or '(none)'}. Use .csv or .xlsx")


def _parse_create_date_series(series: pd.Series) -> pd.Series:
    """Return datetime64[ns] with NaT for unparseable values."""
    return pd.to_datetime(series, errors="coerce")


def _date_to_ymd(d: date) -> str:
    return d.isoformat()


def validate_and_prepare(df: pd.DataFrame) -> Tuple[pd.DataFrame, str, str]:
    """
    Require Lead Source + Create Date columns.
    Returns (prepared df with canonical columns, lead_source_col, create_date_col names).
    """
    lead_col = find_column_name(df, LEAD_SOURCE_CANDIDATES)
    create_col = find_column_name(df, CREATE_DATE_CANDIDATES)
    missing = []
    if not lead_col:
        missing.append("Lead Source")
    if not create_col:
        missing.append("Create Date")
    if missing:
        raise ValueError(f"Missing required columns: {', '.join(missing)}")

    out = df.copy()
    out["_lead_source_raw"] = out[lead_col].apply(_normalize_lead_source)
    out["_create_date_parsed"] = _parse_create_date_series(out[create_col])
    out["_reporting_channel"] = out[lead_col].apply(rollup_channel)
    out["_in_window"] = False
    return out, lead_col, create_col


@dataclass
class QualifiedLeadsResult:
    rows_ingested: int
    qualified_total_file: int
    posted_in_window: int
    posted_excluded_bad_date: int
    posted_outside_window: int
    date_window_start: str
    date_window_end: str
    create_date_min: Optional[str]
    create_date_max: Optional[str]
    channel_counts: Dict[str, int]
    channel_shares_pct: Dict[str, float]
    in_scope_subtotal: int
    in_scope_share_pct: float
    lead_source_unmapped: Dict[str, int]
    lead_source_blank: int
    rows: List[Dict[str, Any]]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "rows_ingested": self.rows_ingested,
            "qualified_total_file": self.qualified_total_file,
            "posted_in_window": self.posted_in_window,
            "posted_excluded_bad_date": self.posted_excluded_bad_date,
            "posted_outside_window": self.posted_outside_window,
            "date_window_start": self.date_window_start,
            "date_window_end": self.date_window_end,
            "create_date_min": self.create_date_min,
            "create_date_max": self.create_date_max,
            "channel_counts": self.channel_counts,
            "channel_shares_pct": self.channel_shares_pct,
            "in_scope_subtotal": self.in_scope_subtotal,
            "in_scope_share_pct": self.in_scope_share_pct,
            "lead_source_unmapped": self.lead_source_unmapped,
            "lead_source_blank": self.lead_source_blank,
            "qualified_rate_window_note": (
                "Every row in this Salesforce export is treated as qualified; "
                "posted_in_window equals qualified_in_window. Channel rates are "
                "share of posted leads by channel, not conversion rate."
            ),
        }


def compute_qualified_leads_metrics(
    df: pd.DataFrame,
    start_date: date,
    end_date: date,
) -> QualifiedLeadsResult:
    """
    Compute channel counts and share-of-posted rates for Create Date window [start, end] inclusive.
    """
    if start_date > end_date:
        raise ValueError("start_date must be on or before end_date")

    prepared, _lead_col, _create_col = validate_and_prepare(df)
    rows_ingested = len(prepared)

    valid_mask = prepared["_create_date_parsed"].notna()
    posted_excluded_bad_date = int((~valid_mask).sum())
    valid_dates = prepared.loc[valid_mask, "_create_date_parsed"]
    create_date_min: Optional[str] = None
    create_date_max: Optional[str] = None
    if not valid_dates.empty:
        create_date_min = _date_to_ymd(valid_dates.min().date())
        create_date_max = _date_to_ymd(valid_dates.max().date())

    window_start = pd.Timestamp(start_date)
    window_end = pd.Timestamp(end_date) + pd.Timedelta(days=1) - pd.Timedelta(microseconds=1)
    in_window_mask = valid_mask & (
        prepared["_create_date_parsed"] >= window_start
    ) & (prepared["_create_date_parsed"] <= window_end)
    prepared["_in_window"] = in_window_mask

    posted_in_window = int(in_window_mask.sum())
    posted_outside_window = int(valid_mask.sum() - posted_in_window)

    windowed = prepared.loc[in_window_mask]
    channel_counts: Dict[str, int] = {ch: 0 for ch in REPORTING_CHANNELS}
    for ch, cnt in windowed["_reporting_channel"].value_counts().items():
        channel_counts[str(ch)] = int(cnt)
    for ch in REPORTING_CHANNELS:
        channel_counts.setdefault(ch, 0)

    channel_shares_pct: Dict[str, float] = {}
    if posted_in_window > 0:
        for ch in REPORTING_CHANNELS:
            channel_shares_pct[ch] = round(100.0 * channel_counts[ch] / posted_in_window, 2)
    else:
        for ch in REPORTING_CHANNELS:
            channel_shares_pct[ch] = 0.0

    in_scope_subtotal = sum(channel_counts[ch] for ch in IN_SCOPE_CHANNELS)
    in_scope_share_pct = (
        round(100.0 * in_scope_subtotal / posted_in_window, 2) if posted_in_window else 0.0
    )

    unmapped: Dict[str, int] = {}
    blank_count = 0
    for raw, ch in zip(prepared["_lead_source_raw"], prepared["_reporting_channel"]):
        if not raw:
            blank_count += 1
            continue
        if ch == "Other" and raw:
            key = raw
            unmapped[key] = unmapped.get(key, 0) + 1
    unmapped = dict(sorted(unmapped.items(), key=lambda x: (-x[1], x[0])))

    row_records: List[Dict[str, Any]] = []
    for _, row in prepared.iterrows():
        parsed = row["_create_date_parsed"]
        if pd.isna(parsed):
            create_ymd = ""
            exclusion = "bad_create_date"
        elif not row["_in_window"]:
            create_ymd = _date_to_ymd(parsed.date())
            exclusion = "outside_window"
        else:
            create_ymd = _date_to_ymd(parsed.date())
            exclusion = ""
        row_records.append(
            {
                "lead_source_raw": row["_lead_source_raw"],
                "reporting_channel": row["_reporting_channel"],
                "create_date": create_ymd,
                "in_window": bool(row["_in_window"]),
                "exclusion_reason": exclusion,
            }
        )

    return QualifiedLeadsResult(
        rows_ingested=rows_ingested,
        qualified_total_file=rows_ingested,
        posted_in_window=posted_in_window,
        posted_excluded_bad_date=posted_excluded_bad_date,
        posted_outside_window=posted_outside_window,
        date_window_start=_date_to_ymd(start_date),
        date_window_end=_date_to_ymd(end_date),
        create_date_min=create_date_min,
        create_date_max=create_date_max,
        channel_counts=channel_counts,
        channel_shares_pct=channel_shares_pct,
        in_scope_subtotal=in_scope_subtotal,
        in_scope_share_pct=in_scope_share_pct,
        lead_source_unmapped=unmapped,
        lead_source_blank=blank_count,
        rows=row_records,
    )


def file_span_from_df(df: pd.DataFrame) -> Tuple[Optional[date], Optional[date]]:
    """Min/max Create Date from parseable rows."""
    prepared, _, _ = validate_and_prepare(df)
    valid = prepared["_create_date_parsed"].dropna()
    if valid.empty:
        return None, None
    return valid.min().date(), valid.max().date()


def parse_ymd_param(value: str, field_name: str) -> date:
    text = (value or "").strip()
    if not text:
        raise ValueError(f"{field_name} is required")
    parsed = pd.to_datetime(text, errors="coerce")
    if pd.isna(parsed):
        raise ValueError(f"Invalid {field_name}: {value!r} (use YYYY-MM-DD)")
    return parsed.date()


def rows_to_export_csv(result: QualifiedLeadsResult) -> str:
    """Build CSV string for row-level drill-down."""
    export_df = pd.DataFrame(result.rows)
    return export_df.to_csv(index=False)


def analyze_file(
    file_path: str,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    use_full_file_span: bool = False,
) -> QualifiedLeadsResult:
    df = load_qualified_leads_file(file_path)
    if use_full_file_span:
        span_min, span_max = file_span_from_df(df)
        if span_min is None or span_max is None:
            raise ValueError("No parseable Create Date values in file; cannot use full file span")
        start_date = span_min
        end_date = span_max
    if start_date is None or end_date is None:
        raise ValueError("start_date and end_date are required unless use_full_file_span is true")
    return compute_qualified_leads_metrics(df, start_date, end_date)
