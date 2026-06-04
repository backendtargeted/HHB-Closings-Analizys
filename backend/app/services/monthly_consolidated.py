"""
Consolidated list-performance report: full REISift export + SF qualified leads.

Default cohort is every row in the uploaded REISift file (no month filter).
Optional report_month (YYYY-MM) remains for API callers that need a Created-date window.
"""

from __future__ import annotations

import calendar
import re
import statistics
from dataclasses import dataclass, field
from datetime import date
from io import BytesIO
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

ProgressCallback = Callable[[int, str], None]

import pandas as pd

from .analysis import (
    analyze_contacts,
    parse_tags,
    _dedupe_parsed_tag_events,
)
from .lifecycle import (
    aggregate_lifecycle_stats,
    aggregate_stuck_at_stage,
    build_events,
    compute_stage_funnel_open,
    get_highest_stage,
)
from .marketing_mapper import find_column_name, make_address_key, smart_read_csv
from .qualified_leads import (
    compute_qualified_leads_metrics,
    load_qualified_leads_file,
    validate_and_prepare,
)

REPORT_TYPE = "monthly_consolidated"

CREATED_CANDIDATES = ["Created", "Created Date", "Created on"]
TAGS_CANDIDATES = ["Tags"]
LISTS_CANDIDATES = ["Lists"]

REISIFT_ADDR = {
    "street": ["Property address", "Property Address", "Address"],
    "city": ["Property city", "Property City", "City"],
    "state": ["Property state", "Property State", "State"],
    "zip": ["Property zip", "Property zip5", "Property Zip", "Zip"],
}

SF_ADDR = {
    "street": ["Street", "Mailing address", "Property address", "Property Address"],
    "city": ["City", "Mailing city", "Property city"],
    "state": ["State/Province", "State", "Mailing state", "Property state"],
    "zip": ["Zip/Postal Code", "Zip", "Mailing zip", "Property zip"],
}

COMBO_EXPORT_CAP = 100
COMBO_MIN_ROWS_FLOOR = 5
COMBO_MIN_ROWS_DEFAULT = 10
QL_MATCH_WARN_THRESHOLD = 0.5

# Not distress lists — excluded from list ranking, combinations, stacking, and QL attribution.
EXCLUDED_LIST_TOKENS: frozenset[str] = frozenset(
    {
        # Source / import
        "8020 source list",
        "podio (source)",
        "appraiva (source list)",
        # Hygiene / operational (incl. REISift tokens split from legacy combined names)
        "dnc + dead deals",
        "dnc",
        "dead deals",
        "closings app",
        "mlsli",
        "tbd",
        "closings app mlsli tbd",
        "buyers (investorbase)",
    }
)


def _normalize_list_token(token: str) -> str:
    return " ".join(str(token or "").strip().lower().split())


def is_excluded_list_token(token: str) -> bool:
    return _normalize_list_token(token) in EXCLUDED_LIST_TOKENS


def is_non_stack_list_token(token: str) -> bool:
    """Backward-compatible alias: hygiene lists are fully excluded now."""
    return is_excluded_list_token(token)


def analysis_list_tokens(lists_str: object) -> List[str]:
    """Distress lists used for ranking; omits source/import and hygiene lists."""
    return [t for t in split_list_tokens(lists_str) if not is_excluded_list_token(t)]


def stackable_list_tokens(lists_str: object) -> List[str]:
    """Lists that count toward stacked rows and list combinations (distress only)."""
    return analysis_list_tokens(lists_str)


def parse_report_month(value: str) -> Tuple[date, date]:
    """YYYY-MM -> (first day, last day) inclusive."""
    text = (value or "").strip()
    m = re.match(r"^(\d{4})-(\d{2})$", text)
    if not m:
        raise ValueError(f"Invalid report_month: {value!r} (use YYYY-MM)")
    year, month = int(m.group(1)), int(m.group(2))
    if month < 1 or month > 12:
        raise ValueError(f"Invalid report_month: {value!r}")
    last_day = calendar.monthrange(year, month)[1]
    return date(year, month, 1), date(year, month, last_day)


def load_reisift_file(file_path: str) -> pd.DataFrame:
    path = Path(file_path)
    if path.suffix.lower() in (".xlsx", ".xls"):
        try:
            return pd.read_excel(file_path, engine="openpyxl")
        except ImportError as exc:
            raise ValueError("Reading Excel requires openpyxl") from exc
    return smart_read_csv(file_path)


def _require_column(df: pd.DataFrame, candidates: List[str], label: str) -> str:
    col = find_column_name(df, candidates)
    if not col:
        raise ValueError(f"Missing required column: {label}")
    return col


def _parse_created_series(series: pd.Series) -> pd.Series:
    return pd.to_datetime(series, errors="coerce").dt.normalize()


