"""
Consolidated list-performance report: full REISift export + SF qualified leads.

Default cohort is every row in the uploaded REISift file (no month filter).
Optional report_month (YYYY-MM) remains for API callers that need a Created-date window.
"""

from __future__ import annotations

import calendar
import re
from dataclasses import dataclass, field
from datetime import date
from io import BytesIO
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

from .analysis import (
    analyze_contacts,
    parse_tags,
    _dedupe_parsed_tag_events,
)
from .lifecycle import aggregate_lifecycle_stats
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
QL_MATCH_WARN_THRESHOLD = 0.5

# REISift source/import lists — excluded from list ranking, combinations, and QL attribution.
EXCLUDED_LIST_TOKENS: frozenset[str] = frozenset(
    {
        "8020 source list",
        "podio (source)",
    }
)


def _normalize_list_token(token: str) -> str:
    return " ".join(str(token or "").strip().lower().split())


def is_excluded_list_token(token: str) -> bool:
    return _normalize_list_token(token) in EXCLUDED_LIST_TOKENS


def analysis_list_tokens(lists_str: object) -> List[str]:
    """Distress lists used for ranking; omits source/import lists."""
    return [t for t in split_list_tokens(lists_str) if not is_excluded_list_token(t)]


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


def row_has_closing_tag(tags_str: object) -> bool:
    parsed = _dedupe_parsed_tag_events(parse_tags(tags_str))
    return any(p.get("type") == "closing" for p in parsed)


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

    def to_dict(self) -> Dict[str, Any]:
        return {
            "lists": self.lists,
            "lists_key": self.lists_key,
            "row_count": self.row_count,
            "closing_count": self.closing_count,
            "closing_rate": self.closing_rate,
        }


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
            "qualified_leads": self.qualified_leads,
            "list_attribution": self.list_attribution,
            "lifecycle": self.lifecycle,
            "lifecycle_stats": self.lifecycle_stats,
            "warnings": self.warnings,
            "methodology_note": self.methodology_note,
        }


def compute_list_metrics(cohort_df: pd.DataFrame, ql_by_list: Dict[str, int]) -> List[ListMetric]:
    token_rows: Dict[str, int] = {}
    token_crm: Dict[str, int] = {}
    token_close: Dict[str, int] = {}
    token_stacked: Dict[str, int] = {}

    for _, row in cohort_df.iterrows():
        tokens = analysis_list_tokens(row.get("Lists"))
        if not tokens:
            continue
        is_stacked = len(tokens) > 1
        has_sf = row_has_sf_tag(row.get("Tags"))
        has_close = row_has_closing_tag(row.get("Tags"))
        for t in tokens:
            token_rows[t] = token_rows.get(t, 0) + 1
            if has_sf:
                token_crm[t] = token_crm.get(t, 0) + 1
            if has_close:
                token_close[t] = token_close.get(t, 0) + 1
            if is_stacked:
                token_stacked[t] = token_stacked.get(t, 0) + 1

    all_tokens = sorted(token_rows.keys(), key=lambda x: (-token_close.get(x, 0), -token_rows[x], x))
    metrics: List[ListMetric] = []
    for t in all_tokens:
        rc = token_rows[t]
        cc = token_close.get(t, 0)
        metrics.append(
            ListMetric(
                token=t,
                row_count=rc,
                crm_lead_count=token_crm.get(t, 0),
                qualified_lead_count=ql_by_list.get(t, 0),
                closing_count=cc,
                closing_rate=round(cc / rc, 6) if rc else 0.0,
                stacked_row_count=token_stacked.get(t, 0),
            )
        )
    return metrics


def compute_combinations(
    cohort_df: pd.DataFrame, min_rows: int = 10
) -> List[ComboMetric]:
    groups: Dict[str, Dict[str, Any]] = {}
    for _, row in cohort_df.iterrows():
        tokens = analysis_list_tokens(row.get("Lists"))
        if not tokens:
            continue
        key_tuple = tuple(sorted(tokens))
        key = " + ".join(key_tuple)
        if key not in groups:
            groups[key] = {"lists": list(key_tuple), "row_count": 0, "closing_count": 0}
        groups[key]["row_count"] += 1
        if row_has_closing_tag(row.get("Tags")):
            groups[key]["closing_count"] += 1

    combos: List[ComboMetric] = []
    for key, g in groups.items():
        if g["row_count"] < min_rows:
            continue
        rc = g["row_count"]
        cc = g["closing_count"]
        combos.append(
            ComboMetric(
                lists=g["lists"],
                lists_key=key,
                row_count=rc,
                closing_count=cc,
                closing_rate=round(cc / rc, 6) if rc else 0.0,
            )
        )
    combos.sort(key=lambda c: (-c.closing_count, -c.closing_rate, -c.row_count))
    return combos[:COMBO_EXPORT_CAP]


