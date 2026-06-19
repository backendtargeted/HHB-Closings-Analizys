"""
Gate 4 — Web Leads report.

Matches Salesforce Website qualified leads to REISift rows and measures how
often those inbound web leads were already on distress lists or touched via
8020 channels before the web-lead anchor date (REISift Created on vs SF Create Date).
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import date
from io import BytesIO
from typing import Any, Callable, Dict, List, Optional, Tuple

import pandas as pd

from .lifecycle import Event, build_events
from .marketing_mapper import find_column_name
from .monthly_consolidated import (
    CREATED_CANDIDATES,
    REISIFT_ADDR,
    SF_ADDR,
    _col_val,
    _discover_sf_addr_cols,
    _parse_tags_cached,
    _reisift_address_key,
    _sf_address_key,
    analysis_list_tokens,
    load_reisift_file,
    stackable_list_tokens,
)
from .qualified_leads import (
    CREATE_DATE_CANDIDATES,
    load_qualified_leads_file,
    rollup_channel,
    validate_and_prepare,
)

REPORT_TYPE = "web_leads"

ProgressCallback = Callable[[int, str], None]

WEB_CHANNELS: Tuple[str, ...] = ("Website",)

COMBO_CAP = 12
PATH_CAP = 10
LIST_CAP = 12
COMBO_MIN_ROWS = 3

AGE_BUCKETS: Tuple[Tuple[str, int, Optional[int]], ...] = (
    ("0-30 days", 0, 30),
    ("31-90 days", 31, 90),
    ("91-180 days", 91, 180),
    ("181-365 days", 181, 365),
    ("365+ days", 366, None),
)

WEB_LEADS_TAG_RE = re.compile(
    r"List\s+Purchased\s+Web\s+Leads\s+(\d{1,2})[-/](\d{4})",
    re.I,
)
LIST_PURCHASED_GENERIC_RE = re.compile(
    r"^List\s+Purchased\s+(?!8020|Web\s+Leads)(\d{1,2})[-/](\d{4})",
    re.I,
)


def _parse_event_date(iso: str) -> Optional[pd.Timestamp]:
    if not iso:
        return None
    parsed = pd.to_datetime(iso, errors="coerce")
    if pd.isna(parsed):
        return None
    return pd.Timestamp(parsed).normalize()


def _web_anchor_date(
    reisift_created: Optional[pd.Timestamp],
    ql_create: Optional[pd.Timestamp],
    web_lead_tag_date: Optional[pd.Timestamp] = None,
) -> Optional[pd.Timestamp]:
    candidates = [
        d
        for d in (web_lead_tag_date, reisift_created, ql_create)
        if d is not None and pd.notna(d)
    ]
    if not candidates:
        return None
    if web_lead_tag_date is not None and pd.notna(web_lead_tag_date):
        return pd.Timestamp(web_lead_tag_date).normalize()
    return min(candidates)


def row_is_web_lead(tags_str: object) -> bool:
    return "list purchased web leads" in str(tags_str or "").lower()


def parse_web_lead_tag_date(tags_str: object) -> Optional[pd.Timestamp]:
    """Earliest List Purchased Web Leads MM/YYYY from raw tag text."""
    dates: List[pd.Timestamp] = []
    for part in str(tags_str or "").split(","):
        tag = part.strip()
        match = WEB_LEADS_TAG_RE.search(tag)
        if not match:
            continue
        month, year = int(match.group(1)), int(match.group(2))
        try:
            dates.append(pd.Timestamp(year=year, month=month, day=1))
        except ValueError:
            continue
    if not dates:
        return None
    return min(dates)


def _supplement_list_dates_from_tags(tags_str: object) -> List[pd.Timestamp]:
    """Parse non-8020 List Purchased MM/YYYY tags not handled by parse_tags."""
    dates: List[pd.Timestamp] = []
    for part in str(tags_str or "").split(","):
        tag = part.strip()
        match = LIST_PURCHASED_GENERIC_RE.match(tag)
        if not match:
            continue
        month, year = int(match.group(1)), int(match.group(2))
        try:
            dates.append(pd.Timestamp(year=year, month=month, day=1))
        except ValueError:
            continue
    return dates


def events_before_anchor(events: List[Event], anchor: pd.Timestamp) -> List[Event]:
    """Events strictly before the web-lead anchor calendar day."""
    anchor_dt = anchor.to_pydatetime()
    out: List[Event] = []
    for e in events:
        dt = _parse_event_date(e.date_iso)
        if dt is not None and dt.to_pydatetime() < anchor_dt:
            out.append(e)
    return out


def compute_web_journey_path(events: List[Event], anchor: pd.Timestamp) -> str:
    """Compact path ending at WEB — list/skip/8020/SF tokens before anchor."""
    before = events_before_anchor(events, anchor)
    tokens: List[str] = []
    for e in before:
        if e.type == "list_purchase":
            t = "LIST"
        elif e.type == "skip_trace":
            t = "SKIP"
        elif e.type == "contact":
            t = e.label or "CONTACT"
        elif e.type in ("sf_updated", "sf_status"):
            slug = re.sub(r"\s+", "_", (e.label or "sf").lower())[:32]
            t = f"SF:{slug}"
        else:
            continue
        if not tokens or tokens[-1] != t:
            tokens.append(t)
    if not tokens or tokens[-1] != "WEB":
        tokens.append("WEB")
    return " -> ".join(tokens)


def _prior_history_from_events(
    events: List[Event],
    anchor: pd.Timestamp,
    tags_str: object = "",
) -> Tuple[bool, Optional[pd.Timestamp], List[str]]:
    """Return (had_prior, earliest_list_date, 8020_channels_before_anchor)."""
    before = events_before_anchor(events, anchor)
    list_dates: List[pd.Timestamp] = list(_supplement_list_dates_from_tags(tags_str))
    channels: List[str] = []
    for e in before:
        if e.type == "list_purchase":
            dt = _parse_event_date(e.date_iso)
            if dt is not None:
                list_dates.append(dt)
        elif e.type == "contact":
            ch = (e.label or "").strip().upper()
            if ch and ch not in channels:
                channels.append(ch)
    earliest_list = min(list_dates) if list_dates else None
    had_prior = earliest_list is not None or bool(channels)
    return had_prior, earliest_list, channels


def _age_bucket_label(days: Optional[int]) -> str:
    if days is None:
        return "Unknown"
    for label, lo, hi in AGE_BUCKETS:
        if hi is None and days >= lo:
            return label
        if hi is not None and lo <= days <= hi:
            return label
    return "Unknown"


def _build_reisift_index(df: pd.DataFrame) -> Dict[str, int]:
    """address_key -> first row index in REISift export."""
    index: Dict[str, int] = {}
    for i in range(len(df)):
        key = _reisift_address_key(df.iloc[i])
        if key and key != "|||" and key not in index:
            index[key] = i
    return index


@dataclass
class WebLeadRow:
    address: str
    address_key: str
    ql_create_date: str
    reisift_created_on: str
    anchor_date: str
    lists: List[str]
    combo_key: str
    had_prior_history: bool
    earliest_list_date: str
    days_list_to_web: Optional[int]
    prior_8020_channels: List[str]
    journey_path: str
    matched: bool

    def to_dict(self) -> Dict[str, Any]:
        return {
            "address": self.address,
            "address_key": self.address_key,
            "ql_create_date": self.ql_create_date,
            "reisift_created_on": self.reisift_created_on,
            "anchor_date": self.anchor_date,
            "lists": self.lists,
            "combo_key": self.combo_key,
            "had_prior_history": self.had_prior_history,
            "earliest_list_date": self.earliest_list_date,
            "days_list_to_web": self.days_list_to_web,
            "prior_8020_channels": self.prior_8020_channels,
            "journey_path": self.journey_path,
            "matched": self.matched,
        }


@dataclass
class WebLeadsResult:
    date_window_start: str
    date_window_end: str
    reisift_rows_ingested: int
    website_ql_total: int
    matched_count: int
    unmatched_count: int
    match_rate_pct: float
    prior_history_count: int
    prior_history_pct: float
    new_to_db_count: int
    new_to_db_pct: float
    top_lists: List[Dict[str, Any]]
    combinations: List[Dict[str, Any]]
    top_paths: List[Dict[str, Any]]
    age_buckets: List[Dict[str, Any]]
    rows: List[WebLeadRow]
    warnings: List[str] = field(default_factory=list)
    methodology_note: str = ""

    def to_api_dict(self) -> Dict[str, Any]:
        return {
            "report_type": REPORT_TYPE,
            "date_window_start": self.date_window_start,
            "date_window_end": self.date_window_end,
            "inputs": {
                "reisift_rows_ingested": self.reisift_rows_ingested,
                "website_ql_total": self.website_ql_total,
            },
            "match": {
                "matched": self.matched_count,
                "unmatched": self.unmatched_count,
                "match_rate_pct": self.match_rate_pct,
            },
            "prior_history": {
                "count": self.prior_history_count,
                "share_pct": self.prior_history_pct,
                "new_to_db_count": self.new_to_db_count,
                "new_to_db_pct": self.new_to_db_pct,
            },
            "top_lists": self.top_lists,
            "combinations": self.combinations,
            "top_paths": self.top_paths,
            "age_buckets": self.age_buckets,
            "rows": [r.to_dict() for r in self.rows],
            "warnings": self.warnings,
            "methodology_note": self.methodology_note,
        }


def result_from_metrics_dict(m: Dict[str, Any]) -> WebLeadsResult:
    """Rebuild export model from persisted metrics."""
    rows = [
        WebLeadRow(
            address=r.get("address", ""),
            address_key=r.get("address_key", ""),
            ql_create_date=r.get("ql_create_date", ""),
            reisift_created_on=r.get("reisift_created_on", ""),
            anchor_date=r.get("anchor_date", ""),
            lists=r.get("lists") or [],
            combo_key=r.get("combo_key", ""),
            had_prior_history=bool(r.get("had_prior_history")),
            earliest_list_date=r.get("earliest_list_date", ""),
            days_list_to_web=r.get("days_list_to_web"),
            prior_8020_channels=r.get("prior_8020_channels") or [],
            journey_path=r.get("journey_path", ""),
            matched=bool(r.get("matched", True)),
        )
        for r in m.get("rows") or []
    ]
    prior = m.get("prior_history") or {}
    match = m.get("match") or {}
    inputs = m.get("inputs") or {}
    return WebLeadsResult(
        date_window_start=m.get("date_window_start", ""),
        date_window_end=m.get("date_window_end", ""),
        reisift_rows_ingested=int(inputs.get("reisift_rows_ingested", 0)),
        website_ql_total=int(inputs.get("website_ql_total", 0)),
        matched_count=int(match.get("matched", 0)),
        unmatched_count=int(match.get("unmatched", 0)),
        match_rate_pct=float(match.get("match_rate_pct", 0)),
        prior_history_count=int(prior.get("count", 0)),
        prior_history_pct=float(prior.get("share_pct", 0)),
        new_to_db_count=int(prior.get("new_to_db_count", 0)),
        new_to_db_pct=float(prior.get("new_to_db_pct", 0)),
        top_lists=m.get("top_lists") or [],
        combinations=m.get("combinations") or [],
        top_paths=m.get("top_paths") or [],
        age_buckets=m.get("age_buckets") or [],
        rows=rows,
        warnings=m.get("warnings") or [],
        methodology_note=m.get("methodology_note", ""),
    )


def _discover_reisift_created_col(df: pd.DataFrame) -> Optional[str]:
    return find_column_name(df, CREATED_CANDIDATES)


def _format_address(row: pd.Series) -> str:
    street = _col_val(row, REISIFT_ADDR["street"])
    city = _col_val(row, REISIFT_ADDR["city"])
    return f"{street}, {city}".strip(", ") or street or "Unknown"


def _website_ql_window(
    sf_df: pd.DataFrame,
    use_full_file_span: bool,
    start: Optional[date],
    end: Optional[date],
) -> Tuple[pd.DataFrame, date, date]:
    prepared, lead_col, create_col = validate_and_prepare(sf_df)
    parsed_dates = prepared["_create_date_parsed"]
    valid = parsed_dates.dropna()
    if valid.empty:
        raise ValueError("Qualified leads file has no parseable Create Date values.")

    if use_full_file_span:
        window_start = valid.min().date()
        window_end = valid.max().date()
    else:
        if start is None or end is None:
            raise ValueError("start_date and end_date required when not using full file span.")
        window_start, window_end = start, end

    w_start = pd.Timestamp(window_start)
    w_end = pd.Timestamp(window_end) + pd.Timedelta(days=1) - pd.Timedelta(microseconds=1)
    in_window = parsed_dates.notna() & (parsed_dates >= w_start) & (parsed_dates <= w_end)
    windowed = prepared.loc[in_window].copy()
    windowed["_reporting_channel"] = windowed[lead_col].map(rollup_channel)
    website = windowed.loc[windowed["_reporting_channel"].isin(WEB_CHANNELS)].copy()
    return website, window_start, window_end


def _reisift_created_ts(
    row: pd.Series, created_col: Optional[str]
) -> Optional[pd.Timestamp]:
    if not created_col or created_col not in row.index:
        return None
    parsed = pd.to_datetime(row.get(created_col), errors="coerce")
    if pd.isna(parsed):
        return None
    return pd.Timestamp(parsed).normalize()


def _process_matched_reisift_row(
    rs_row: pd.Series,
    created_col: Optional[str],
    ql_create_ts: Optional[pd.Timestamp],
    address_key: str,
) -> Tuple[WebLeadRow, bool]:
    address = _format_address(rs_row)
    reisift_created_ts = _reisift_created_ts(rs_row, created_col)
    tags_val = rs_row.get("Tags", "")
    web_tag_date = parse_web_lead_tag_date(tags_val)

    anchor = _web_anchor_date(reisift_created_ts, ql_create_ts, web_tag_date)
    if anchor is None:
        anchor = pd.Timestamp.now().normalize()

    parsed = _parse_tags_cached(tags_val)
    events = build_events(parsed)
    had_prior, earliest_list, channels = _prior_history_from_events(
        events, anchor, tags_val
    )

    days_list: Optional[int] = None
    earliest_list_str = ""
    if earliest_list is not None:
        earliest_list_str = earliest_list.date().isoformat()
        days_list = (anchor - earliest_list).days

    lists = analysis_list_tokens(rs_row.get("Lists", ""))
    stackable = stackable_list_tokens(rs_row.get("Lists", ""))
    combo_key = " + ".join(sorted(stackable)) if len(stackable) >= 2 else ""
    journey = compute_web_journey_path(events, anchor)

    row = WebLeadRow(
        address=address,
        address_key=address_key,
        ql_create_date=ql_create_ts.date().isoformat() if ql_create_ts is not None else "",
        reisift_created_on=(
            reisift_created_ts.date().isoformat() if reisift_created_ts is not None else ""
        ),
        anchor_date=anchor.date().isoformat(),
        lists=lists,
        combo_key=combo_key,
        had_prior_history=had_prior,
        earliest_list_date=earliest_list_str,
        days_list_to_web=days_list,
        prior_8020_channels=channels,
        journey_path=journey,
        matched=True,
    )
    return row, had_prior


def _finalize_result(
    *,
    date_window_start: str,
    date_window_end: str,
    reisift_ingested: int,
    website_total: int,
    matched: int,
    unmatched: int,
    prior_count: int,
    rows: List[WebLeadRow],
    list_counter: Counter[str],
    combo_counter: Counter[str],
    path_counter: Counter[str],
    age_counter: Counter[str],
    warnings: List[str],
    methodology: str,
    on_progress: Optional[ProgressCallback] = None,
) -> WebLeadsResult:
    if on_progress:
        on_progress(85, "Aggregating compact summaries…")

    match_rate = round(100.0 * matched / website_total, 2) if website_total else 0.0
    prior_pct = round(100.0 * prior_count / matched, 1) if matched else 0.0
    new_count = matched - prior_count
    new_pct = round(100.0 * new_count / matched, 1) if matched else 0.0

    top_lists = [
        {
            "list": name,
            "count": cnt,
            "share_pct": round(100.0 * cnt / matched, 1) if matched else 0,
        }
        for name, cnt in list_counter.most_common(LIST_CAP)
    ]
    combinations = [
        {
            "lists_key": key,
            "lists": key.split(" + "),
            "row_count": cnt,
            "share_pct": round(100.0 * cnt / matched, 1) if matched else 0,
        }
        for key, cnt in combo_counter.most_common(COMBO_CAP)
        if cnt >= COMBO_MIN_ROWS
    ]
    top_paths = [
        {
            "path": path,
            "count": cnt,
            "share_pct": round(100.0 * cnt / matched, 1) if matched else 0,
        }
        for path, cnt in path_counter.most_common(PATH_CAP)
    ]
    age_buckets = [
        {
            "bucket": label,
            "count": age_counter.get(label, 0),
            "share_pct": round(100.0 * age_counter.get(label, 0) / prior_count, 1)
            if prior_count
            else 0,
        }
        for label, _, _ in AGE_BUCKETS
    ]
    if age_counter.get("Unknown", 0):
        age_buckets.append(
            {
                "bucket": "Unknown",
                "count": age_counter["Unknown"],
                "share_pct": round(100.0 * age_counter["Unknown"] / prior_count, 1)
                if prior_count
                else 0,
            }
        )

    if on_progress:
        on_progress(95, "Analysis complete")

    return WebLeadsResult(
        date_window_start=date_window_start,
        date_window_end=date_window_end,
        reisift_rows_ingested=reisift_ingested,
        website_ql_total=website_total,
        matched_count=matched,
        unmatched_count=unmatched,
        match_rate_pct=match_rate,
        prior_history_count=prior_count,
        prior_history_pct=prior_pct,
        new_to_db_count=new_count,
        new_to_db_pct=new_pct,
        top_lists=top_lists,
        combinations=combinations,
        top_paths=top_paths,
        age_buckets=age_buckets,
        rows=rows,
        warnings=warnings,
        methodology_note=methodology,
    )


def analyze(
    reisift_path: str,
    qualified_leads_path: Optional[str] = None,
    *,
    use_full_file_span: bool = True,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    on_progress: Optional[ProgressCallback] = None,
) -> WebLeadsResult:
    if qualified_leads_path:
        return _analyze_with_qualified_leads(
            reisift_path,
            qualified_leads_path,
            use_full_file_span=use_full_file_span,
            start_date=start_date,
            end_date=end_date,
            on_progress=on_progress,
        )
    return _analyze_reisift_only(reisift_path, on_progress=on_progress)


def _analyze_reisift_only(
    reisift_path: str,
    on_progress: Optional[ProgressCallback] = None,
) -> WebLeadsResult:
    warnings: List[str] = []

    def report(progress: int, message: str) -> None:
        if on_progress:
            on_progress(progress, message)

    report(10, "Loading REISift export…")
    reisift_df = load_reisift_file(reisift_path)
    reisift_ingested = len(reisift_df)
    created_col = _discover_reisift_created_col(reisift_df)
    if not created_col:
        warnings.append(
            "REISift export has no Created column; web-lead anchor uses List Purchased Web Leads tag only."
        )

    if "Tags" not in reisift_df.columns:
        raise ValueError("REISift export is missing required Tags column.")

    report(35, "Identifying web leads from REISift tags…")
    cohort_mask = reisift_df["Tags"].map(row_is_web_lead)
    cohort = reisift_df.loc[cohort_mask].copy()
    website_total = len(cohort)
    if website_total == 0:
        raise ValueError(
            "No rows with a List Purchased Web Leads tag found. "
            "Export web leads from REISift or upload Salesforce Website qualified leads."
        )

    created_dates = []
    web_tag_dates = []
    for _, row in cohort.iterrows():
        ts = _reisift_created_ts(row, created_col)
        if ts is not None:
            created_dates.append(ts)
        wt = parse_web_lead_tag_date(row.get("Tags", ""))
        if wt is not None:
            web_tag_dates.append(wt)
    span_candidates = created_dates + web_tag_dates
    window_start = min(span_candidates).date().isoformat() if span_candidates else ""
    window_end = max(span_candidates).date().isoformat() if span_candidates else ""

    rows: List[WebLeadRow] = []
    list_counter: Counter[str] = Counter()
    combo_counter: Counter[str] = Counter()
    path_counter: Counter[str] = Counter()
    age_counter: Counter[str] = Counter()
    prior_count = 0

    report(55, f"Analyzing {website_total:,} web lead rows…")
    for i, (_, rs_row) in enumerate(cohort.iterrows()):
        key = _reisift_address_key(rs_row)
        web_row, had_prior = _process_matched_reisift_row(
            rs_row, created_col, None, key
        )
        rows.append(web_row)
        if had_prior:
            prior_count += 1
            if web_row.days_list_to_web is not None:
                age_counter[_age_bucket_label(web_row.days_list_to_web)] += 1
            else:
                age_counter["Unknown"] += 1
        for lst in web_row.lists:
            list_counter[lst] += 1
        if web_row.combo_key:
            combo_counter[web_row.combo_key] += 1
        path_counter[web_row.journey_path] += 1
        if on_progress and i > 0 and i % 50 == 0:
            report(55 + int(25 * i / max(website_total, 1)), f"Row {i:,} / {website_total:,}…")

    methodology = (
        "Cohort = REISift rows carrying a List Purchased Web Leads tag. "
        "Anchor date = Web Leads list-purchase month (fallback: REISift Created on). "
        "Prior history = any distress list purchase or (8020) CC/SMS/DM strictly before anchor. "
        f"List combinations require ≥{COMBO_MIN_ROWS} web leads and cap at {COMBO_CAP}. "
        f"Journey paths cap at {PATH_CAP} routes ending in WEB."
    )

    return _finalize_result(
        date_window_start=window_start,
        date_window_end=window_end,
        reisift_ingested=reisift_ingested,
        website_total=website_total,
        matched=website_total,
        unmatched=0,
        prior_count=prior_count,
        rows=rows,
        list_counter=list_counter,
        combo_counter=combo_counter,
        path_counter=path_counter,
        age_counter=age_counter,
        warnings=warnings,
        methodology=methodology,
        on_progress=on_progress,
    )


def _analyze_with_qualified_leads(
    reisift_path: str,
    qualified_leads_path: str,
    *,
    use_full_file_span: bool = True,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    on_progress: Optional[ProgressCallback] = None,
) -> WebLeadsResult:
    warnings: List[str] = []

    def report(progress: int, message: str) -> None:
        if on_progress:
            on_progress(progress, message)

    report(10, "Loading REISift export…")
    reisift_df = load_reisift_file(reisift_path)
    reisift_ingested = len(reisift_df)
    created_col = _discover_reisift_created_col(reisift_df)
    if not created_col:
        warnings.append(
            "REISift export has no Created / Created on column; anchor dates use Salesforce Create Date only."
        )

    report(25, "Indexing REISift addresses…")
    reisift_index = _build_reisift_index(reisift_df)

    report(35, "Loading Website qualified leads…")
    sf_df = load_qualified_leads_file(qualified_leads_path)
    website_ql, window_start, window_end = _website_ql_window(
        sf_df, use_full_file_span, start_date, end_date
    )
    website_total = len(website_ql)
    if website_total == 0:
        warnings.append(
            f"No Website-channel qualified leads with Create Date in {window_start} – {window_end}."
        )

    addr_cols = _discover_sf_addr_cols(sf_df)
    if not addr_cols.get("street"):
        raise ValueError("Qualified leads file is missing a usable street/address column.")

    report(50, "Matching web leads to REISift…")
    rows: List[WebLeadRow] = []
    list_counter: Counter[str] = Counter()
    combo_counter: Counter[str] = Counter()
    path_counter: Counter[str] = Counter()
    age_counter: Counter[str] = Counter()
    matched = 0
    unmatched = 0
    prior_count = 0
    create_col = find_column_name(sf_df, CREATE_DATE_CANDIDATES) or ""

    for _, ql_row in website_ql.iterrows():
        key = _sf_address_key(ql_row, addr_cols)
        ql_create = pd.to_datetime(ql_row.get(create_col, ""), errors="coerce")
        ql_create_ts = (
            pd.Timestamp(ql_create).normalize() if pd.notna(ql_create) else None
        )

        idx = reisift_index.get(key)
        if idx is None:
            unmatched += 1
            rows.append(
                WebLeadRow(
                    address=str(ql_row.get(addr_cols["street"], "") or "").strip(),
                    address_key=key,
                    ql_create_date=ql_create_ts.date().isoformat() if ql_create_ts is not None else "",
                    reisift_created_on="",
                    anchor_date=ql_create_ts.date().isoformat() if ql_create_ts is not None else "",
                    lists=[],
                    combo_key="",
                    had_prior_history=False,
                    earliest_list_date="",
                    days_list_to_web=None,
                    prior_8020_channels=[],
                    journey_path="WEB",
                    matched=False,
                )
            )
            continue

        matched += 1
        web_row, had_prior = _process_matched_reisift_row(
            reisift_df.iloc[idx],
            created_col,
            ql_create_ts,
            key,
        )
        rows.append(web_row)
        if had_prior:
            prior_count += 1
            if web_row.days_list_to_web is not None:
                age_counter[_age_bucket_label(web_row.days_list_to_web)] += 1
            elif had_prior:
                age_counter["Unknown"] += 1
        for lst in web_row.lists:
            list_counter[lst] += 1
        if web_row.combo_key:
            combo_counter[web_row.combo_key] += 1
        path_counter[web_row.journey_path] += 1

    if matched + unmatched and round(100.0 * matched / (matched + unmatched), 2) < 50:
        warnings.append(
            f"Only {round(100.0 * matched / (matched + unmatched), 2)}% of Website leads "
            "matched REISift by address; check exports align."
        )

    methodology = (
        "Cohort = Salesforce Total Qualified Leads with Lead Source mapped to Website, "
        f"Create Date in {window_start} – {window_end}. "
        "Each lead is matched to REISift by normalized property address. "
        "Anchor date = Web Leads list tag month when present, else earlier of REISift Created on "
        "and SF Create Date. "
        "Prior history = distress list purchase or (8020) CC/SMS/DM strictly before anchor. "
        f"List combinations require ≥{COMBO_MIN_ROWS} matched web leads and cap at {COMBO_CAP}. "
        f"Journey paths cap at {PATH_CAP} distinct routes ending in WEB."
    )

    return _finalize_result(
        date_window_start=window_start.isoformat(),
        date_window_end=window_end.isoformat(),
        reisift_ingested=reisift_ingested,
        website_total=website_total,
        matched=matched,
        unmatched=unmatched,
        prior_count=prior_count,
        rows=rows,
        list_counter=list_counter,
        combo_counter=combo_counter,
        path_counter=path_counter,
        age_counter=age_counter,
        warnings=warnings,
        methodology=methodology,
        on_progress=on_progress,
    )


def build_export_workbook(result: WebLeadsResult) -> bytes:
    try:
        import openpyxl  # noqa: F401
    except ImportError as exc:
        raise ValueError("XLSX export requires openpyxl") from exc

    buf = BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        summary_rows = [
            {"metric": "Date window start", "value": result.date_window_start},
            {"metric": "Date window end", "value": result.date_window_end},
            {"metric": "REISift rows ingested", "value": result.reisift_rows_ingested},
            {"metric": "Website QL total", "value": result.website_ql_total},
            {"metric": "Matched to REISift", "value": result.matched_count},
            {"metric": "Unmatched", "value": result.unmatched_count},
            {"metric": "Match rate %", "value": result.match_rate_pct},
            {"metric": "Prior history count", "value": result.prior_history_count},
            {"metric": "Prior history %", "value": result.prior_history_pct},
            {"metric": "New to database count", "value": result.new_to_db_count},
            {"metric": "New to database %", "value": result.new_to_db_pct},
        ]
        pd.DataFrame(summary_rows).to_excel(writer, sheet_name="Summary", index=False)
        pd.DataFrame([r.to_dict() for r in result.rows]).to_excel(
            writer, sheet_name="Web Lead Rows", index=False
        )
        if result.top_lists:
            pd.DataFrame(result.top_lists).to_excel(writer, sheet_name="Top Lists", index=False)
        if result.combinations:
            pd.DataFrame(result.combinations).to_excel(
                writer, sheet_name="List Combinations", index=False
            )
        if result.top_paths:
            pd.DataFrame(result.top_paths).to_excel(
                writer, sheet_name="Journey Paths", index=False
            )
        if result.age_buckets:
            pd.DataFrame(result.age_buckets).to_excel(
                writer, sheet_name="List Age Buckets", index=False
            )
    buf.seek(0)
    return buf.getvalue()