def prepare_reisift_cohort(
    df: pd.DataFrame,
    start: Optional[date] = None,
    end: Optional[date] = None,
) -> Tuple[pd.DataFrame, Optional[str], str]:
    """
    Validate REISift export and return analysis cohort.

    scope is ``full_file`` (all rows) or ``calendar_month`` (Created in [start, end]).
    """
    _require_column(df, TAGS_CANDIDATES, "Tags")
    _require_column(df, LISTS_CANDIDATES, "Lists")
    created_col = find_column_name(df, CREATED_CANDIDATES)

    if start is None or end is None:
        return df.copy().reset_index(drop=True), created_col, "full_file"

    if not created_col:
        raise ValueError("Missing required column: Created (needed when report_month is set)")

    out = df.copy()
    out["_created_parsed"] = _parse_created_series(out[created_col])
    window_start = pd.Timestamp(start)
    window_end = pd.Timestamp(end) + pd.Timedelta(days=1) - pd.Timedelta(microseconds=1)
    mask = out["_created_parsed"].notna() & (
        out["_created_parsed"] >= window_start
    ) & (out["_created_parsed"] <= window_end)
    cohort = out.loc[mask].copy().reset_index(drop=True)
    return cohort, created_col, "calendar_month"


def filter_reisift_cohort(df: pd.DataFrame, start: date, end: date) -> Tuple[pd.DataFrame, str]:
    """Backward-compatible wrapper for month-scoped cohort."""
    cohort, created_col, _ = prepare_reisift_cohort(df, start, end)
    return cohort, created_col or ""


def row_has_sf_tag(tags_str: object) -> bool:
    if pd.isna(tags_str) or not str(tags_str).strip():
        return False
    for tag in str(tags_str).split(","):
        if tag.strip().upper().startswith("(SF)"):
            return True
    return False


def _parsed_has_closing(parsed: List[Dict[str, Any]]) -> bool:
    return any(p.get("type") == "closing" for p in parsed)


def row_has_closing_tag(tags_str: object) -> bool:
    if pd.isna(tags_str) or not str(tags_str).strip():
        return False
    text = str(tags_str)
    if "(CLOSED)" not in text.upper():
        return False
    parsed = _dedupe_parsed_tag_events(parse_tags(text))
    return _parsed_has_closing(parsed)


def _parse_tags_cached(tags_str: object) -> List[Dict[str, Any]]:
    if pd.isna(tags_str) or not str(tags_str).strip():
        return []
    return _dedupe_parsed_tag_events(parse_tags(str(tags_str)))


def split_list_tokens(lists_str: object) -> List[str]:
    if pd.isna(lists_str) or not str(lists_str).strip():
        return []
    seen: set = set()
    tokens: List[str] = []
    for part in str(lists_str).split(","):
        t = part.strip()
        if not t or t in seen:
            continue
        seen.add(t)
        tokens.append(t)
    return tokens


def _reisift_address_key(row: pd.Series) -> str:
    street = _col_val(row, REISIFT_ADDR["street"])
    city = _col_val(row, REISIFT_ADDR["city"])
    state = _col_val(row, REISIFT_ADDR["state"])
    zip_code = _col_val(row, REISIFT_ADDR["zip"])
    return make_address_key(street, city, state, zip_code)


def _sf_address_key(row: pd.Series, cols: Dict[str, Optional[str]]) -> str:
    return make_address_key(
        row.get(cols["street"], "") if cols["street"] else "",
        row.get(cols["city"], "") if cols["city"] else "",
        row.get(cols["state"], "") if cols["state"] else "",
        row.get(cols["zip"], "") if cols["zip"] else "",
    )


def _col_val(row: pd.Series, candidates: List[str]) -> str:
    for name in candidates:
        if name in row.index and pd.notna(row[name]):
            text = str(row[name]).strip()
            if text:
                return text
    return ""


def _discover_sf_addr_cols(df: pd.DataFrame) -> Dict[str, Optional[str]]:
    return {k: find_column_name(df, v) for k, v in SF_ADDR.items()}


@dataclass
class ListMetric:
    token: str
    row_count: int
    crm_lead_count: int
    qualified_lead_count: int
    closing_count: int
    closing_rate: float
    stacked_row_count: int

    def to_dict(self) -> Dict[str, Any]:
        return {
            "token": self.token,
            "row_count": self.row_count,
            "crm_lead_count": self.crm_lead_count,
            "qualified_lead_count": self.qualified_lead_count,
            "closing_count": self.closing_count,
            "closing_rate": self.closing_rate,
            "stacked_row_count": self.stacked_row_count,
        }


@dataclass
class ComboMetric:
    lists: List[str]
    lists_key: str
    row_count: int
    closing_count: int
    closing_rate: float
    combo_group: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "lists": self.lists,
            "lists_key": self.lists_key,
            "row_count": self.row_count,
            "closing_count": self.closing_count,
            "closing_rate": self.closing_rate,
            "combo_group": self.combo_group,
        }


@dataclass
class CohortScanResult:
    """Single-pass cohort aggregates (list metrics, combos, QL keys, lifecycle inputs)."""

    crm_lead_rows: int = 0
    closing_rows: int = 0
    stacked_rows: int = 0
    token_rows: Dict[str, int] = field(default_factory=dict)
    token_crm: Dict[str, int] = field(default_factory=dict)
    token_close: Dict[str, int] = field(default_factory=dict)
    token_stacked: Dict[str, int] = field(default_factory=dict)
    combo_groups: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    cohort_keys: Dict[str, List[str]] = field(default_factory=dict)
    tag_lead_source_counts: Dict[str, int] = field(default_factory=dict)
    open_pipeline_stages: List[str] = field(default_factory=list)
    closing_matches: List[Dict[str, Any]] = field(default_factory=list)


