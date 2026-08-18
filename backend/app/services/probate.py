"""
Gate 5 — Probate lifecycle.

Long Island Profiles (probate county tags) vs 8020 as competing list providers
on the same REISift row, then Salesforce Prospect (QL Create Date), then
Transactions Primary/Secondary Reason for Selling.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from io import BytesIO
from typing import Any, Callable, Dict, List, Optional, Tuple

import pandas as pd

from .marketing_mapper import find_column_name, make_address_key, sanitize_phone
from .monthly_consolidated import (
    REISIFT_ADDR,
    TAGS_CANDIDATES,
    _col_val,
    load_reisift_file,
)
from .qualified_leads import CREATE_DATE_CANDIDATES, load_qualified_leads_file

REPORT_TYPE = "probate"

ProgressCallback = Callable[[int, str], None]

PROBATE_TAG_RE = re.compile(
    r"^Probates\s+NY\s+(Nassau|Queens|Suffolk)\s+(\d{1,2})-(\d{4})$",
    re.I,
)
LIST_PURCHASED_8020_RE = re.compile(
    r"^List\s+Purchased\s+8020\s+(\d{1,2})[-/](\d{4})$",
    re.I,
)
LIST_PURCHASED_GENERIC_RE = re.compile(
    r"^List\s+Purchased\s+(?!8020\b|Web\s+Leads)(\d{1,2})[-/](\d{4})$",
    re.I,
)
STANDALONE_8020_TOKEN_RE = re.compile(r"^\(8020\)$", re.I)

COUNTIES = ("Nassau", "Queens", "Suffolk")

LOCKED_PROBATE_TAGS: Tuple[str, ...] = (
    "Probates NY Nassau 02-2025",
    "Probates NY Nassau 03-2025",
    "Probates NY Nassau 04-2025",
    "Probates NY Nassau 05-2025",
    "Probates NY Nassau 06-2025",
    "Probates NY Nassau 07-2025",
    "Probates NY Nassau 08-2025",
    "Probates NY Nassau 09-2025",
    "Probates NY Nassau 1-2026",
    "Probates NY Nassau 10-2025",
    "Probates NY Nassau 2-2026",
    "Probates NY Nassau 4-2026",
    "Probates NY Nassau 5-2026",
    "Probates NY Nassau 7-2026",
    "Probates NY Nassau 8-2026",
    "Probates NY Queens 2-2026",
    "Probates NY Queens 4-2026",
    "Probates NY Queens 5-2026",
    "Probates NY Queens 7-2026",
    "Probates NY Queens 8-2026",
    "Probates NY Suffolk 02-2025",
    "Probates NY Suffolk 03-2025",
    "Probates NY Suffolk 04-2025",
    "Probates NY Suffolk 05-2025",
    "Probates NY Suffolk 06-2025",
    "Probates NY Suffolk 07-2025",
    "Probates NY Suffolk 08-2025",
    "Probates NY Suffolk 09-2025",
    "Probates NY Suffolk 1-2026",
    "Probates NY Suffolk 10-2025",
    "Probates NY Suffolk 12-2025",
    "Probates NY Suffolk 2-2026",
    "Probates NY Suffolk 3-2026",
    "Probates NY Suffolk 4-2026",
    "Probates NY Suffolk 5-2026",
    "Probates NY Suffolk 6-2026",
    "Probates NY Suffolk 7-2026",
    "Probates NY Suffolk 8-2026",
)

FIRST_SOURCE_LIP_ONLY = "lip_only"
FIRST_SOURCE_LIP_FIRST = "lip_first"
FIRST_SOURCE_8020_FIRST = "eight_first"
FIRST_SOURCE_SAME = "same_month"

FIRST_SOURCE_LABELS: Dict[str, str] = {
    FIRST_SOURCE_LIP_ONLY: "LIP only",
    FIRST_SOURCE_LIP_FIRST: "LIP first",
    FIRST_SOURCE_8020_FIRST: "8020 first",
    FIRST_SOURCE_SAME: "Same month",
}

LAG_BUCKETS: Tuple[Tuple[str, Optional[int], Optional[int]], ...] = (
    ("Prospect before LIP", None, -1),
    ("Same month", 0, 0),
    ("1-3 months", 1, 3),
    ("4-6 months", 4, 6),
    ("7-12 months", 7, 12),
    ("13+ months", 13, None),
)

QL_ADDR = {
    "street": ["Street", "Mailing address", "Property address", "Property Address"],
    "city": ["City", "Mailing city", "Property city"],
    "state": ["State/Province", "State", "Mailing state", "Property state"],
    "zip": ["Zip/Postal Code", "Zip", "Mailing zip", "Property zip"],
}
OPP_ADDR = {
    "street": ["Address (Street)", "Billing Street", "Street", "Address"],
    "city": ["Address (City)", "City"],
    "state": ["Address (State/Province)", "State/Province", "State"],
    "zip": ["Address (ZIP/Postal Code)", "Zip/Postal Code", "Zip"],
}
TXN_ADDR = {
    "street": ["Address (Street)", "Street", "Address"],
    "city": ["Address (City)", "City"],
    "state": ["Address (State/Province)", "State/Province", "State"],
    "zip": ["Address (ZIP/Postal Code)", "Zip/Postal Code", "Zip"],
}

QL_PHONE_CANDIDATES = ["Phone", "Mobile", "Mobile Phone"]
REISIFT_PHONE_CANDIDATES = [
    "Phone 1",
    "Phone 2",
    "Phone 3",
    "Phone",
    "Mobile",
    "Mobile Phone",
]
OPP_DATE_CANDIDATES = ["Created Date", "Create Date", "CreatedDate"]
TXN_DATE_CANDIDATES = ["Closed Date", "Date Closed", "Close Date"]
PRIMARY_REASON_CANDIDATES = ["Primary Reason for Selling", "Primary Reason For Selling"]
SECONDARY_REASON_CANDIDATES = [
    "Secondary Reason for Selling",
    "Secondary Reason For Selling",
]

BLANK_REASON = "(blank)"


def _split_tag_tokens(tags_str: object) -> List[str]:
    if tags_str is None or (isinstance(tags_str, float) and pd.isna(tags_str)):
        return []
    return [part.strip() for part in str(tags_str).split(",") if part.strip()]


def _month_start(year: int, month: int) -> Optional[pd.Timestamp]:
    try:
        return pd.Timestamp(year=year, month=month, day=1)
    except ValueError:
        return None


def parse_probate_tags(tags_str: object) -> List[Dict[str, Any]]:
    """Parse Probates NY {County} M-YYYY tokens. Earliest-first."""
    found: List[Dict[str, Any]] = []
    seen: set[Tuple[str, int, int]] = set()
    for token in _split_tag_tokens(tags_str):
        match = PROBATE_TAG_RE.match(token)
        if not match:
            continue
        county = match.group(1).title()
        month = int(match.group(2))
        year = int(match.group(3))
        key = (county, year, month)
        if key in seen:
            continue
        dt = _month_start(year, month)
        if dt is None:
            continue
        seen.add(key)
        found.append(
            {
                "county": county,
                "year": year,
                "month": month,
                "date": dt,
                "tag": token,
            }
        )
    found.sort(key=lambda item: (item["date"], item["county"]))
    return found


def first_probate_hit(tags_str: object) -> Optional[Dict[str, Any]]:
    hits = parse_probate_tags(tags_str)
    return hits[0] if hits else None


def row_has_probate_tag(tags_str: object) -> bool:
    return first_probate_hit(tags_str) is not None


def parse_8020_list_purchase_date(tags_str: object) -> Optional[pd.Timestamp]:
    """Earliest 8020 *list purchase* month. Contact tags like (8020) CC do not count."""
    tokens = _split_tag_tokens(tags_str)
    has_standalone_8020 = any(STANDALONE_8020_TOKEN_RE.match(t) for t in tokens)
    dates: List[pd.Timestamp] = []
    for token in tokens:
        match_8020 = LIST_PURCHASED_8020_RE.match(token)
        if match_8020:
            dt = _month_start(int(match_8020.group(2)), int(match_8020.group(1)))
            if dt is not None:
                dates.append(dt)
            continue
        if not has_standalone_8020:
            continue
        match_generic = LIST_PURCHASED_GENERIC_RE.match(token)
        if not match_generic:
            continue
        dt = _month_start(int(match_generic.group(2)), int(match_generic.group(1)))
        if dt is not None:
            dates.append(dt)
    if not dates:
        return None
    return min(dates)


def classify_first_source(
    lip_date: Optional[pd.Timestamp],
    eight_date: Optional[pd.Timestamp],
) -> str:
    if lip_date is None or pd.isna(lip_date):
        raise ValueError("LIP date is required to classify first source")
    if eight_date is None or pd.isna(eight_date):
        return FIRST_SOURCE_LIP_ONLY
    lip = pd.Timestamp(lip_date)
    eight = pd.Timestamp(eight_date)
    lip_ym = (lip.year, lip.month)
    eight_ym = (eight.year, eight.month)
    if lip_ym < eight_ym:
        return FIRST_SOURCE_LIP_FIRST
    if eight_ym < lip_ym:
        return FIRST_SOURCE_8020_FIRST
    return FIRST_SOURCE_SAME


def months_between(
    start: Optional[pd.Timestamp], end: Optional[pd.Timestamp]
) -> Optional[int]:
    if start is None or end is None or pd.isna(start) or pd.isna(end):
        return None
    a = pd.Timestamp(start)
    b = pd.Timestamp(end)
    return (b.year - a.year) * 12 + (b.month - a.month)


def lag_bucket_label(months: Optional[int]) -> str:
    if months is None:
        return "Unknown"
    if months < 0:
        return "Prospect before LIP"
    for label, lo, hi in LAG_BUCKETS:
        if lo is None:
            continue
        if hi is None and months >= lo:
            return label
        if hi is not None and lo <= months <= hi:
            return label
    return "Unknown"


def _zip5(raw: object) -> str:
    digits = re.sub(r"\D", "", str(raw or ""))
    return digits[:5]


def _ym_label(ts: Optional[pd.Timestamp]) -> str:
    if ts is None or pd.isna(ts):
        return ""
    stamp = pd.Timestamp(ts)
    return f"{stamp.year:04d}-{stamp.month:02d}"


def _iso_day(ts: Optional[pd.Timestamp]) -> str:
    if ts is None or pd.isna(ts):
        return ""
    return pd.Timestamp(ts).date().isoformat()


def _reason_value(raw: object) -> str:
    if raw is None or (isinstance(raw, float) and pd.isna(raw)):
        return BLANK_REASON
    text = str(raw).strip()
    if not text or text.lower() == "nan":
        return BLANK_REASON
    return text


def _discover_cols(df: pd.DataFrame, spec: Dict[str, List[str]]) -> Dict[str, Optional[str]]:
    return {k: find_column_name(df, v) for k, v in spec.items()}


def _address_key_from_parts(street: object, city: object, state: object, zip_code: object) -> str:
    return make_address_key(street or "", city or "", state or "", _zip5(zip_code))


def _row_address_key(row: pd.Series, cols: Dict[str, Optional[str]]) -> str:
    street = row.get(cols["street"], "") if cols.get("street") else ""
    city = row.get(cols["city"], "") if cols.get("city") else ""
    state = row.get(cols["state"], "") if cols.get("state") else ""
    zip_code = row.get(cols["zip"], "") if cols.get("zip") else ""
    return _address_key_from_parts(street, city, state, zip_code)


def _fallback_keys(full_key: str) -> List[str]:
    parts = full_key.split("|")
    if len(parts) != 4:
        return []
    street, city, _state, zip_code = parts
    keys: List[str] = []
    if street and zip_code:
        no_state = f"{street}|{city}||{zip_code}"
        street_zip = f"{street}|||{zip_code}"
        if no_state != full_key:
            keys.append(no_state)
        if street_zip not in (full_key, no_state):
            keys.append(street_zip)
    return keys


def _valid_key(key: str) -> bool:
    if not key or key == "|||":
        return False
    parts = key.split("|")
    return bool(parts and parts[0])


def _phones_from_row(row: pd.Series, candidates: List[str]) -> List[str]:
    found: List[str] = []
    seen: set[str] = set()
    for name in candidates:
        if name not in row.index:
            continue
        phone = sanitize_phone(row.get(name, ""))
        if len(phone) >= 10 and phone not in seen:
            seen.add(phone)
            found.append(phone)
    return found


def _parse_ts(raw: object) -> Optional[pd.Timestamp]:
    parsed = pd.to_datetime(raw, errors="coerce")
    if pd.isna(parsed):
        return None
    return pd.Timestamp(parsed).normalize()


def _load_crm_file(file_path: str) -> pd.DataFrame:
    return load_qualified_leads_file(file_path)


@dataclass
class CrmHit:
    date: Optional[pd.Timestamp]
    primary_reason: str = BLANK_REASON
    secondary_reason: str = BLANK_REASON
    via: str = ""


@dataclass
class MatchIndex:
    by_full: Dict[str, List[int]]
    by_no_state: Dict[str, List[int]]
    by_street_zip: Dict[str, List[int]]
    by_phone: Dict[str, List[int]]
    rows: pd.DataFrame
    dates: List[Optional[pd.Timestamp]]
    primary_reasons: List[str]
    secondary_reasons: List[str]


def _add_index(bucket: Dict[str, List[int]], key: str, idx: int) -> None:
    if not _valid_key(key):
        return
    bucket.setdefault(key, []).append(idx)


def _build_match_index(
    df: pd.DataFrame,
    addr_spec: Dict[str, List[str]],
    date_candidates: List[str],
    phone_candidates: Optional[List[str]] = None,
    primary_reason_candidates: Optional[List[str]] = None,
    secondary_reason_candidates: Optional[List[str]] = None,
) -> MatchIndex:
    cols = _discover_cols(df, addr_spec)
    date_col = find_column_name(df, date_candidates) if date_candidates else None
    primary_col = (
        find_column_name(df, primary_reason_candidates) if primary_reason_candidates else None
    )
    secondary_col = (
        find_column_name(df, secondary_reason_candidates)
        if secondary_reason_candidates
        else None
    )
    by_full: Dict[str, List[int]] = {}
    by_no_state: Dict[str, List[int]] = {}
    by_street_zip: Dict[str, List[int]] = {}
    by_phone: Dict[str, List[int]] = {}
    dates: List[Optional[pd.Timestamp]] = []
    primaries: List[str] = []
    secondaries: List[str] = []
    for i, (_, row) in enumerate(df.iterrows()):
        full = _row_address_key(row, cols)
        _add_index(by_full, full, i)
        for fb in _fallback_keys(full):
            parts = fb.split("|")
            if parts[1]:
                _add_index(by_no_state, fb, i)
            else:
                _add_index(by_street_zip, fb, i)
        if phone_candidates:
            for phone in _phones_from_row(row, phone_candidates):
                by_phone.setdefault(phone, []).append(i)
        dates.append(_parse_ts(row.get(date_col, "")) if date_col else None)
        primaries.append(_reason_value(row.get(primary_col, "")) if primary_col else BLANK_REASON)
        secondaries.append(
            _reason_value(row.get(secondary_col, "")) if secondary_col else BLANK_REASON
        )
    return MatchIndex(
        by_full=by_full,
        by_no_state=by_no_state,
        by_street_zip=by_street_zip,
        by_phone=by_phone,
        rows=df,
        dates=dates,
        primary_reasons=primaries,
        secondary_reasons=secondaries,
    )


def _lookup_indices(index: MatchIndex, full_key: str, phones: List[str]) -> Tuple[List[int], str]:
    if _valid_key(full_key) and full_key in index.by_full:
        return index.by_full[full_key], "address"
    for fb in _fallback_keys(full_key):
        parts = fb.split("|")
        if parts[1] and fb in index.by_no_state:
            return index.by_no_state[fb], "address_no_state"
        if not parts[1] and fb in index.by_street_zip:
            return index.by_street_zip[fb], "street_zip"
        if parts[1] and fb in index.by_full:
            return index.by_full[fb], "address_no_state"
        if fb in index.by_full:
            return index.by_full[fb], "street_zip"
    for phone in phones:
        if phone in index.by_phone:
            return index.by_phone[phone], "phone"
    return [], ""


def _best_hit(index: Optional[MatchIndex], full_key: str, phones: List[str]) -> Optional[CrmHit]:
    if index is None:
        return None
    idxs, via = _lookup_indices(index, full_key, phones)
    if not idxs:
        return None
    best_i = idxs[0]
    best_date = index.dates[best_i]
    for i in idxs[1:]:
        dt = index.dates[i]
        if dt is None:
            continue
        if best_date is None or dt < best_date:
            best_date = dt
            best_i = i
    return CrmHit(
        date=best_date,
        primary_reason=index.primary_reasons[best_i],
        secondary_reason=index.secondary_reasons[best_i],
        via=via,
    )


def _pct(part: int, whole: int) -> float:
    if whole <= 0:
        return 0.0
    return round(100.0 * part / whole, 2)


def _counter_table(counter: Counter[str], whole: int) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for key, count in counter.most_common():
        rows.append({"label": key, "count": count, "share_pct": _pct(count, whole)})
    return rows


def _mean_median(values: List[int]) -> Tuple[Optional[float], Optional[float]]:
    if not values:
        return None, None
    series = pd.Series(values, dtype="float64")
    return round(float(series.mean()), 2), round(float(series.median()), 2)


@dataclass
class ProbateRow:
    address: str
    address_key: str
    county: str
    counties: List[str]
    lip_month: str
    eight_month: str
    first_source: str
    first_source_label: str
    prospect_date: str
    prospect_matched: bool
    prospect_match_via: str
    months_lip_to_prospect: Optional[int]
    months_eight_to_prospect: Optional[int]
    months_winner_to_prospect: Optional[int]
    lag_bucket: str
    opp_matched: bool
    opp_created_date: str
    txn_matched: bool
    txn_closed_date: str
    txn_primary_reason: str
    txn_secondary_reason: str
    tags: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "address": self.address,
            "address_key": self.address_key,
            "county": self.county,
            "counties": self.counties,
            "lip_month": self.lip_month,
            "eight_month": self.eight_month,
            "first_source": self.first_source,
            "first_source_label": self.first_source_label,
            "prospect_date": self.prospect_date,
            "prospect_matched": self.prospect_matched,
            "prospect_match_via": self.prospect_match_via,
            "months_lip_to_prospect": self.months_lip_to_prospect,
            "months_eight_to_prospect": self.months_eight_to_prospect,
            "months_winner_to_prospect": self.months_winner_to_prospect,
            "lag_bucket": self.lag_bucket,
            "opp_matched": self.opp_matched,
            "opp_created_date": self.opp_created_date,
            "txn_matched": self.txn_matched,
            "txn_closed_date": self.txn_closed_date,
            "txn_primary_reason": self.txn_primary_reason if self.txn_matched else "",
            "txn_secondary_reason": self.txn_secondary_reason if self.txn_matched else "",
            "tags": self.tags,
        }


@dataclass
class ProbateResult:
    date_window_start: str
    date_window_end: str
    reisift_rows_ingested: int
    lip_universe: int
    prospect_matched: int
    prospect_rate_pct: float
    opp_matched: int
    opp_rate_pct: float
    txn_matched: int
    txn_rate_pct: float
    mean_months_lip_to_prospect: Optional[float]
    median_months_lip_to_prospect: Optional[float]
    first_source: List[Dict[str, Any]]
    counties: List[Dict[str, Any]]
    cohorts: List[Dict[str, Any]]
    lag_buckets: List[Dict[str, Any]]
    funnel: Dict[str, int]
    primary_reasons: List[Dict[str, Any]]
    secondary_reasons: List[Dict[str, Any]]
    rows: List[ProbateRow] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    methodology_note: str = ""

    def to_api_dict(self) -> Dict[str, Any]:
        return {
            "report_type": REPORT_TYPE,
            "date_window_start": self.date_window_start,
            "date_window_end": self.date_window_end,
            "inputs": {
                "reisift_rows_ingested": self.reisift_rows_ingested,
                "lip_universe": self.lip_universe,
            },
            "match": {
                "prospect_matched": self.prospect_matched,
                "prospect_rate_pct": self.prospect_rate_pct,
                "opp_matched": self.opp_matched,
                "opp_rate_pct": self.opp_rate_pct,
                "txn_matched": self.txn_matched,
                "txn_rate_pct": self.txn_rate_pct,
            },
            "lag": {
                "mean_months_lip_to_prospect": self.mean_months_lip_to_prospect,
                "median_months_lip_to_prospect": self.median_months_lip_to_prospect,
            },
            "first_source": self.first_source,
            "counties": self.counties,
            "cohorts": self.cohorts,
            "lag_buckets": self.lag_buckets,
            "funnel": self.funnel,
            "primary_reasons": self.primary_reasons,
            "secondary_reasons": self.secondary_reasons,
            "rows": [r.to_dict() for r in self.rows],
            "warnings": self.warnings,
            "methodology_note": self.methodology_note,
        }


def result_from_metrics_dict(metrics: Dict[str, Any]) -> ProbateResult:
    rows = [ProbateRow(**_row_kwargs(item)) for item in metrics.get("rows") or []]
    match = metrics.get("match") or {}
    lag = metrics.get("lag") or {}
    inputs = metrics.get("inputs") or {}
    return ProbateResult(
        date_window_start=str(metrics.get("date_window_start") or ""),
        date_window_end=str(metrics.get("date_window_end") or ""),
        reisift_rows_ingested=int(inputs.get("reisift_rows_ingested") or 0),
        lip_universe=int(inputs.get("lip_universe") or 0),
        prospect_matched=int(match.get("prospect_matched") or 0),
        prospect_rate_pct=float(match.get("prospect_rate_pct") or 0),
        opp_matched=int(match.get("opp_matched") or 0),
        opp_rate_pct=float(match.get("opp_rate_pct") or 0),
        txn_matched=int(match.get("txn_matched") or 0),
        txn_rate_pct=float(match.get("txn_rate_pct") or 0),
        mean_months_lip_to_prospect=lag.get("mean_months_lip_to_prospect"),
        median_months_lip_to_prospect=lag.get("median_months_lip_to_prospect"),
        first_source=list(metrics.get("first_source") or []),
        counties=list(metrics.get("counties") or []),
        cohorts=list(metrics.get("cohorts") or []),
        lag_buckets=list(metrics.get("lag_buckets") or []),
        funnel=dict(metrics.get("funnel") or {}),
        primary_reasons=list(metrics.get("primary_reasons") or []),
        secondary_reasons=list(metrics.get("secondary_reasons") or []),
        rows=rows,
        warnings=list(metrics.get("warnings") or []),
        methodology_note=str(metrics.get("methodology_note") or ""),
    )


def _row_kwargs(item: Dict[str, Any]) -> Dict[str, Any]:
    allowed = {
        "address",
        "address_key",
        "county",
        "counties",
        "lip_month",
        "eight_month",
        "first_source",
        "first_source_label",
        "prospect_date",
        "prospect_matched",
        "prospect_match_via",
        "months_lip_to_prospect",
        "months_eight_to_prospect",
        "months_winner_to_prospect",
        "lag_bucket",
        "opp_matched",
        "opp_created_date",
        "txn_matched",
        "txn_closed_date",
        "txn_primary_reason",
        "txn_secondary_reason",
        "tags",
    }
    out = {k: item.get(k) for k in allowed}
    out["counties"] = list(out.get("counties") or [])
    out["prospect_matched"] = bool(out.get("prospect_matched"))
    out["opp_matched"] = bool(out.get("opp_matched"))
    out["txn_matched"] = bool(out.get("txn_matched"))
    out["address"] = str(out.get("address") or "")
    out["address_key"] = str(out.get("address_key") or "")
    out["county"] = str(out.get("county") or "")
    out["lip_month"] = str(out.get("lip_month") or "")
    out["eight_month"] = str(out.get("eight_month") or "")
    out["first_source"] = str(out.get("first_source") or "")
    out["first_source_label"] = str(out.get("first_source_label") or "")
    out["prospect_date"] = str(out.get("prospect_date") or "")
    out["prospect_match_via"] = str(out.get("prospect_match_via") or "")
    out["lag_bucket"] = str(out.get("lag_bucket") or "")
    out["opp_created_date"] = str(out.get("opp_created_date") or "")
    out["txn_closed_date"] = str(out.get("txn_closed_date") or "")
    out["txn_primary_reason"] = str(out.get("txn_primary_reason") or "")
    out["txn_secondary_reason"] = str(out.get("txn_secondary_reason") or "")
    out["tags"] = str(out.get("tags") or "")
    return out


def analyze(
    reisift_path: str,
    ql_path: str,
    opportunities_path: Optional[str] = None,
    transactions_path: Optional[str] = None,
    on_progress: Optional[ProgressCallback] = None,
) -> ProbateResult:
    def report(pct: int, message: str) -> None:
        if on_progress:
            on_progress(pct, message)

    warnings: List[str] = []
    report(8, "Loading REISift export…")
    reisift_df = load_reisift_file(reisift_path)
    tags_col = find_column_name(reisift_df, TAGS_CANDIDATES)
    if not tags_col:
        raise ValueError("Missing required column: Tags")

    report(18, "Loading Salesforce qualified leads…")
    ql_df = _load_crm_file(ql_path)
    ql_index = _build_match_index(ql_df, QL_ADDR, CREATE_DATE_CANDIDATES, QL_PHONE_CANDIDATES)

    opp_index: Optional[MatchIndex] = None
    if opportunities_path:
        report(26, "Loading opportunities…")
        opp_index = _build_match_index(
            _load_crm_file(opportunities_path), OPP_ADDR, OPP_DATE_CANDIDATES
        )
    else:
        warnings.append("Opportunities file not uploaded — Opp funnel counts will be zero.")

    txn_index: Optional[MatchIndex] = None
    if transactions_path:
        report(32, "Loading transactions…")
        txn_df = _load_crm_file(transactions_path)
        txn_index = _build_match_index(
            txn_df,
            TXN_ADDR,
            TXN_DATE_CANDIDATES,
            primary_reason_candidates=PRIMARY_REASON_CANDIDATES,
            secondary_reason_candidates=SECONDARY_REASON_CANDIDATES,
        )
        if not find_column_name(txn_df, PRIMARY_REASON_CANDIDATES):
            warnings.append("Transactions file has no Primary Reason for Selling column.")
    else:
        warnings.append(
            "Transactions file not uploaded — reason-to-sell tables will be empty."
        )

    rows: List[ProbateRow] = []
    lip_dates: List[pd.Timestamp] = []
    lag_values: List[int] = []
    first_source_counter: Counter[str] = Counter()
    county_counter: Counter[str] = Counter()
    lag_counter: Counter[str] = Counter()
    cohort_stats: Dict[str, Dict[str, Any]] = {}
    primary_counter: Counter[str] = Counter()
    secondary_counter: Counter[str] = Counter()

    report(40, "Scanning probate tags…")
    total = len(reisift_df)
    for i, (_, row) in enumerate(reisift_df.iterrows()):
        tags_val = row.get(tags_col, "")
        hit = first_probate_hit(tags_val)
        if hit is None:
            continue
        lip_date = hit["date"]
        lip_dates.append(lip_date)
        eight_date = parse_8020_list_purchase_date(tags_val)
        source = classify_first_source(lip_date, eight_date)
        first_source_counter[source] += 1
        counties = [h["county"] for h in parse_probate_tags(tags_val)]
        county = hit["county"]
        county_counter[county] += 1

        street = _col_val(row, REISIFT_ADDR["street"])
        city = _col_val(row, REISIFT_ADDR["city"])
        state = _col_val(row, REISIFT_ADDR["state"])
        zip_code = _col_val(row, REISIFT_ADDR["zip"])
        key = _address_key_from_parts(street, city, state, zip_code)
        phones = _phones_from_row(row, REISIFT_PHONE_CANDIDATES)
        display = " ".join(p for p in (street, city) if p) or key

        ql_hit = _best_hit(ql_index, key, phones)
        opp_hit = _best_hit(opp_index, key, [])
        txn_hit = _best_hit(txn_index, key, [])

        prospect_date = ql_hit.date if ql_hit else None
        months_lip = months_between(lip_date, prospect_date)
        months_eight = months_between(eight_date, prospect_date)
        winner_date = lip_date
        if eight_date is not None and eight_date < lip_date:
            winner_date = eight_date
        months_winner = months_between(winner_date, prospect_date)
        bucket = lag_bucket_label(months_lip) if ql_hit else "Unknown"
        if ql_hit and months_lip is not None:
            lag_values.append(months_lip)
            lag_counter[bucket] += 1

        if txn_hit:
            primary_counter[txn_hit.primary_reason] += 1
            secondary_counter[txn_hit.secondary_reason] += 1

        cohort_key = _ym_label(lip_date)
        stats = cohort_stats.setdefault(
            cohort_key,
            {"lip_month": cohort_key, "listed": 0, "prospects": 0, "txns": 0, "lags": []},
        )
        stats["listed"] += 1
        if ql_hit:
            stats["prospects"] += 1
        if txn_hit:
            stats["txns"] += 1
        if months_lip is not None:
            stats["lags"].append(months_lip)

        rows.append(
            ProbateRow(
                address=display,
                address_key=key,
                county=county,
                counties=counties,
                lip_month=_ym_label(lip_date),
                eight_month=_ym_label(eight_date),
                first_source=source,
                first_source_label=FIRST_SOURCE_LABELS[source],
                prospect_date=_iso_day(prospect_date),
                prospect_matched=ql_hit is not None,
                prospect_match_via=ql_hit.via if ql_hit else "",
                months_lip_to_prospect=months_lip,
                months_eight_to_prospect=months_eight,
                months_winner_to_prospect=months_winner,
                lag_bucket=bucket if ql_hit else "",
                opp_matched=opp_hit is not None,
                opp_created_date=_iso_day(opp_hit.date if opp_hit else None),
                txn_matched=txn_hit is not None,
                txn_closed_date=_iso_day(txn_hit.date if txn_hit else None),
                txn_primary_reason=txn_hit.primary_reason if txn_hit else "",
                txn_secondary_reason=txn_hit.secondary_reason if txn_hit else "",
                tags=str(tags_val or ""),
            )
        )
        if on_progress and i > 0 and i % 200 == 0:
            report(40 + int(45 * i / max(total, 1)), f"Row {i:,} / {total:,}…")

    universe = len(rows)
    if universe == 0:
        warnings.append(
            "No REISift rows had a Probates NY Nassau/Queens/Suffolk M-YYYY tag."
        )

    prospect_n = sum(1 for r in rows if r.prospect_matched)
    opp_n = sum(1 for r in rows if r.opp_matched)
    txn_n = sum(1 for r in rows if r.txn_matched)
    mean_lag, median_lag = _mean_median(lag_values)

    first_source_table = [
        {
            "key": key,
            "label": FIRST_SOURCE_LABELS[key],
            "count": first_source_counter.get(key, 0),
            "share_pct": _pct(first_source_counter.get(key, 0), universe),
            "prospects": sum(1 for r in rows if r.first_source == key and r.prospect_matched),
            "prospect_rate_pct": _pct(
                sum(1 for r in rows if r.first_source == key and r.prospect_matched),
                first_source_counter.get(key, 0),
            ),
        }
        for key in (
            FIRST_SOURCE_LIP_ONLY,
            FIRST_SOURCE_LIP_FIRST,
            FIRST_SOURCE_8020_FIRST,
            FIRST_SOURCE_SAME,
        )
        if first_source_counter.get(key, 0) or True
    ]

    county_table = [
        {
            "county": county,
            "count": county_counter.get(county, 0),
            "share_pct": _pct(county_counter.get(county, 0), universe),
            "prospects": sum(1 for r in rows if r.county == county and r.prospect_matched),
            "prospect_rate_pct": _pct(
                sum(1 for r in rows if r.county == county and r.prospect_matched),
                county_counter.get(county, 0),
            ),
        }
        for county in COUNTIES
    ]

    lag_table = []
    for label, _lo, _hi in LAG_BUCKETS:
        count = lag_counter.get(label, 0)
        lag_table.append(
            {
                "bucket": label,
                "count": count,
                "share_pct": _pct(count, prospect_n),
            }
        )

    cohorts: List[Dict[str, Any]] = []
    for key in sorted(cohort_stats):
        stats = cohort_stats[key]
        listed = int(stats["listed"])
        prospects = int(stats["prospects"])
        mean_c, med_c = _mean_median(list(stats["lags"]))
        cohorts.append(
            {
                "lip_month": key,
                "listed": listed,
                "prospects": prospects,
                "prospect_rate_pct": _pct(prospects, listed),
                "txns": int(stats["txns"]),
                "mean_months_lip_to_prospect": mean_c,
                "median_months_lip_to_prospect": med_c,
            }
        )

    window_start = min(lip_dates).date().isoformat() if lip_dates else ""
    window_end = max(lip_dates).date().isoformat() if lip_dates else ""

    methodology = (
        "Universe = REISift rows with a Probates NY Nassau/Queens/Suffolk M-YYYY tag "
        "(Long Island Profiles county drop). First LIP month = earliest of those tags. "
        "8020 list purchase = List Purchased 8020 MM/YYYY, or List Purchased MM/YYYY when a "
        "standalone (8020) token is on the same row. First source compares those two months "
        "on the same row. Prospect = Salesforce Qualified Leads Create Date matched by "
        "street/city/state/zip, then street+zip, then phone. Reason for selling is read only "
        "from the Transactions pipeline Primary/Secondary columns after that match."
    )

    report(96, "Finishing summary…")
    return ProbateResult(
        date_window_start=window_start,
        date_window_end=window_end,
        reisift_rows_ingested=total,
        lip_universe=universe,
        prospect_matched=prospect_n,
        prospect_rate_pct=_pct(prospect_n, universe),
        opp_matched=opp_n,
        opp_rate_pct=_pct(opp_n, universe),
        txn_matched=txn_n,
        txn_rate_pct=_pct(txn_n, universe),
        mean_months_lip_to_prospect=mean_lag,
        median_months_lip_to_prospect=median_lag,
        first_source=first_source_table,
        counties=county_table,
        cohorts=cohorts,
        lag_buckets=lag_table,
        funnel={
            "lip": universe,
            "prospect": prospect_n,
            "opportunity": opp_n,
            "transaction": txn_n,
        },
        primary_reasons=_counter_table(primary_counter, txn_n),
        secondary_reasons=_counter_table(secondary_counter, txn_n),
        rows=rows,
        warnings=warnings,
        methodology_note=methodology,
    )


def build_export_workbook(result: ProbateResult) -> bytes:
    try:
        import openpyxl  # noqa: F401
    except ImportError as exc:
        raise ValueError("XLSX export requires openpyxl") from exc

    buf = BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        summary = [
            {"metric": "Date window start", "value": result.date_window_start},
            {"metric": "Date window end", "value": result.date_window_end},
            {"metric": "REISift rows ingested", "value": result.reisift_rows_ingested},
            {"metric": "LIP / probate universe", "value": result.lip_universe},
            {"metric": "Prospect matched", "value": result.prospect_matched},
            {"metric": "Prospect % of LIP list", "value": result.prospect_rate_pct},
            {"metric": "Opportunities matched", "value": result.opp_matched},
            {"metric": "Transactions matched", "value": result.txn_matched},
            {
                "metric": "Mean months LIP to Prospect",
                "value": result.mean_months_lip_to_prospect,
            },
            {
                "metric": "Median months LIP to Prospect",
                "value": result.median_months_lip_to_prospect,
            },
            {"metric": "Methodology", "value": result.methodology_note},
        ]
        pd.DataFrame(summary).to_excel(writer, sheet_name="Summary", index=False)
        pd.DataFrame([r.to_dict() for r in result.rows]).to_excel(
            writer, sheet_name="Probate Rows", index=False
        )
        if result.first_source:
            pd.DataFrame(result.first_source).to_excel(
                writer, sheet_name="First Source", index=False
            )
        if result.counties:
            pd.DataFrame(result.counties).to_excel(writer, sheet_name="County", index=False)
        if result.cohorts:
            pd.DataFrame(result.cohorts).to_excel(writer, sheet_name="List Month", index=False)
        if result.lag_buckets:
            pd.DataFrame(result.lag_buckets).to_excel(
                writer, sheet_name="Lag Buckets", index=False
            )
        if result.primary_reasons:
            pd.DataFrame(result.primary_reasons).to_excel(
                writer, sheet_name="Txn Primary Reason", index=False
            )
        if result.secondary_reasons:
            pd.DataFrame(result.secondary_reasons).to_excel(
                writer, sheet_name="Txn Secondary Reason", index=False
            )
    return buf.getvalue()