def attribute_qualified_leads_to_lists(
    cohort_df: pd.DataFrame, sf_df: pd.DataFrame, start: date, end: date
) -> Tuple[Dict[str, int], Dict[str, Any]]:
    ql_metrics = compute_qualified_leads_metrics(sf_df, start, end)
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

    cohort_keys: Dict[str, List[str]] = {}
    for _, row in cohort_df.iterrows():
        key = _reisift_address_key(row)
        if not key or key == "|||":
            continue
        tokens = analysis_list_tokens(row.get("Lists"))
        if not tokens:
            continue
        cohort_keys.setdefault(key, [])
        for t in tokens:
            if t not in cohort_keys[key]:
                cohort_keys[key].append(t)

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
        qualified_leads=m.get("qualified_leads", {}),
        list_attribution=m.get("list_attribution", {}),
        lifecycle=m.get("lifecycle", {}),
        warnings=m.get("warnings", []),
        methodology_note=m.get("methodology_note", ""),
    )


def build_lifecycle_from_cohort(cohort_df: pd.DataFrame) -> Dict[str, Any]:
    closing_rows = cohort_df[cohort_df["Tags"].apply(row_has_closing_tag)]
    if closing_rows.empty:
        return {}

    matches: List[Dict[str, Any]] = []
    for idx, row in closing_rows.iterrows():
        street = _col_val(row, REISIFT_ADDR["street"])
        city = _col_val(row, REISIFT_ADDR["city"])
        addr = f"{street} {city}".strip() or street or "Unknown"
        parsed = _dedupe_parsed_tag_events(parse_tags(row.get("Tags", "")))
        close_date = None
        for p in parsed:
            if p.get("type") == "closing":
                close_date = p.get("date")
                break
        matches.append(
            {
                "deal_index": int(idx),
                "csv_index": int(idx),
                "closed_date": close_date or "",
                "address": addr,
                "lead_source": "Contact History Tags",
                "csv_record": row.to_dict(),
                "workbook_close": None,
                "deal_meta": None,
            }
        )

    results_df = analyze_contacts(matches)
    rows = results_df.to_dict(orient="records")
    return aggregate_lifecycle_stats(rows)


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
) -> MonthlyConsolidatedResult:
    warnings: List[str] = []
    month_text = (report_month or "").strip()

    if month_text:
        start, end = parse_report_month(month_text)
        scope = "calendar_month"
        label = month_text
    else:
        start, end = None, None
        scope = "full_file"
        label = "full_export"

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

    crm_lead_rows = int(cohort_df["Tags"].apply(row_has_sf_tag).sum()) if cohort_rows else 0
    closing_rows = int(cohort_df["Tags"].apply(row_has_closing_tag).sum()) if cohort_rows else 0

    stacked_rows = 0
    if cohort_rows:
        stacked_rows = int(
            cohort_df["Lists"].apply(lambda x: len(analysis_list_tokens(x)) > 1).sum()
        )
    stacked_pct = round(100.0 * stacked_rows / cohort_rows, 2) if cohort_rows else 0.0

    sf_df = load_qualified_leads_file(qualified_leads_path)
    from .qualified_leads import analyze_file as ql_analyze_file

    if cohort_scope == "full_file":
        ql_result = ql_analyze_file(qualified_leads_path, use_full_file_span=True)
        ql_start = date.fromisoformat(ql_result.date_window_start)
        ql_end = date.fromisoformat(ql_result.date_window_end)
    else:
        ql_start, ql_end = start, end  # type: ignore[assignment]
        ql_result = compute_qualified_leads_metrics(sf_df, ql_start, ql_end)

    ql_by_list, list_attr = attribute_qualified_leads_to_lists(
        cohort_df, sf_df, ql_start, ql_end
    )
    if list_attr.get("match_rate_pct", 100) < QL_MATCH_WARN_THRESHOLD * 100:
        warnings.append(
            f"Qualified lead address match rate is {list_attr.get('match_rate_pct')}%; "
            "list attribution may be understated."
        )

    lists = compute_list_metrics(cohort_df, ql_by_list)
    combinations = compute_combinations(cohort_df, min_rows=10)
    lifecycle_raw = build_lifecycle_from_cohort(cohort_df) if closing_rows else {}
    lifecycle_stats = lifecycle_stats_for_api(lifecycle_raw)

    excluded_label = "8020 Source List and PODIO (SOURCE)"
    list_scope = (
        f"List metrics exclude {excluded_label} (source/import lists). "
        "List credit applies to every remaining list on a matched REISift property. "
        "Closing rate = closings on list ÷ REISift rows carrying that list."
    )
    if cohort_scope == "full_file":
        methodology = (
            "Cohort = all rows in the uploaded REISift export. "
            "CRM leads = rows with any (SF) tag. Closings = (CLOSED) 8020 tags (existing app logic). "
            "Qualified leads use the full Create Date span of the uploaded Salesforce file. "
            + list_scope
        )
    else:
        methodology = (
            "Cohort = REISift properties whose Created date falls in the selected calendar month. "
            "CRM leads = cohort rows with any (SF) tag. Closings = (CLOSED) 8020 tags (existing app logic). "
            "Qualified leads use the Salesforce export with the same Create Date window; "
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
        qualified_leads=ql_result.to_dict(),
        list_attribution=list_attr,
        lifecycle=lifecycle_raw,
        lifecycle_stats=lifecycle_stats,
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

    buf.seek(0)
    return buf.getvalue()
