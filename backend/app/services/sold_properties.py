"""
Shared pipeline helpers used by Investor Sold — NOT a Gate 6 product report.

Cohort logic: REISift rows with a non-empty `in_sold_properties_full` (external sale month).
Measures marketing intensity and funnel depth on or before that sold month. Salesforce Create
Date is a clock (Prospect lag), not source credit. analyze() remains for tests and reuse.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from io import BytesIO
from typing import Any, Callable, Dict, List, Optional, Tuple

import pandas as pd

from .analysis import _dedupe_parsed_tag_events, parse_tags
from .closing_resolution import resolve_milestones_from_parsed
from .lifecycle import (
    ENGAGED_LABELS,
    STAGE_ORDER,
    build_events,
    compute_stage_funnel_open,
    get_highest_stage,
)
from .marketing_mapper import find_column_name, make_address_key, normalize_status
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

REPORT_TYPE = "sold_properties"

ProgressCallback = Callable[[int, str], None]

SOLD_MONTH_CANDIDATES = [
    "in_sold_properties_full",
    "In Sold Properties Full",
    "in_sold_properties",
    "Sold Month",
    "sold_month",
    "External Sold Month",
]

CREATED_CANDIDATES = ["Created", "Created Date", "Created on", "created"]
LISTS_CANDIDATES = ["Lists", "List", "lists"]
REISIFT_PHONE_CANDIDATES = [
    "Phone 1",
    "Phone 2",
    "Phone 3",
    "Phone",
    "Mobile",
    "Mobile Phone",
]

TOUCH_CHANNELS = ("CC", "SMS", "DM")

# Business pipeline (ordered ascending). Canonical for Investor Sold / workspace copy.
# Prospect sources: 8020, Court Alerts, LI Profiles (Probates NY).
# Then: Marketed (CC/DM/SMS) → Lead (SF/Podio) → Qualified Lead → Opportunity → Closed.
PIPELINE_ORDER = (
    "NONE",
    "PROSPECT",
    "MARKETED",
    "LEAD",
    "QUALIFIED_LEAD",
    "OPPORTUNITY",
    "HHB_CLOSED",
)

PIPELINE_LABELS = {
    "NONE": "No list / history",
    "PROSPECT": "Prospect",
    "MARKETED": "Marketed",
    "LEAD": "Lead",
    "QUALIFIED_LEAD": "Qualified Lead",
    "OPPORTUNITY": "Opportunity",
    "HHB_CLOSED": "Closed",
}

# Stages always shown in funnel tables (even at zero).
PIPELINE_FUNNEL_ALWAYS = PIPELINE_ORDER[1:]  # skip NONE unless present

# Single product-facing ladder (Gate 7 + workspace copy). Opp includes under contract.
CANONICAL_PIPELINE = (
    "Prospect (8020 / Court Alerts / LI Profiles) → "
    "Marketed (CC/DM/SMS) → "
    "Lead (Salesforce/Podio) → "
    "Qualified Lead → "
    "Opportunity (includes under contract) → "
    "Closed"
)

PROSPECT_SOURCE_LABELS = {
    "8020": "8020",
    "eight": "8020",
    "lip": "LI Profiles",
    "court_alerts": "Court Alerts",
}

_MONTH_SLASH_RE = re.compile(r"^(\d{1,2})[/-](\d{4})$")
_YEAR_MONTH_RE = re.compile(r"^(\d{4})-(\d{1,2})$")
_MONTH_NAME_RE = re.compile(
    r"^(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*[/\-\s]+(\d{4})$",
    re.I,
)
_MONTH_NAME_MAP = {
    "jan": 1,
    "feb": 2,
    "mar": 3,
    "apr": 4,
    "may": 5,
    "jun": 6,
    "jul": 7,
    "aug": 8,
    "sep": 9,
    "oct": 10,
    "nov": 11,
    "dec": 12,
}


def _col_val(row: pd.Series, col: Optional[str]) -> str:
    if not col or col not in row.index or pd.isna(row[col]):
        return ""
    return str(row[col]).strip()


def _discover_addr_cols(df: pd.DataFrame) -> Dict[str, Optional[str]]:
    return {k: find_column_name(df, v) for k, v in REISIFT_ADDR.items()}


def _address_key_from_row(row: pd.Series, cols: Dict[str, Optional[str]]) -> str:
    return make_address_key(
        _col_val(row, cols.get("street")),
        _col_val(row, cols.get("city")),
        _col_val(row, cols.get("state")),
        _col_val(row, cols.get("zip")),
    )


def _display_address(row: pd.Series, cols: Dict[str, Optional[str]]) -> str:
    parts = [
        _col_val(row, cols.get("street")),
        _col_val(row, cols.get("city")),
        _col_val(row, cols.get("state")),
        _col_val(row, cols.get("zip")),
    ]
    return ", ".join(p for p in parts if p)


def _month_start(year: int, month: int) -> Optional[pd.Timestamp]:
    try:
        return pd.Timestamp(year=year, month=month, day=1)
    except ValueError:
        return None


def _month_end(ts: pd.Timestamp) -> pd.Timestamp:
    return (ts + pd.offsets.MonthEnd(0)).normalize()


def parse_sold_month(raw: object) -> Optional[pd.Timestamp]:
    """
    Parse external sale month from in_sold_properties_full.
    Accepts M/YYYY, MM/YYYY, M-YYYY, YYYY-MM, month names, and Excel/date values.
    Returns first-of-month Timestamp or None.
    """
    if raw is None or (isinstance(raw, float) and pd.isna(raw)):
        return None
    if isinstance(raw, datetime):
        return _month_start(raw.year, raw.month)
    if isinstance(raw, pd.Timestamp):
        if pd.isna(raw):
            return None
        return _month_start(int(raw.year), int(raw.month))

    text = str(raw).strip()
    if not text or text.lower() in ("nan", "none", "null", ""):
        return None

    m = _MONTH_SLASH_RE.match(text)
    if m:
        return _month_start(int(m.group(2)), int(m.group(1)))

    m = _YEAR_MONTH_RE.match(text)
    if m:
        return _month_start(int(m.group(1)), int(m.group(2)))

    m = _MONTH_NAME_RE.match(text)
    if m:
        mon = _MONTH_NAME_MAP.get(m.group(1)[:3].lower())
        if mon:
            return _month_start(int(m.group(2)), mon)

    parsed = pd.to_datetime(text, errors="coerce")
    if pd.notna(parsed):
        stamp = pd.Timestamp(parsed)
        return _month_start(int(stamp.year), int(stamp.month))
    return None


def _ym_label(ts: Optional[pd.Timestamp]) -> str:
    if ts is None or pd.isna(ts):
        return ""
    stamp = pd.Timestamp(ts)
    return f"{stamp.year:04d}-{stamp.month:02d}"


def _iso_day(ts: Optional[pd.Timestamp]) -> str:
    if ts is None or pd.isna(ts):
        return ""
    return pd.Timestamp(ts).date().isoformat()


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


def _pct(part: int, whole: int) -> float:
    if whole <= 0:
        return 0.0
    return round(100.0 * part / whole, 2)


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


# Prospect list sources beyond parse_tags List Purchased 8020.
_LIP_TAG_RE = re.compile(
    r"^Probates\s+NY\s+(Nassau|Queens|Suffolk)\s+(\d{1,2})-(\d{4})$",
    re.I,
)
_COURT_ALERTS_LIST_RE = re.compile(
    r"^List\s+Purchased\s+Court\s*Alerts?\s+(\d{1,2})[-/](\d{4})$",
    re.I,
)
_COURT_ALERTS_TAG_RE = re.compile(
    r"^Court\s*Alerts?\s+(?:NY\s+)?(?:Nassau|Queens|Suffolk|Erie|Monroe|Onondaga)?\s*"
    r"(\d{1,2})[-/](\d{4})$",
    re.I,
)


def _prospect_source_dates_from_tags(tags_str: object) -> List[Tuple[datetime, str]]:
    """
    Dated Prospect list events from Tags: 8020 (via caller/parsed), LI Profiles, Court Alerts.
    Returns (date, source_id) where source_id is eight | lip | court_alerts.
    """
    out: List[Tuple[datetime, str]] = []
    for part in str(tags_str or "").split(","):
        tag = part.strip()
        if not tag:
            continue
        m = _LIP_TAG_RE.match(tag)
        if m:
            month, year = int(m.group(2)), int(m.group(3))
            try:
                out.append((datetime(year, month, 1), "lip"))
            except ValueError:
                pass
            continue
        m = _COURT_ALERTS_LIST_RE.match(tag) or _COURT_ALERTS_TAG_RE.match(tag)
        if m:
            month, year = int(m.group(1)), int(m.group(2))
            try:
                out.append((datetime(year, month, 1), "court_alerts"))
            except ValueError:
                pass
    return out


def _lists_has_prospect_source(lists_str: object) -> Optional[str]:
    """If Lists names a Prospect provider, return source_id (no month)."""
    text = " ".join(str(lists_str or "").lower().split())
    if not text:
        return None
    if "court alert" in text or "courtalert" in text:
        return "court_alerts"
    if (
        "li profile" in text
        or "long island profile" in text
        or "probate" in text
    ):
        return "lip"
    # Distress 8020 lists — not "8020 source list" hygiene import.
    if re.search(r"\b8020\b", text) and "source list" not in text:
        return "8020"
    return None


def earliest_prospect_list(
    parsed: List[Dict[str, Any]],
    tags_str: object = "",
    lists_str: object = "",
) -> Tuple[Optional[datetime], str]:
    """
    Earliest Prospect list month among 8020, Court Alerts, LI Profiles.

    Prefers parse_tags list_purchase events (canonical). Falls back to Lists names
    when no dated tag exists. Returns (date_or_none, source_id) where source_id is
    8020 | lip | court_alerts | "".
    """
    candidates: List[Tuple[datetime, str]] = []
    for p in parsed:
        if p.get("type") != "list_purchase":
            continue
        dt = _parse_iso_dt(str(p.get("date", "")))
        if dt is None:
            continue
        label = str(p.get("label") or "8020").strip().lower()
        if label in ("eight", ""):
            label = "8020"
        if label not in ("8020", "lip", "court_alerts"):
            label = "8020"
        candidates.append((dt, label))
    # Legacy / extra tag shapes not yet in parse_tags (keep in sync defensively).
    for dt, src in _prospect_source_dates_from_tags(tags_str):
        mapped = "8020" if src == "eight" else src
        if not any(c[0] == dt and c[1] == mapped for c in candidates):
            candidates.append((dt, mapped))
    if not candidates:
        src = _lists_has_prospect_source(lists_str)
        if src == "eight":
            src = "8020"
        return None, (src or "")
    best_dt, best_src = min(candidates, key=lambda x: x[0])
    return best_dt, best_src


def _contact_touch_stats(
    parsed: List[Dict[str, Any]],
    *,
    on_or_before: Optional[datetime] = None,
) -> Tuple[Dict[str, int], Optional[str], Optional[str]]:
    """Count CC/SMS/DM contact tags (optionally capped at sold month); first touch."""
    counts = {ch: 0 for ch in TOUCH_CHANNELS}
    touches: List[Tuple[datetime, str]] = []
    for p in parsed:
        if p.get("type") != "contact":
            continue
        ch = str(p.get("channel") or p.get("label") or "").upper()
        if ch not in counts:
            continue
        dt = _parse_iso_dt(str(p.get("date", "")))
        if on_or_before is not None and dt is not None and dt > on_or_before:
            continue
        counts[ch] += 1
        if dt is not None:
            touches.append((dt, ch))
    if not touches:
        return counts, None, None
    touches.sort(key=lambda x: x[0])
    first_dt, first_ch = touches[0]
    return counts, first_ch, first_dt.isoformat()


def _pipeline_rank(stage: str) -> int:
    try:
        return PIPELINE_ORDER.index(stage)
    except ValueError:
        return 0


def _max_pipeline(*stages: str) -> str:
    best = "NONE"
    for s in stages:
        if _pipeline_rank(s) > _pipeline_rank(best):
            best = s
    return best


@dataclass
class SoldPropertyRow:
    address: str = ""
    address_key: str = ""
    street: str = ""
    city: str = ""
    state: str = ""
    zip: str = ""
    sold_month: str = ""
    sold_month_raw: str = ""
    created: str = ""
    lists: str = ""
    list_purchase_date: str = ""
    marketed: bool = False
    cc_touch_count: int = 0
    sms_touch_count: int = 0
    dm_touch_count: int = 0
    first_touch_channel: str = ""
    first_touch_date: str = ""
    lead_matched: bool = False
    lead_date: str = ""
    lead_source: str = ""  # podio | sf_tag | ""
    qualified_lead_matched: bool = False
    qualified_lead_date: str = ""
    qualified_lead_match_via: str = ""
    # Back-compat: lead OR qualified lead (old bundled "prospect" match)
    prospect_matched: bool = False
    prospect_date: str = ""
    prospect_match_via: str = ""
    prospect_source: str = ""  # ql | sf_tag | podio | ""
    opp_matched: bool = False
    opp_created_date: str = ""
    under_contract_date: str = ""
    hhb_closed_date: str = ""
    highest_lifecycle_stage: str = "NONE"
    pipeline_stage: str = "NONE"
    pipeline_stage_label: str = ""
    days_list_to_sold: Optional[int] = None
    months_list_to_sold: Optional[int] = None
    days_list_to_qualified_lead: Optional[int] = None
    months_list_to_qualified_lead: Optional[int] = None
    # Alias for older consumers (lag to QL Create Date)
    days_list_to_prospect: Optional[int] = None
    months_list_to_prospect: Optional[int] = None
    tags: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "address": self.address,
            "address_key": self.address_key,
            "street": self.street,
            "city": self.city,
            "state": self.state,
            "zip": self.zip,
            "sold_month": self.sold_month,
            "sold_month_raw": self.sold_month_raw,
            "created": self.created,
            "lists": self.lists,
            "list_purchase_date": self.list_purchase_date,
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
            "qualified_lead_match_via": self.qualified_lead_match_via,
            "prospect_matched": self.prospect_matched,
            "prospect_date": self.prospect_date,
            "prospect_match_via": self.prospect_match_via,
            "prospect_source": self.prospect_source,
            "opp_matched": self.opp_matched,
            "opp_created_date": self.opp_created_date,
            "under_contract_date": self.under_contract_date,
            "hhb_closed_date": self.hhb_closed_date,
            "highest_lifecycle_stage": self.highest_lifecycle_stage,
            "pipeline_stage": self.pipeline_stage,
            "pipeline_stage_label": self.pipeline_stage_label,
            "days_list_to_sold": self.days_list_to_sold,
            "months_list_to_sold": self.months_list_to_sold,
            "days_list_to_qualified_lead": self.days_list_to_qualified_lead,
            "months_list_to_qualified_lead": self.months_list_to_qualified_lead,
            "days_list_to_prospect": self.days_list_to_prospect,
            "months_list_to_prospect": self.months_list_to_prospect,
            "tags": self.tags,
        }


@dataclass
class SoldPropertiesResult:
    reisift_rows_ingested: int = 0
    cohort_rows: int = 0
    sold_month_unparseable: int = 0
    marketed_count: int = 0
    marketed_pct: float = 0.0
    lead_matched: int = 0
    lead_rate_pct: float = 0.0
    qualified_lead_matched: int = 0
    qualified_lead_rate_pct: float = 0.0
    prospect_matched: int = 0  # lead OR qualified lead (compat)
    prospect_rate_pct: float = 0.0
    opp_matched: int = 0
    opp_rate_pct: float = 0.0
    under_contract_count: int = 0
    hhb_closed_count: int = 0
    total_touch_counts: Dict[str, int] = field(default_factory=dict)
    avg_touches_per_marketed: Optional[float] = None
    pipeline_funnel: List[Dict[str, Any]] = field(default_factory=list)
    by_sold_month: List[Dict[str, Any]] = field(default_factory=list)
    lifecycle_funnel: List[Dict[str, Any]] = field(default_factory=list)
    mean_months_list_to_sold: Optional[float] = None
    median_months_list_to_sold: Optional[float] = None
    mean_months_list_to_qualified_lead: Optional[float] = None
    median_months_list_to_qualified_lead: Optional[float] = None
    mean_months_list_to_prospect: Optional[float] = None
    median_months_list_to_prospect: Optional[float] = None
    rows: List[SoldPropertyRow] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    methodology_note: str = ""
    date_window_start: str = ""
    date_window_end: str = ""

    def to_api_dict(self) -> Dict[str, Any]:
        return {
            "report_type": REPORT_TYPE,
            "date_window_start": self.date_window_start,
            "date_window_end": self.date_window_end,
            "inputs": {
                "reisift_rows_ingested": self.reisift_rows_ingested,
                "cohort_rows": self.cohort_rows,
                "sold_month_unparseable": self.sold_month_unparseable,
            },
            "marketing": {
                "marketed_count": self.marketed_count,
                "marketed_pct": self.marketed_pct,
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
            "lifecycle_funnel": self.lifecycle_funnel,
            "by_sold_month": self.by_sold_month,
            "rows": [r.to_dict() for r in self.rows],
            "warnings": self.warnings,
            "methodology_note": self.methodology_note,
        }


def _row_kwargs(item: Dict[str, Any]) -> Dict[str, Any]:
    allowed = {f.name for f in SoldPropertyRow.__dataclass_fields__.values()}  # type: ignore[attr-defined]
    out: Dict[str, Any] = {}
    for k in allowed:
        out[k] = item.get(k)
    out["marketed"] = bool(out.get("marketed"))
    out["lead_matched"] = bool(out.get("lead_matched"))
    out["qualified_lead_matched"] = bool(out.get("qualified_lead_matched"))
    out["prospect_matched"] = bool(out.get("prospect_matched"))
    out["opp_matched"] = bool(out.get("opp_matched"))
    for int_key in ("cc_touch_count", "sms_touch_count", "dm_touch_count"):
        out[int_key] = int(out.get(int_key) or 0)
    for str_key in (
        "address",
        "address_key",
        "street",
        "city",
        "state",
        "zip",
        "sold_month",
        "sold_month_raw",
        "created",
        "lists",
        "list_purchase_date",
        "first_touch_channel",
        "first_touch_date",
        "lead_date",
        "lead_source",
        "qualified_lead_date",
        "qualified_lead_match_via",
        "prospect_date",
        "prospect_match_via",
        "prospect_source",
        "opp_created_date",
        "under_contract_date",
        "hhb_closed_date",
        "highest_lifecycle_stage",
        "pipeline_stage",
        "pipeline_stage_label",
        "tags",
    ):
        out[str_key] = str(out.get(str_key) or "")
    return out


def result_from_metrics_dict(metrics: Dict[str, Any]) -> SoldPropertiesResult:
    rows = [SoldPropertyRow(**_row_kwargs(item)) for item in metrics.get("rows") or []]
    inputs = metrics.get("inputs") or {}
    marketing = metrics.get("marketing") or {}
    match = metrics.get("match") or {}
    lag = metrics.get("lag") or {}
    return SoldPropertiesResult(
        reisift_rows_ingested=int(inputs.get("reisift_rows_ingested") or 0),
        cohort_rows=int(inputs.get("cohort_rows") or 0),
        sold_month_unparseable=int(inputs.get("sold_month_unparseable") or 0),
        marketed_count=int(marketing.get("marketed_count") or 0),
        marketed_pct=float(marketing.get("marketed_pct") or 0),
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
        total_touch_counts=dict(marketing.get("total_touch_counts") or {}),
        avg_touches_per_marketed=marketing.get("avg_touches_per_marketed"),
        pipeline_funnel=list(metrics.get("pipeline_funnel") or []),
        by_sold_month=list(metrics.get("by_sold_month") or []),
        lifecycle_funnel=list(metrics.get("lifecycle_funnel") or []),
        mean_months_list_to_sold=lag.get("mean_months_list_to_sold"),
        median_months_list_to_sold=lag.get("median_months_list_to_sold"),
        mean_months_list_to_qualified_lead=lag.get("mean_months_list_to_qualified_lead"),
        median_months_list_to_qualified_lead=lag.get("median_months_list_to_qualified_lead"),
        mean_months_list_to_prospect=lag.get("mean_months_list_to_prospect"),
        median_months_list_to_prospect=lag.get("median_months_list_to_prospect"),
        rows=rows,
        warnings=list(metrics.get("warnings") or []),
        methodology_note=str(metrics.get("methodology_note") or ""),
        date_window_start=str(metrics.get("date_window_start") or ""),
        date_window_end=str(metrics.get("date_window_end") or ""),
    )


def _mean_median(values: List[int]) -> Tuple[Optional[float], Optional[float]]:
    if not values:
        return None, None
    series = pd.Series(values, dtype="float64")
    return round(float(series.mean()), 2), round(float(series.median()), 2)


def _sf_engaged_before(parsed: List[Dict[str, Any]], sold_end: datetime) -> bool:
    for p in parsed:
        if p.get("type") not in ("sf_updated", "sf_status"):
            continue
        label = normalize_status(str(p.get("label", "")))
        if label not in ENGAGED_LABELS:
            continue
        dt = _parse_iso_dt(str(p.get("date", "")))
        if dt is not None and dt <= sold_end:
            return True
    return False


def _podio_crm_present(parsed: List[Dict[str, Any]]) -> bool:
    """PodioSellerLeads is a presence flag — no sold-month date gate."""
    return any(p.get("type") == "podio_crm" for p in parsed)


def _first_podio_crm_date(parsed: List[Dict[str, Any]]) -> str:
    for p in parsed:
        if p.get("type") != "podio_crm":
            continue
        raw = str(p.get("date", "") or "").strip()
        if not raw:
            continue
        dt = _parse_iso_dt(raw)
        if dt is not None:
            return dt.date().isoformat()
    return ""


def analyze(
    reisift_path: str,
    ql_path: str,
    opportunities_path: Optional[str] = None,
    on_progress: Optional[ProgressCallback] = None,
) -> SoldPropertiesResult:
    def report(pct: int, message: str) -> None:
        if on_progress:
            on_progress(pct, message)

    warnings: List[str] = []
    report(8, "Loading REISift export…")
    reisift_df = load_reisift_file(reisift_path)
    tags_col = find_column_name(reisift_df, TAGS_CANDIDATES)
    if not tags_col:
        raise ValueError("Missing required column: Tags")
    sold_col = find_column_name(reisift_df, SOLD_MONTH_CANDIDATES)
    if not sold_col:
        raise ValueError(
            "Missing required column: in_sold_properties_full "
            "(aliases: Sold Month, in_sold_properties)"
        )

    created_col = find_column_name(reisift_df, CREATED_CANDIDATES)
    lists_col = find_column_name(reisift_df, LISTS_CANDIDATES)
    addr_cols = _discover_addr_cols(reisift_df)

    report(18, "Loading Salesforce qualified leads…")
    ql_df = _load_crm_file(ql_path)
    ql_index = _build_match_index(
        ql_df,
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

    report(40, "Building sold-properties cohort…")
    rows: List[SoldPropertyRow] = []
    unparseable = 0
    sold_months: List[pd.Timestamp] = []

    total = len(reisift_df)
    for i, (_, row) in enumerate(reisift_df.iterrows()):
        if total and i % 500 == 0:
            report(40 + int(40 * i / total), f"Scanning sold cohort… ({i}/{total})")

        raw_sold = row.get(sold_col, "")
        if raw_sold is None or (isinstance(raw_sold, float) and pd.isna(raw_sold)):
            continue
        raw_text = str(raw_sold).strip()
        if not raw_text or raw_text.lower() in ("nan", "none", "null", "0", "false"):
            continue

        sold_ts = parse_sold_month(raw_sold)
        if sold_ts is None:
            unparseable += 1
            continue

        sold_end = _month_end(sold_ts)
        sold_end_dt = sold_end.to_pydatetime()
        sold_months.append(sold_ts)

        tags_val = str(row.get(tags_col, "") or "").strip()
        parsed = _parse_tags_merged(tags_val) if tags_val else []
        events = build_events(parsed)
        stages = compute_stage_funnel_open(events, sold_end)
        # CLOSED from HHB tag still matters if before sold month end
        milestones = resolve_milestones_from_parsed(parsed)
        hhb_closed = milestones.date_closed
        if hhb_closed is not None and hhb_closed <= sold_end_dt:
            stages["CLOSED"] = {"reached": True, "date": hhb_closed.date().isoformat()}
        else:
            stages["CLOSED"] = {"reached": False, "date": None}
            hhb_closed = None

        highest = get_highest_stage(stages)
        if stages.get("CLOSED", {}).get("reached"):
            highest = "CLOSED"

        list_dt, prospect_list_source = earliest_prospect_list(
            parsed, tags_val, _col_val(row, lists_col)
        )
        list_purchase_ymd = list_dt.date().isoformat() if list_dt else ""
        created_raw = _col_val(row, created_col)
        created_ts = pd.to_datetime(created_raw, errors="coerce") if created_raw else pd.NaT
        if list_dt is None and pd.notna(created_ts):
            list_dt = created_ts.to_pydatetime()
        lists_only_src = _lists_has_prospect_source(_col_val(row, lists_col))
        if not prospect_list_source and lists_only_src:
            prospect_list_source = lists_only_src

        touch_counts, first_ch, first_date = _contact_touch_stats(
            parsed, on_or_before=sold_end_dt
        )
        marketed = sum(touch_counts.values()) > 0

        key = _address_key_from_row(row, addr_cols)
        phones = _phones_from_row(row, REISIFT_PHONE_CANDIDATES)
        first_list_month = (
            pd.Timestamp(year=list_dt.year, month=list_dt.month, day=1)
            if list_dt
            else None
        )

        ql_hit = _best_hit(
            ql_index,
            key,
            phones,
            on_or_after=first_list_month,
            before=sold_end + pd.Timedelta(days=1),
        )
        # `_best_hit(..., before=)` keeps rows with lag < 0 vs before — i.e. date < before.
        # Sold end + 1 day means Create Date on or before sold month end.

        prospect_from_ql = ql_hit is not None and ql_hit.date is not None
        prospect_from_sf = _sf_engaged_before(parsed, sold_end_dt)
        prospect_from_podio = _podio_crm_present(parsed)

        lead_matched = prospect_from_sf or prospect_from_podio
        qualified_lead_matched = prospect_from_ql
        prospect_matched = lead_matched or qualified_lead_matched

        lead_date = ""
        lead_source = ""
        qualified_lead_date = ""
        qualified_lead_via = ""
        prospect_date = ""
        prospect_via = ""
        prospect_source = ""

        if prospect_from_sf:
            for p in parsed:
                if p.get("type") not in ("sf_updated", "sf_status"):
                    continue
                label = normalize_status(str(p.get("label", "")))
                if label not in ENGAGED_LABELS:
                    continue
                dt = _parse_iso_dt(str(p.get("date", "")))
                if dt is not None and dt <= sold_end_dt:
                    lead_date = dt.date().isoformat()
                    lead_source = "sf_tag"
                    break
            if not lead_source:
                lead_source = "sf_tag"
        if prospect_from_podio and not lead_source:
            lead_date = _first_podio_crm_date(parsed)
            lead_source = "podio"
        elif prospect_from_podio and lead_source == "sf_tag":
            # Both present: prefer SF date when available; still mark lead
            pass
        if prospect_from_podio and lead_source == "":
            lead_date = _first_podio_crm_date(parsed)
            lead_source = "podio"

        if prospect_from_ql and ql_hit is not None:
            qualified_lead_date = _iso_day(ql_hit.date)
            qualified_lead_via = ql_hit.via
            prospect_date = qualified_lead_date
            prospect_via = qualified_lead_via
            prospect_source = "ql"
        elif lead_source:
            prospect_date = lead_date
            prospect_via = lead_source
            prospect_source = lead_source

        opp_hit = None
        if opp_index is not None:
            opp_hit = _best_hit(
                opp_index,
                key,
                phones,
                on_or_after=first_list_month,
                before=sold_end + pd.Timedelta(days=1),
            )
        opp_matched = opp_hit is not None and opp_hit.date is not None
        opp_date = _iso_day(opp_hit.date) if opp_hit and opp_hit.date is not None else ""

        under_contract = milestones.date_under_contract
        if under_contract is not None and under_contract > sold_end_dt:
            under_contract = None
        under_ymd = under_contract.date().isoformat() if under_contract else ""
        hhb_ymd = hhb_closed.date().isoformat() if hhb_closed else ""
        # Under contract counts as Opportunity (not a separate stage).
        if under_contract is not None:
            opp_matched = True

        # Business pipeline: Prospect → Marketed → Lead → QL → Opp → Closed
        pipe = "NONE"
        if (
            list_purchase_ymd
            or prospect_list_source
            or lists_only_src
            or created_raw
        ):
            pipe = "PROSPECT"
        if marketed:
            pipe = _max_pipeline(pipe, "MARKETED")
        if lead_matched:
            pipe = _max_pipeline(pipe, "LEAD")
        if qualified_lead_matched:
            pipe = _max_pipeline(pipe, "QUALIFIED_LEAD")
        if opp_matched or under_contract is not None:
            pipe = _max_pipeline(pipe, "OPPORTUNITY")
        if hhb_closed is not None:
            pipe = _max_pipeline(pipe, "HHB_CLOSED")

        sold_anchor_dt = sold_end_dt
        days_list_to_sold = _days_between(list_dt, sold_anchor_dt) if list_dt else None
        months_list_to_sold = (
            months_between(pd.Timestamp(list_dt), sold_ts) if list_dt else None
        )
        ql_dt = _parse_iso_dt(qualified_lead_date) if qualified_lead_date else None
        days_list_to_ql = _days_between(list_dt, ql_dt) if list_dt else None
        months_list_to_ql = (
            months_between(pd.Timestamp(list_dt), pd.Timestamp(ql_dt))
            if list_dt and ql_dt
            else None
        )

        rows.append(
            SoldPropertyRow(
                address=_display_address(row, addr_cols),
                address_key=key,
                street=_col_val(row, addr_cols.get("street")),
                city=_col_val(row, addr_cols.get("city")),
                state=_col_val(row, addr_cols.get("state")),
                zip=_col_val(row, addr_cols.get("zip")),
                sold_month=_ym_label(sold_ts),
                sold_month_raw=raw_text,
                created=created_raw,
                lists=_col_val(row, lists_col),
                list_purchase_date=list_purchase_ymd,
                marketed=marketed,
                cc_touch_count=touch_counts["CC"],
                sms_touch_count=touch_counts["SMS"],
                dm_touch_count=touch_counts["DM"],
                first_touch_channel=first_ch or "",
                first_touch_date=first_date or "",
                lead_matched=lead_matched,
                lead_date=lead_date,
                lead_source=lead_source,
                qualified_lead_matched=qualified_lead_matched,
                qualified_lead_date=qualified_lead_date,
                qualified_lead_match_via=qualified_lead_via,
                prospect_matched=prospect_matched,
                prospect_date=prospect_date,
                prospect_match_via=prospect_via,
                prospect_source=prospect_source,
                opp_matched=opp_matched,
                opp_created_date=opp_date,
                under_contract_date=under_ymd,
                hhb_closed_date=hhb_ymd,
                highest_lifecycle_stage=highest,
                pipeline_stage=pipe,
                pipeline_stage_label=PIPELINE_LABELS.get(pipe, pipe),
                days_list_to_sold=days_list_to_sold,
                months_list_to_sold=months_list_to_sold,
                days_list_to_qualified_lead=days_list_to_ql,
                months_list_to_qualified_lead=months_list_to_ql,
                days_list_to_prospect=days_list_to_ql,
                months_list_to_prospect=months_list_to_ql,
                tags=tags_val,
            )
        )

    report(85, "Aggregating summary…")
    cohort_n = len(rows)
    marketed_n = sum(1 for r in rows if r.marketed)
    lead_n = sum(1 for r in rows if r.lead_matched)
    ql_n = sum(1 for r in rows if r.qualified_lead_matched)
    prospect_n = sum(1 for r in rows if r.prospect_matched)
    opp_n = sum(1 for r in rows if r.opp_matched)
    uc_n = sum(1 for r in rows if r.under_contract_date)
    closed_n = sum(1 for r in rows if r.hhb_closed_date)

    total_touches = {
        ch: sum(int(getattr(r, f"{ch.lower()}_touch_count")) for r in rows)
        for ch in TOUCH_CHANNELS
    }
    touch_sum = sum(total_touches.values())
    avg_touches = round(touch_sum / marketed_n, 2) if marketed_n else None

    pipe_counter: Counter[str] = Counter(r.pipeline_stage for r in rows)
    pipeline_funnel = [
        {
            "stage": stage,
            "label": PIPELINE_LABELS.get(stage, stage),
            "count": pipe_counter.get(stage, 0),
            "share_pct": _pct(pipe_counter.get(stage, 0), cohort_n),
        }
        for stage in PIPELINE_ORDER
        if pipe_counter.get(stage, 0) > 0 or stage in PIPELINE_FUNNEL_ALWAYS
    ]

    life_counter: Counter[str] = Counter(r.highest_lifecycle_stage for r in rows)
    lifecycle_funnel = [
        {
            "stage": stage,
            "count": life_counter.get(stage, 0),
            "share_pct": _pct(life_counter.get(stage, 0), cohort_n),
        }
        for stage in list(STAGE_ORDER) + ["NONE"]
        if life_counter.get(stage, 0) > 0
    ]

    by_month_stats: Dict[str, Dict[str, Any]] = {}
    for r in rows:
        key = r.sold_month or "(unknown)"
        bucket = by_month_stats.setdefault(
            key,
            {
                "sold_month": key,
                "count": 0,
                "marketed": 0,
                "leads": 0,
                "qualified_leads": 0,
                "prospects": 0,
                "opportunities": 0,
                "under_contract": 0,
                "hhb_closed": 0,
            },
        )
        bucket["count"] += 1
        if r.marketed:
            bucket["marketed"] += 1
        if r.lead_matched:
            bucket["leads"] += 1
        if r.qualified_lead_matched:
            bucket["qualified_leads"] += 1
        if r.prospect_matched:
            bucket["prospects"] += 1
        if r.opp_matched:
            bucket["opportunities"] += 1
        if r.under_contract_date:
            bucket["under_contract"] += 1
        if r.hhb_closed_date:
            bucket["hhb_closed"] += 1
    by_sold_month = sorted(by_month_stats.values(), key=lambda x: x["sold_month"])

    months_to_sold = [m for m in (r.months_list_to_sold for r in rows) if m is not None]
    months_to_ql = [
        m for m in (r.months_list_to_qualified_lead for r in rows) if m is not None
    ]
    mean_sold, median_sold = _mean_median(months_to_sold)
    mean_ql, median_ql = _mean_median(months_to_ql)

    if sold_months:
        date_window_start = _ym_label(min(sold_months))
        date_window_end = _ym_label(max(sold_months))
    else:
        date_window_start = ""
        date_window_end = ""

    if unparseable:
        warnings.append(
            f"{unparseable} row(s) had a non-empty in_sold_properties_full value that "
            "could not be parsed as a month and were excluded."
        )

    methodology_note = (
        "Cohort = REISift rows with a parseable in_sold_properties_full sale month "
        f"(external sale, not an HHB closing). Canonical pipeline: {CANONICAL_PIPELINE}. "
        "List purchase tags remain source credit; "
        "Create Date is a Qualified Lead clock only. Never-marketed rows are often DNC / "
        "suppression. Why they sold elsewhere is out of scope."
    )

    report(100, "Done")
    return SoldPropertiesResult(
        reisift_rows_ingested=len(reisift_df),
        cohort_rows=cohort_n,
        sold_month_unparseable=unparseable,
        marketed_count=marketed_n,
        marketed_pct=_pct(marketed_n, cohort_n),
        lead_matched=lead_n,
        lead_rate_pct=_pct(lead_n, cohort_n),
        qualified_lead_matched=ql_n,
        qualified_lead_rate_pct=_pct(ql_n, cohort_n),
        prospect_matched=prospect_n,
        prospect_rate_pct=_pct(prospect_n, cohort_n),
        opp_matched=opp_n,
        opp_rate_pct=_pct(opp_n, cohort_n),
        under_contract_count=uc_n,
        hhb_closed_count=closed_n,
        total_touch_counts=total_touches,
        avg_touches_per_marketed=avg_touches,
        pipeline_funnel=pipeline_funnel,
        by_sold_month=by_sold_month,
        lifecycle_funnel=lifecycle_funnel,
        mean_months_list_to_sold=mean_sold,
        median_months_list_to_sold=median_sold,
        mean_months_list_to_qualified_lead=mean_ql,
        median_months_list_to_qualified_lead=median_ql,
        mean_months_list_to_prospect=mean_ql,
        median_months_list_to_prospect=median_ql,
        rows=rows,
        warnings=warnings,
        methodology_note=methodology_note,
        date_window_start=date_window_start,
        date_window_end=date_window_end,
    )


def build_export_workbook(result: SoldPropertiesResult) -> bytes:
    try:
        import openpyxl  # noqa: F401
    except ImportError as exc:
        raise ValueError("Export requires openpyxl") from exc

    summary_rows = [
        {"metric": "REISift rows ingested", "value": result.reisift_rows_ingested},
        {"metric": "Sold cohort rows", "value": result.cohort_rows},
        {"metric": "Sold month unparseable (excluded)", "value": result.sold_month_unparseable},
        {"metric": "Marketed count", "value": result.marketed_count},
        {"metric": "Marketed %", "value": result.marketed_pct},
        {"metric": "Lead matched", "value": result.lead_matched},
        {"metric": "Lead %", "value": result.lead_rate_pct},
        {"metric": "Qualified Lead matched", "value": result.qualified_lead_matched},
        {"metric": "Qualified Lead %", "value": result.qualified_lead_rate_pct},
        {"metric": "Opportunity matched", "value": result.opp_matched},
        {"metric": "Opportunity %", "value": result.opp_rate_pct},
        {"metric": "Under contract", "value": result.under_contract_count},
        {"metric": "Closed", "value": result.hhb_closed_count},
        {"metric": "CC touches (total)", "value": result.total_touch_counts.get("CC", 0)},
        {"metric": "SMS touches (total)", "value": result.total_touch_counts.get("SMS", 0)},
        {"metric": "DM touches (total)", "value": result.total_touch_counts.get("DM", 0)},
        {"metric": "Avg touches per marketed", "value": result.avg_touches_per_marketed},
        {"metric": "Mean months list → sold", "value": result.mean_months_list_to_sold},
        {"metric": "Median months list → sold", "value": result.median_months_list_to_sold},
        {
            "metric": "Mean months list → prospect",
            "value": result.mean_months_list_to_prospect,
        },
        {
            "metric": "Median months list → prospect",
            "value": result.median_months_list_to_prospect,
        },
        {"metric": "Sold month span start", "value": result.date_window_start},
        {"metric": "Sold month span end", "value": result.date_window_end},
        {"metric": "Methodology", "value": result.methodology_note},
    ]
    for w in result.warnings:
        summary_rows.append({"metric": "Warning", "value": w})

    journey = [r.to_dict() for r in result.rows]
    never_marketed = [r.to_dict() for r in result.rows if not r.marketed]
    summary_rows.insert(
        5,
        {"metric": "Never marketed count", "value": len(never_marketed)},
    )
    buf = BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        pd.DataFrame(summary_rows).to_excel(writer, sheet_name="Summary", index=False)
        pd.DataFrame(journey).to_excel(writer, sheet_name="Journey", index=False)
        pd.DataFrame(never_marketed).to_excel(
            writer, sheet_name="Never Marketed", index=False
        )
        if result.pipeline_funnel:
            pd.DataFrame(result.pipeline_funnel).to_excel(
                writer, sheet_name="Pipeline Funnel", index=False
            )
        if result.by_sold_month:
            pd.DataFrame(result.by_sold_month).to_excel(
                writer, sheet_name="By Sold Month", index=False
            )
        if result.lifecycle_funnel:
            pd.DataFrame(result.lifecycle_funnel).to_excel(
                writer, sheet_name="Lifecycle Funnel", index=False
            )
    return buf.getvalue()