@dataclass
class MonthlyConsolidatedResult:
    report_month: str
    cohort_scope: str
    period_start: str
    period_end: str
    reisift_rows_ingested: int
    cohort_rows: int
    crm_lead_rows: int
    closing_rows: int
    stacked_rows: int
    stacked_pct: float
    lists: List[ListMetric]
    combinations: List[ComboMetric]
    qualified_leads: Dict[str, Any]
    list_attribution: Dict[str, Any]
    lifecycle: Dict[str, Any]
    lifecycle_stats: Dict[str, Any] = field(default_factory=dict)
    open_pipeline_lifecycle: Dict[str, Any] = field(default_factory=dict)
    tag_lead_source_counts: List[Dict[str, Any]] = field(default_factory=list)
    combo_min_rows: int = COMBO_MIN_ROWS_DEFAULT
    warnings: List[str] = field(default_factory=list)
    methodology_note: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "report_type": REPORT_TYPE,
            "report_month": self.report_month,
            "cohort_scope": self.cohort_scope,
            "period": {"start": self.period_start, "end": self.period_end},
            "inputs": {
                "reisift_rows_ingested": self.reisift_rows_ingested,
                "cohort_rows": self.cohort_rows,
            },
            "cohort": {
                "total_rows": self.cohort_rows,
                "crm_lead_rows": self.crm_lead_rows,
                "closing_rows": self.closing_rows,
                "stacked_rows": self.stacked_rows,
                "stacked_pct": self.stacked_pct,
            },
            "lists": [m.to_dict() for m in self.lists],
            "combinations": [c.to_dict() for c in self.combinations],
            "combo_min_rows": self.combo_min_rows,
            "qualified_leads": self.qualified_leads,
            "list_attribution": self.list_attribution,
            "lifecycle": self.lifecycle,
            "lifecycle_stats": self.lifecycle_stats,
            "open_pipeline_lifecycle": self.open_pipeline_lifecycle,
            "tag_lead_source_counts": self.tag_lead_source_counts,
            "warnings": self.warnings,
            "methodology_note": self.methodology_note,
        }


def list_metrics_from_scan(
    scan: CohortScanResult, ql_by_list: Dict[str, int]
) -> List[ListMetric]:
    all_tokens = sorted(
        scan.token_rows.keys(),
        key=lambda x: (-scan.token_close.get(x, 0), -scan.token_rows[x], x),
    )
    metrics: List[ListMetric] = []
    for t in all_tokens:
        rc = scan.token_rows[t]
        cc = scan.token_close.get(t, 0)
        metrics.append(
            ListMetric(
                token=t,
                row_count=rc,
                crm_lead_count=scan.token_crm.get(t, 0),
                qualified_lead_count=ql_by_list.get(t, 0),
                closing_count=cc,
                closing_rate=round(cc / rc, 6) if rc else 0.0,
                stacked_row_count=scan.token_stacked.get(t, 0),
            )
        )
    return metrics


def compute_list_metrics(cohort_df: pd.DataFrame, ql_by_list: Dict[str, int]) -> List[ListMetric]:
    return list_metrics_from_scan(scan_cohort(cohort_df), ql_by_list)


def _iat_val(series: Optional[pd.Series], i: int) -> object:
    if series is None:
        return None
    return series.iat[i]


def _address_key_at(
    cohort_df: pd.DataFrame, i: int, addr_cols: Dict[str, Optional[str]]
) -> str:
    street_col = addr_cols.get("street")
    city_col = addr_cols.get("city")
    state_col = addr_cols.get("state")
    zip_col = addr_cols.get("zip")
    street = ""
    city = ""
    state = ""
    zip_code = ""
    if street_col:
        v = cohort_df[street_col].iat[i]
        if pd.notna(v):
            street = str(v).strip()
    if city_col:
        v = cohort_df[city_col].iat[i]
        if pd.notna(v):
            city = str(v).strip()
    if state_col:
        v = cohort_df[state_col].iat[i]
        if pd.notna(v):
            state = str(v).strip()
    if zip_col:
        v = cohort_df[zip_col].iat[i]
        if pd.notna(v):
            zip_code = str(v).strip()
    return make_address_key(street, city, state, zip_code)


def scan_cohort(
    cohort_df: pd.DataFrame,
    created_col: Optional[str] = None,
    default_end: Optional[pd.Timestamp] = None,
    on_progress: Optional[ProgressCallback] = None,
) -> CohortScanResult:
    """
    One pass over the cohort: list metrics, combinations, QL address keys,
    tag lead sources, CRM open-pipeline stages, and closing lifecycle inputs.
    """
    result = CohortScanResult()
    n = len(cohort_df)
    if n == 0:
        return result

    if default_end is None:
        default_end = pd.Timestamp.now()

    tags_series = cohort_df["Tags"] if "Tags" in cohort_df.columns else None
    lists_series = cohort_df["Lists"] if "Lists" in cohort_df.columns else None
    created_series = (
        cohort_df[created_col] if created_col and created_col in cohort_df.columns else None
    )
    addr_cols = {
        "street": find_column_name(cohort_df, REISIFT_ADDR["street"]),
        "city": find_column_name(cohort_df, REISIFT_ADDR["city"]),
        "state": find_column_name(cohort_df, REISIFT_ADDR["state"]),
        "zip": find_column_name(cohort_df, REISIFT_ADDR["zip"]),
    }
    progress_interval = max(25_000, n // 20) if n > 10_000 else 0

    for i in range(n):
        if progress_interval and on_progress and i > 0 and i % progress_interval == 0:
            pct = 20 + int(35 * i / n)
            on_progress(pct, f"Scanning cohort… ({i:,} / {n:,} rows)")

        tags_val = _iat_val(tags_series, i)
        lists_val = _iat_val(lists_series, i)

        has_sf = row_has_sf_tag(tags_val)
        parsed = _parse_tags_cached(tags_val)
        has_close = _parsed_has_closing(parsed)

        if has_sf:
            result.crm_lead_rows += 1
        if has_close:
            result.closing_rows += 1

        tokens = analysis_list_tokens(lists_val)
        stackable = stackable_list_tokens(lists_val)
        if len(stackable) > 1:
            result.stacked_rows += 1

        if tokens:
            is_stacked = len(stackable) > 1
            for t in tokens:
                result.token_rows[t] = result.token_rows.get(t, 0) + 1
                if has_sf:
                    result.token_crm[t] = result.token_crm.get(t, 0) + 1
                if has_close:
                    result.token_close[t] = result.token_close.get(t, 0) + 1
                if is_stacked:
                    result.token_stacked[t] = result.token_stacked.get(t, 0) + 1

        if len(stackable) >= 2:
            key_tuple = tuple(sorted(stackable))
            key = " + ".join(key_tuple)
            if key not in result.combo_groups:
                result.combo_groups[key] = {
                    "lists": list(key_tuple),
                    "row_count": 0,
                    "closing_count": 0,
                }
            result.combo_groups[key]["row_count"] += 1
            if has_close:
                result.combo_groups[key]["closing_count"] += 1

        addr_key = _address_key_at(cohort_df, i, addr_cols)
        if addr_key and addr_key != "|||" and tokens:
            bucket = result.cohort_keys.setdefault(addr_key, [])
            for t in tokens:
                if t not in bucket:
                    bucket.append(t)

        src = derive_tag_lead_source_from_parsed(parsed)
        result.tag_lead_source_counts[src] = (
            result.tag_lead_source_counts.get(src, 0) + 1
        )

        if has_sf and not has_close:
            contacts = parse_tags(str(tags_val or ""))
            events = build_events(contacts)
            ref_end = default_end
            if created_series is not None:
                parsed_created = pd.to_datetime(created_series.iat[i], errors="coerce")
                if pd.notna(parsed_created):
                    ref_end = pd.Timestamp(parsed_created)
            stages = compute_stage_funnel_open(events, ref_end)
            result.open_pipeline_stages.append(get_highest_stage(stages))

        if has_close:
            street_col = addr_cols.get("street")
            city_col = addr_cols.get("city")
            street = ""
            city = ""
            if street_col:
                v = cohort_df[street_col].iat[i]
                if pd.notna(v):
                    street = str(v).strip()
            if city_col:
                v = cohort_df[city_col].iat[i]
                if pd.notna(v):
                    city = str(v).strip()
            addr = f"{street} {city}".strip() or street or "Unknown"
            close_date = None
            for p in parsed:
                if p.get("type") == "closing":
                    close_date = p.get("date")
                    break
            idx = int(cohort_df.index[i])
            result.closing_matches.append(
                {
                    "deal_index": idx,
                    "csv_index": idx,
                    "closed_date": close_date or "",
                    "address": addr,
                    "lead_source": "Contact History Tags",
                    "csv_record": cohort_df.iloc[i].to_dict(),
                    "workbook_close": None,
                    "deal_meta": None,
                }
            )

    return result


def resolve_combo_min_rows(multi_list_counts: List[int]) -> int:
    """
    Dynamic floor for combination visibility: median row count among multi-list
    stackable combos, bounded below by COMBO_MIN_ROWS_FLOOR.
    """
    if not multi_list_counts:
        return COMBO_MIN_ROWS_DEFAULT
    if len(multi_list_counts) == 1:
        return max(COMBO_MIN_ROWS_FLOOR, multi_list_counts[0])
    med = statistics.median(multi_list_counts)
    return max(COMBO_MIN_ROWS_FLOOR, int(round(med)))


def _combo_group_for_lists(
    lists: List[str],
    list_closing_by_token: Dict[str, int],
    list_rows_by_token: Dict[str, int],
) -> str:
    """Group label = stackable list in the combo with the most closings (then rows)."""
    if not lists:
        return ""
    if len(lists) == 1:
        return lists[0]

    def sort_key(token: str) -> Tuple[int, int, str]:
        return (
            -list_closing_by_token.get(token, 0),
            -list_rows_by_token.get(token, 0),
            token.lower(),
        )

    return sorted(lists, key=sort_key)[0]


def combinations_from_scan(
    scan: CohortScanResult,
    min_rows: Optional[int] = None,
    list_metrics: Optional[List[ListMetric]] = None,
) -> Tuple[List[ComboMetric], int]:
    groups = scan.combo_groups
    multi_counts = [g["row_count"] for g in groups.values()]
    threshold = min_rows if min_rows is not None else resolve_combo_min_rows(multi_counts)

    list_closing_by_token: Dict[str, int] = {}
    list_rows_by_token: Dict[str, int] = {}
    if list_metrics:
        for m in list_metrics:
            list_closing_by_token[m.token] = m.closing_count
            list_rows_by_token[m.token] = m.row_count

    combos: List[ComboMetric] = []
    for key, g in groups.items():
        if g["row_count"] < threshold:
            continue
        rc = g["row_count"]
        cc = g["closing_count"]
        combo_lists = g["lists"]
        combos.append(
            ComboMetric(
                lists=combo_lists,
                lists_key=key,
                row_count=rc,
                closing_count=cc,
                closing_rate=round(cc / rc, 6) if rc else 0.0,
                combo_group=_combo_group_for_lists(
                    combo_lists, list_closing_by_token, list_rows_by_token
                ),
            )
        )
    combos.sort(
        key=lambda c: (
            c.combo_group.lower(),
            -c.closing_count,
            -c.closing_rate,
            -c.row_count,
        )
    )
    return combos[:COMBO_EXPORT_CAP], threshold


def compute_combinations(
    cohort_df: pd.DataFrame,
    min_rows: Optional[int] = None,
    list_metrics: Optional[List[ListMetric]] = None,
) -> Tuple[List[ComboMetric], int]:
    return combinations_from_scan(
        scan_cohort(cohort_df), min_rows=min_rows, list_metrics=list_metrics
    )


def attribute_qualified_leads_to_lists(
    cohort_df: pd.DataFrame,
    sf_df: pd.DataFrame,
    start: date,
    end: date,
    cohort_keys: Optional[Dict[str, List[str]]] = None,
) -> Tuple[Dict[str, int], Dict[str, Any]]:
    compute_qualified_leads_metrics(sf_df, start, end)
    prepared, _, _ = validate_and_prepare(sf_df)
    window_start = pd.Timestamp(start)
    window_end = pd.Timestamp(end) + pd.Timedelta(days=1) - pd.Timedelta(microseconds=1)
    in_window = prepared["_create_date_parsed"].notna() & (
        prepared["_create_date_parsed"] >= window_start
    ) & (prepared["_create_date_parsed"] <= window_end)
    windowed = prepared.loc[in_window].copy()

    addr_cols = _discover_sf_addr_cols(sf_df)
    if not addr_cols.get("street"):
        return {}, {
            "matched_to_reisift": 0,
            "unmatched": int(len(windowed)),
            "by_list_token": {},
            "match_rate_pct": 0.0,
        }

    if cohort_keys is None:
        cohort_keys = scan_cohort(cohort_df).cohort_keys

    by_list: Dict[str, int] = {}
    matched = 0
    unmatched = 0
    for _, row in windowed.iterrows():
        key = _sf_address_key(row, addr_cols)
        tokens = cohort_keys.get(key)
        if not tokens:
            unmatched += 1
            continue
        matched += 1
        for t in tokens:
            by_list[t] = by_list.get(t, 0) + 1

    total_ql = matched + unmatched
    match_rate = round(100.0 * matched / total_ql, 2) if total_ql else 0.0
    return by_list, {
        "matched_to_reisift": matched,
        "unmatched": unmatched,
        "by_list_token": dict(sorted(by_list.items(), key=lambda x: (-x[1], x[0]))),
        "match_rate_pct": match_rate,
    }


def lifecycle_stats_for_api(lifecycle: Dict[str, Any]) -> Dict[str, Any]:
    """Map aggregate_lifecycle_stats keys to API/frontend SummaryStats field names."""
    if not lifecycle:
        return {}
    return {
        "Funnel_Acquired_Count": lifecycle.get("Funnel Acquired Count"),
        "Funnel_Researched_Count": lifecycle.get("Funnel Researched Count"),
        "Funnel_First_Contacted_Count": lifecycle.get("Funnel First Contacted Count"),
        "Funnel_Engaged_Count": lifecycle.get("Funnel Engaged Count"),
        "Funnel_Converted_Count": lifecycle.get("Funnel Converted Count"),
        "Funnel_Acquired_Rate_Pct": lifecycle.get("Funnel Acquired Rate Pct"),
        "Funnel_Researched_Rate_Pct": lifecycle.get("Funnel Researched Rate Pct"),
        "Funnel_First_Contact_Rate_Pct": lifecycle.get("Funnel First Contact Rate Pct"),
        "Funnel_Engaged_Rate_Pct": lifecycle.get("Funnel Engaged Rate Pct"),
        "Funnel_Converted_Rate_Pct": lifecycle.get("Funnel Converted Rate Pct"),
        "Engaged_To_Converted_Rate_Pct": lifecycle.get("Engaged To Converted Rate Pct"),
        "Top_Paths_Json": lifecycle.get("Top Paths Json"),
        "First_Touch_Breakdown_Json": lifecycle.get("First Touch Breakdown Json"),
    }


def result_from_metrics_dict(m: Dict[str, Any]) -> MonthlyConsolidatedResult:
    lists = [
        ListMetric(
            token=x["token"],
            row_count=x["row_count"],
            crm_lead_count=x.get("crm_lead_count", 0),
            qualified_lead_count=x.get("qualified_lead_count", 0),
            closing_count=x["closing_count"],
            closing_rate=x["closing_rate"],
            stacked_row_count=x.get("stacked_row_count", 0),
        )
        for x in m.get("lists", [])
    ]
    combos = [
        ComboMetric(
            lists=x["lists"],
            lists_key=x["lists_key"],
            row_count=x["row_count"],
            closing_count=x["closing_count"],
            closing_rate=x["closing_rate"],
            combo_group=x.get("combo_group", ""),
        )
        for x in m.get("combinations", [])
    ]
    cohort = m.get("cohort", {})
    period = m.get("period", {})
    inputs = m.get("inputs", {})
    return MonthlyConsolidatedResult(
        report_month=m.get("report_month", ""),
        cohort_scope=m.get("cohort_scope", "full_file"),
        period_start=period.get("start", ""),
        period_end=period.get("end", ""),
        reisift_rows_ingested=inputs.get("reisift_rows_ingested", 0),
        cohort_rows=cohort.get("total_rows", 0),
        crm_lead_rows=cohort.get("crm_lead_rows", 0),
        closing_rows=cohort.get("closing_rows", 0),
        stacked_rows=cohort.get("stacked_rows", 0),
        stacked_pct=cohort.get("stacked_pct", 0.0),
        lists=lists,
        combinations=combos,
        combo_min_rows=int(m.get("combo_min_rows", COMBO_MIN_ROWS_DEFAULT)),
        qualified_leads=m.get("qualified_leads", {}),
        list_attribution=m.get("list_attribution", {}),
        lifecycle=m.get("lifecycle", {}),
        lifecycle_stats=m.get("lifecycle_stats", {}),
        open_pipeline_lifecycle=m.get("open_pipeline_lifecycle", {}),
        tag_lead_source_counts=m.get("tag_lead_source_counts", []),
        warnings=m.get("warnings", []),
        methodology_note=m.get("methodology_note", ""),
    )


def _row_reference_end(row: pd.Series, created_col: Optional[str], default_end: pd.Timestamp) -> pd.Timestamp:
    if created_col and created_col in row.index:
        parsed = pd.to_datetime(row.get(created_col), errors="coerce")
        if pd.notna(parsed):
            return pd.Timestamp(parsed)
    return default_end


def derive_tag_lead_source_from_parsed(parsed: List[Dict[str, Any]]) -> str:
    """Tag-derived lead source from pre-parsed events."""
    if not parsed:
        return "NONE"

    def _sort_key(p: Dict[str, Any]) -> Tuple[int, str]:
        d = p.get("date")
        if d is None:
            return (0, "")
        try:
            return (1, pd.Timestamp(d).isoformat())
        except (ValueError, TypeError):
            return (0, str(d))

    ordered = sorted(parsed, key=_sort_key)
    first_contact: Optional[str] = None
    has_list = False
    for p in ordered:
        if p.get("type") == "list_purchase":
            has_list = True
        if p.get("type") == "contact" and first_contact is None:
            first_contact = str(p.get("channel") or p.get("label") or "CONTACT")
    if first_contact:
        return first_contact
    if has_list:
        return "LIST"
    return "NONE"


def derive_tag_lead_source(tags_str: object) -> str:
    """Tag-derived lead source: first 8020 channel, else LIST, else NONE."""
    if pd.isna(tags_str) or not str(tags_str).strip():
        return "NONE"
    return derive_tag_lead_source_from_parsed(_parse_tags_cached(tags_str))


def tag_lead_source_counts_to_api(counts: Dict[str, int]) -> List[Dict[str, Any]]:
    total = sum(counts.values()) or 1
    return [
        {
            "source": src,
            "count": cnt,
            "share_pct": round(100.0 * cnt / total, 1),
        }
        for src, cnt in sorted(counts.items(), key=lambda x: (-x[1], x[0]))
    ]


def build_tag_lead_source_counts(cohort_df: pd.DataFrame) -> List[Dict[str, Any]]:
    return tag_lead_source_counts_to_api(scan_cohort(cohort_df).tag_lead_source_counts)


def build_open_pipeline_lifecycle(
    cohort_df: pd.DataFrame,
    created_col: Optional[str],
    default_end: pd.Timestamp,
    open_pipeline_stages: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Stuck-at-stage summary for CRM-tagged cohort rows without a closing tag."""
    if open_pipeline_stages is None:
        scan = scan_cohort(cohort_df, created_col, default_end)
        open_pipeline_stages = scan.open_pipeline_stages
    return aggregate_stuck_at_stage(open_pipeline_stages)


def build_lifecycle_from_matches(matches: List[Dict[str, Any]]) -> Dict[str, Any]:
    if not matches:
        return {}
    results_df = analyze_contacts(matches)
    rows = results_df.to_dict(orient="records")
    return aggregate_lifecycle_stats(rows)


def build_lifecycle_from_cohort(cohort_df: pd.DataFrame) -> Dict[str, Any]:
    scan = scan_cohort(cohort_df)
    return build_lifecycle_from_matches(scan.closing_matches)


def _created_span_label(df: pd.DataFrame, created_col: Optional[str]) -> Tuple[str, str]:
    if not created_col or created_col not in df.columns:
        return "", ""
    parsed = _parse_created_series(df[created_col]).dropna()
    if parsed.empty:
        return "", ""
    return parsed.min().date().isoformat(), parsed.max().date().isoformat()


def analyze(
    reisift_path: str,
    qualified_leads_path: str,
    report_month: Optional[str] = None,
    on_progress: Optional[ProgressCallback] = None,
) -> MonthlyConsolidatedResult:
    warnings: List[str] = []
    month_text = (report_month or "").strip()

    def report(progress: int, message: str) -> None:
        if on_progress:
            on_progress(progress, message)

    if month_text:
        start, end = parse_report_month(month_text)
        scope = "calendar_month"
        label = month_text
    else:
        start, end = None, None
        scope = "full_file"
        label = "full_export"

    report(12, "Loading REISift export…")
    reisift_df = load_reisift_file(reisift_path)
    reisift_ingested = len(reisift_df)
    cohort_df, created_col, cohort_scope = prepare_reisift_cohort(reisift_df, start, end)
    cohort_rows = len(cohort_df)

    if cohort_rows == 0:
        if cohort_scope == "calendar_month":
            warnings.append(f"No REISift rows with Created in {month_text}.")
        else:
            warnings.append("REISift file has no data rows.")

    if cohort_scope == "full_file":
        period_start, period_end = _created_span_label(cohort_df, created_col)
    else:
        period_start = start.isoformat()  # type: ignore[union-attr]
        period_end = end.isoformat()  # type: ignore[union-attr]

    if period_end:
        try:
            default_ref = pd.Timestamp(period_end)
        except (ValueError, TypeError):
            default_ref = pd.Timestamp.now()
    else:
        default_ref = pd.Timestamp.now()

    report(18, "Scanning cohort (lists, tags, pipeline)…")
    scan = scan_cohort(cohort_df, created_col, default_ref, on_progress=on_progress)

    crm_lead_rows = scan.crm_lead_rows
    closing_rows = scan.closing_rows
    stacked_rows = scan.stacked_rows
    stacked_pct = round(100.0 * stacked_rows / cohort_rows, 2) if cohort_rows else 0.0

    report(58, "Loading qualified leads…")
    sf_df = load_qualified_leads_file(qualified_leads_path)
    from .qualified_leads import analyze_file as ql_analyze_file

    if cohort_scope == "full_file":
        ql_result = ql_analyze_file(qualified_leads_path, use_full_file_span=True)
        ql_start = date.fromisoformat(ql_result.date_window_start)
        ql_end = date.fromisoformat(ql_result.date_window_end)
    else:
        ql_start, ql_end = start, end  # type: ignore[assignment]
        ql_result = compute_qualified_leads_metrics(sf_df, ql_start, ql_end)

    report(68, "Attributing qualified leads to lists…")
    ql_by_list, list_attr = attribute_qualified_leads_to_lists(
        cohort_df, sf_df, ql_start, ql_end, cohort_keys=scan.cohort_keys
    )
    if list_attr.get("match_rate_pct", 100) < QL_MATCH_WARN_THRESHOLD * 100:
        warnings.append(
            f"Qualified lead address match rate is {list_attr.get('match_rate_pct')}%; "
            "list attribution may be understated."
        )

    report(76, "Ranking lists and combinations…")
    lists = list_metrics_from_scan(scan, ql_by_list)
    combinations, combo_min_rows = combinations_from_scan(scan, list_metrics=lists)

    report(82, "Analyzing closing lifecycle…")
    lifecycle_raw = (
        build_lifecycle_from_matches(scan.closing_matches) if closing_rows else {}
    )
    lifecycle_stats = lifecycle_stats_for_api(lifecycle_raw)

    report(86, "Finalizing open pipeline summary…")
    open_pipeline = build_open_pipeline_lifecycle(
        cohort_df, created_col, default_ref, open_pipeline_stages=scan.open_pipeline_stages
    )
    tag_lead_sources = tag_lead_source_counts_to_api(scan.tag_lead_source_counts)
    report(88, "Analysis complete")

    excluded_label = (
        "8020 Source List, PODIO (SOURCE), Appraiva (Source List), "
        "DNC / Dead Deals, Closings App, MLSLI, TBD, and Buyers (Investorbase)"
    )
    list_scope = (
        f"List metrics, stacking, and combinations use distress lists only — excluding {excluded_label}. "
        f"Combinations require ≥2 stackable lists and ≥{combo_min_rows} cohort rows "
        f"(dynamic median threshold, floor {COMBO_MIN_ROWS_FLOOR}). "
        "List credit applies to every remaining list on a matched REISift property. "
        "Closing rate = closings on list ÷ REISift rows carrying that list."
    )
    pipeline_scope = (
        "Open pipeline stuck-at-stage uses CRM-tagged rows without a closing tag "
        "(not every non-closing row in the export). "
    )
    if cohort_scope == "full_file":
        methodology = (
            "Cohort = all rows in the uploaded REISift export. "
            "CRM leads = rows with any (SF) tag. Closings = (CLOSED) 8020 tags (existing app logic). "
            "Qualified leads use the full Create Date span of the uploaded Salesforce file. "
            + pipeline_scope
            + list_scope
        )
    else:
        methodology = (
            "Cohort = REISift properties whose Created date falls in the selected calendar month. "
            "CRM leads = cohort rows with any (SF) tag. Closings = (CLOSED) 8020 tags (existing app logic). "
            "Qualified leads use the Salesforce export with the same Create Date window; "
            + pipeline_scope
            + list_scope
        )

    return MonthlyConsolidatedResult(
        report_month=label,
        cohort_scope=cohort_scope,
        period_start=period_start,
        period_end=period_end,
        reisift_rows_ingested=reisift_ingested,
        cohort_rows=cohort_rows,
        crm_lead_rows=crm_lead_rows,
        closing_rows=closing_rows,
        stacked_rows=stacked_rows,
        stacked_pct=stacked_pct,
        lists=lists,
        combinations=combinations,
        combo_min_rows=combo_min_rows,
        qualified_leads=ql_result.to_dict(),
        list_attribution=list_attr,
        lifecycle=lifecycle_raw,
        lifecycle_stats=lifecycle_stats,
        open_pipeline_lifecycle=open_pipeline,
        tag_lead_source_counts=tag_lead_sources,
        warnings=warnings,
        methodology_note=methodology,
    )


def build_export_workbook(result: MonthlyConsolidatedResult) -> bytes:
    try:
        import openpyxl  # noqa: F401
    except ImportError as exc:
        raise ValueError("XLSX export requires openpyxl") from exc

    buf = BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        summary = pd.DataFrame(
            [
                {"metric": "Cohort scope", "value": result.cohort_scope},
                {"metric": "Report label", "value": result.report_month},
                {"metric": "Period start (Created span or month)", "value": result.period_start},
                {"metric": "Period end", "value": result.period_end},
                {"metric": "REISift rows ingested", "value": result.reisift_rows_ingested},
                {"metric": "Cohort rows analyzed", "value": result.cohort_rows},
                {"metric": "CRM lead rows ((SF) tag)", "value": result.crm_lead_rows},
                {"metric": "Closing rows", "value": result.closing_rows},
                {"metric": "Stacked rows (multi-list)", "value": result.stacked_rows},
                {"metric": "Stacked %", "value": result.stacked_pct},
                {"metric": "Combo min rows (median threshold)", "value": result.combo_min_rows},
            ]
        )
        summary.to_excel(writer, sheet_name="Summary", index=False)

        pd.DataFrame([m.to_dict() for m in result.lists]).to_excel(
            writer, sheet_name="List Performance", index=False
        )
        pd.DataFrame([c.to_dict() for c in result.combinations]).to_excel(
            writer, sheet_name="List Combinations", index=False
        )

        ql = result.qualified_leads
        ch_rows = [
            {"channel": ch, "count": ql.get("channel_counts", {}).get(ch, 0),
             "share_pct": ql.get("channel_shares_pct", {}).get(ch, 0)}
            for ch in ("CC", "SMS", "DM", "Website", "PPC", "SEO", "Other")
        ]
        pd.DataFrame(ch_rows).to_excel(writer, sheet_name="Qualified Channels", index=False)

        lc = result.lifecycle
        if lc:
            funnel_rows = [
                {"metric": "Funnel Acquired Count", "value": lc.get("Funnel Acquired Count")},
                {"metric": "Funnel Researched Count", "value": lc.get("Funnel Researched Count")},
                {"metric": "Funnel First Contacted Count", "value": lc.get("Funnel First Contacted Count")},
                {"metric": "Funnel Engaged Count", "value": lc.get("Funnel Engaged Count")},
                {"metric": "Funnel Converted Count", "value": lc.get("Funnel Converted Count")},
            ]
            pd.DataFrame(funnel_rows).to_excel(writer, sheet_name="Lifecycle", index=False)
            import json as _json

            paths_raw = lc.get("Top Paths Json")
            if paths_raw:
                try:
                    paths = _json.loads(paths_raw) if isinstance(paths_raw, str) else paths_raw
                    pd.DataFrame(paths).to_excel(writer, sheet_name="Top Paths", index=False)
                except (_json.JSONDecodeError, TypeError):
                    pass
        else:
            pd.DataFrame([{"note": "No closings in cohort"}]).to_excel(
                writer, sheet_name="Lifecycle", index=False
            )

        if result.tag_lead_source_counts:
            pd.DataFrame(result.tag_lead_source_counts).to_excel(
                writer, sheet_name="Lead Source Tags", index=False
            )

        open_pipe = result.open_pipeline_lifecycle or {}
        stuck = open_pipe.get("stuck_at_stage") or []
        if stuck:
            pd.DataFrame(stuck).to_excel(writer, sheet_name="Open Pipeline", index=False)

    buf.seek(0)
    return buf.getvalue()
