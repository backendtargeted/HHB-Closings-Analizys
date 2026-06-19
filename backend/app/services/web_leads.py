"""
Gate 4 — Web Leads (and similar cohort tracks).

Upload a manually filtered cohort file (web leads, court alerts, etc.) and match
each row to the full REISift export for lists, tag history, journey paths, and
combinations. Optional closings workbook for close-date enrichment.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from io import BytesIO
from typing import Any, Callable, Dict, List, Optional, Tuple

import pandas as pd

from .lifecycle import Event, build_events
from .closing_resolution import filter_closings_by_stage
from .marketing_mapper import find_column_name
from .marketing_ramp import (
    CLOSINGS_ADDR,
    DATE_CLOSED_CANDIDATES,
    STAGE_CANDIDATES,
    load_closings_file,
    _address_key_from_row,
    _discover_addr_cols,
)
from .monthly_consolidated import (
    CREATED_CANDIDATES,
    REISIFT_ADDR,
    _col_val,
    _parse_tags_cached,
    _reisift_address_key,
    analysis_list_tokens,
    load_reisift_file,
    stackable_list_tokens,
)

REPORT_TYPE = "web_leads"

ProgressCallback = Callable[[int, str], None]

COHORT_SOURCE_DEFAULT = "web_leads"

COHORT_SOURCE_LABELS: Dict[str, str] = {
    "web_leads": "Web Leads track",
    "court_alerts": "Court alerts track",
    "long_island_profiles": "Long Island profiles track",
}

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
HAS_8020_TAG_RE = re.compile(r"\b8020\b", re.I)


def _parse_event_date(iso: str) -> Optional[pd.Timestamp]:
    if not iso:
        return None
    parsed = pd.to_datetime(iso, errors="coerce")
    if pd.isna(parsed):
        return None
    return pd.Timestamp(parsed).normalize()


def _web_anchor_date(
    cohort_created: Optional[pd.Timestamp],
    reisift_created: Optional[pd.Timestamp],
    web_lead_tag_date: Optional[pd.Timestamp] = None,
) -> Optional[pd.Timestamp]:
    """Anchor = when the lead entered this cohort track (web tag month preferred)."""
    if web_lead_tag_date is not None and pd.notna(web_lead_tag_date):
        return pd.Timestamp(web_lead_tag_date).normalize()
    candidates = [
        d
        for d in (cohort_created, reisift_created)
        if d is not None and pd.notna(d)
    ]
    if not candidates:
        return None
    return min(candidates)


def row_is_web_lead(tags_str: object) -> bool:
    return "list purchased web leads" in str(tags_str or "").lower()


def tags_have_8020(tags_str: object) -> bool:
    """True when REISift tags include any 8020 list-purchase or (8020) contact tag."""
    return bool(HAS_8020_TAG_RE.search(str(tags_str or "")))


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


def _compact_journey_display(path: str) -> str:
    """Shorten noisy paths for summary tables (collapse repeated LIST tokens)."""
    parts = [p.strip() for p in path.split(" -> ")]
    compact: List[str] = []
    for p in parts:
        if p == "LIST" and compact and compact[-1] == "LIST":
            continue
        compact.append(p)
    if len(compact) > 8:
        head = compact[:3]
        tail = compact[-4:]
        compact = head + ["…"] + tail
    return " -> ".join(compact)


def _build_closings_index(closings_path: str) -> Dict[str, Dict[str, Any]]:
    """address_key -> latest stage-filtered closing row."""
    df = load_closings_file(closings_path)
    filtered = filter_closings_by_stage(df)
    date_col = find_column_name(filtered, DATE_CLOSED_CANDIDATES)
    addr_cols = _discover_addr_cols(filtered, CLOSINGS_ADDR)
    if not addr_cols.get("street"):
        return {}

    stage_col = find_column_name(filtered, STAGE_CANDIDATES)
    index: Dict[str, Dict[str, Any]] = {}
    for _, row in filtered.iterrows():
        key = _address_key_from_row(row, addr_cols)
        if not key or key == "|||":
            continue
        closed_raw = row.get(date_col, "") if date_col else ""
        closed = pd.to_datetime(closed_raw, errors="coerce")
        closed_ymd = ""
        if pd.notna(closed):
            closed_ymd = pd.Timestamp(closed).date().isoformat()
        stage_val = str(row.get(stage_col, "") or "").strip() if stage_col else ""
        entry = {
            "date_closed": closed_ymd,
            "stage": stage_val,
            "sort_closed": pd.Timestamp(closed) if pd.notna(closed) else pd.Timestamp.min,
        }
        existing = index.get(key)
        if existing is None or entry["sort_closed"] > existing["sort_closed"]:
            index[key] = entry
    return index


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
    cohort_track_date: str
    reisift_created_on: str
    anchor_date: str
    lists: List[str]
    combo_key: str
    had_prior_history: bool
    earliest_list_date: str
    days_list_to_web: Optional[int]
    prior_8020_channels: List[str]
    has_8020_tag: bool
    journey_path: str
    journey_path_compact: str
    matched: bool
    closings_matched: bool = False
    closings_date_closed: str = ""
    closings_stage: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "address": self.address,
            "address_key": self.address_key,
            "cohort_track_date": self.cohort_track_date,
            "ql_create_date": self.cohort_track_date,  # legacy alias
            "reisift_created_on": self.reisift_created_on,
            "anchor_date": self.anchor_date,
            "lists": self.lists,
            "combo_key": self.combo_key,
            "had_prior_history": self.had_prior_history,
            "earliest_list_date": self.earliest_list_date,
            "days_list_to_web": self.days_list_to_web,
            "prior_8020_channels": self.prior_8020_channels,
            "has_8020_tag": self.has_8020_tag,
            "journey_path": self.journey_path,
            "journey_path_compact": self.journey_path_compact,
            "matched": self.matched,
            "closings_matched": self.closings_matched,
            "closings_date_closed": self.closings_date_closed,
            "closings_stage": self.closings_stage,
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
    cohort_source: str = COHORT_SOURCE_DEFAULT

    def to_api_dict(self) -> Dict[str, Any]:
        return {
            "report_type": REPORT_TYPE,
            "date_window_start": self.date_window_start,
            "date_window_end": self.date_window_end,
            "inputs": {
                "cohort_rows": self.website_ql_total,
                "cohort_source": self.cohort_source,
                "reisift_reference_rows": self.reisift_rows_ingested,
                "website_ql_total": self.website_ql_total,
                "reisift_rows_ingested": self.reisift_rows_ingested,
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
            "cohort_source": self.cohort_source,
        }


def result_from_metrics_dict(m: Dict[str, Any]) -> WebLeadsResult:
    """Rebuild export model from persisted metrics."""
    rows = [
        WebLeadRow(
            address=r.get("address", ""),
            address_key=r.get("address_key", ""),
            cohort_track_date=r.get("cohort_track_date") or r.get("ql_create_date", ""),
            reisift_created_on=r.get("reisift_created_on", ""),
            anchor_date=r.get("anchor_date", ""),
            lists=r.get("lists") or [],
            combo_key=r.get("combo_key", ""),
            had_prior_history=bool(r.get("had_prior_history")),
            earliest_list_date=r.get("earliest_list_date", ""),
            days_list_to_web=r.get("days_list_to_web"),
            prior_8020_channels=r.get("prior_8020_channels") or [],
            has_8020_tag=bool(r.get("has_8020_tag")),
            journey_path=r.get("journey_path", ""),
            journey_path_compact=r.get("journey_path_compact") or r.get("journey_path", ""),
            matched=bool(r.get("matched", True)),
            closings_matched=bool(r.get("closings_matched")),
            closings_date_closed=r.get("closings_date_closed", ""),
            closings_stage=r.get("closings_stage", ""),
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
        cohort_source=m.get("cohort_source", COHORT_SOURCE_DEFAULT),
    )


def _discover_reisift_created_col(df: pd.DataFrame) -> Optional[str]:
    return find_column_name(df, CREATED_CANDIDATES)


def _format_address(row: pd.Series) -> str:
    street = _col_val(row, REISIFT_ADDR["street"])
    city = _col_val(row, REISIFT_ADDR["city"])
    return f"{street}, {city}".strip(", ") or street or "Unknown"


def _reisift_created_ts(
    row: pd.Series, created_col: Optional[str]
) -> Optional[pd.Timestamp]:
    if not created_col or created_col not in row.index:
        return None
    parsed = pd.to_datetime(row.get(created_col), errors="coerce")
    if pd.isna(parsed):
        return None
    return pd.Timestamp(parsed).normalize()


def _process_cohort_reisift_match(
    cohort_row: pd.Series,
    reisift_row: pd.Series,
    cohort_created_col: Optional[str],
    reisift_created_col: Optional[str],
    address_key: str,
    closings_entry: Optional[Dict[str, Any]] = None,
) -> Tuple[WebLeadRow, bool]:
    """Enrich cohort row using full REISift tags/lists; anchor from cohort track."""
    address = _format_address(cohort_row)
    cohort_created = _reisift_created_ts(cohort_row, cohort_created_col)
    reisift_created = _reisift_created_ts(reisift_row, reisift_created_col)
    cohort_tags = cohort_row.get("Tags", "")
    web_tag_date = parse_web_lead_tag_date(cohort_tags) or parse_web_lead_tag_date(
        reisift_row.get("Tags", "")
    )

    anchor = _web_anchor_date(cohort_created, reisift_created, web_tag_date)
    if anchor is None:
        anchor = pd.Timestamp.now().normalize()

    tags_val = reisift_row.get("Tags", "")
    has_8020 = tags_have_8020(tags_val) or tags_have_8020(cohort_tags)
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

    lists = analysis_list_tokens(reisift_row.get("Lists", ""))
    stackable = stackable_list_tokens(reisift_row.get("Lists", ""))
    combo_key = " + ".join(sorted(stackable)) if len(stackable) >= 2 else ""
    journey = compute_web_journey_path(events, anchor)
    journey_compact = _compact_journey_display(journey)

    closings_matched = closings_entry is not None
    closings_date = (closings_entry or {}).get("date_closed", "")
    closings_stage = (closings_entry or {}).get("stage", "")

    cohort_track_date_str = (
        cohort_created.date().isoformat() if cohort_created is not None else ""
    )

    row = WebLeadRow(
        address=address,
        address_key=address_key,
        cohort_track_date=cohort_track_date_str,
        reisift_created_on=(
            reisift_created.date().isoformat() if reisift_created is not None else ""
        ),
        anchor_date=anchor.date().isoformat(),
        lists=lists,
        combo_key=combo_key,
        had_prior_history=had_prior,
        earliest_list_date=earliest_list_str,
        days_list_to_web=days_list,
        prior_8020_channels=channels,
        has_8020_tag=has_8020,
        journey_path=journey,
        journey_path_compact=journey_compact,
        matched=True,
        closings_matched=closings_matched,
        closings_date_closed=closings_date,
        closings_stage=closings_stage,
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
    cohort_source: str = COHORT_SOURCE_DEFAULT,
    on_progress: Optional[ProgressCallback] = None,
) -> WebLeadsResult:
    if on_progress:
        on_progress(85, "Aggregating compact summaries…")

    match_rate = round(100.0 * matched / website_total, 2) if website_total else 0.0
    prior_pct = round(100.0 * prior_count / matched, 1) if matched else 0.0
    new_to_db_count = sum(1 for r in rows if not r.has_8020_tag)
    new_pct = round(100.0 * new_to_db_count / matched, 1) if matched else 0.0

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
        new_to_db_count=new_to_db_count,
        new_to_db_pct=new_pct,
        top_lists=top_lists,
        combinations=combinations,
        top_paths=top_paths,
        age_buckets=age_buckets,
        rows=rows,
        warnings=warnings,
        methodology_note=methodology,
        cohort_source=cohort_source,
    )


def analyze(
    cohort_path: str,
    reisift_reference_path: str,
    closings_path: Optional[str] = None,
    *,
    cohort_source: str = COHORT_SOURCE_DEFAULT,
    on_progress: Optional[ProgressCallback] = None,
) -> WebLeadsResult:
    """Match a manually filtered cohort track to the full REISift reference."""
    warnings: List[str] = []
    cohort_label = COHORT_SOURCE_LABELS.get(cohort_source, cohort_source)

    def report(progress: int, message: str) -> None:
        if on_progress:
            on_progress(progress, message)

    report(5, "Loading cohort track file…")
    cohort_df = load_reisift_file(cohort_path)
    cohort_total = len(cohort_df)
    if cohort_total == 0:
        raise ValueError("Cohort track file is empty.")

    report(15, "Loading full REISift reference…")
    reisift_df = load_reisift_file(reisift_reference_path)
    reisift_ingested = len(reisift_df)

    cohort_created_col = _discover_reisift_created_col(cohort_df)
    reisift_created_col = _discover_reisift_created_col(reisift_df)
    if not cohort_created_col:
        warnings.append(
            "Cohort track file has no Created column; track dates use web-lead tag month only."
        )
    if not reisift_created_col:
        warnings.append("REISift reference has no Created column.")

    if "Tags" not in cohort_df.columns:
        warnings.append(
            "Cohort track file has no Tags column; web-lead anchor uses Created dates only."
        )

    report(25, "Indexing REISift reference addresses…")
    reisift_index = _build_reisift_index(reisift_df)

    closings_index: Dict[str, Dict[str, Any]] = {}
    if closings_path:
        report(30, "Loading closings workbook…")
        closings_index = _build_closings_index(closings_path)
        if not closings_index:
            warnings.append(
                "Closings file loaded but no stage-filtered closings matched address columns."
            )

    rows: List[WebLeadRow] = []
    list_counter: Counter[str] = Counter()
    combo_counter: Counter[str] = Counter()
    path_counter: Counter[str] = Counter()
    age_counter: Counter[str] = Counter()
    matched = 0
    unmatched = 0
    prior_count = 0
    track_dates: List[pd.Timestamp] = []

    report(40, f"Matching {cohort_total:,} cohort rows to REISift…")
    for i, (_, cohort_row) in enumerate(cohort_df.iterrows()):
        key = _reisift_address_key(cohort_row)
        cohort_created = _reisift_created_ts(cohort_row, cohort_created_col)
        if cohort_created is not None:
            track_dates.append(cohort_created)
        web_tag = parse_web_lead_tag_date(cohort_row.get("Tags", ""))
        if web_tag is not None:
            track_dates.append(web_tag)

        idx = reisift_index.get(key)
        if idx is None:
            unmatched += 1
            continue

        matched += 1
        reisift_row = reisift_df.iloc[idx]
        closings_entry = closings_index.get(key)
        web_row, had_prior = _process_cohort_reisift_match(
            cohort_row,
            reisift_row,
            cohort_created_col,
            reisift_created_col,
            key,
            closings_entry,
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
        path_counter[web_row.journey_path_compact] += 1

        if on_progress and i > 0 and i % 50 == 0:
            report(
                40 + int(40 * i / max(cohort_total, 1)),
                f"Row {i:,} / {cohort_total:,}…",
            )

    if cohort_total and matched == 0:
        warnings.append(
            "No cohort rows matched the REISift reference by address; check exports align."
        )
    elif cohort_total and round(100.0 * matched / cohort_total, 2) < 50:
        warnings.append(
            f"Only {round(100.0 * matched / cohort_total, 2)}% of cohort rows "
            "matched REISift by address; check exports align."
        )

    window_start = min(track_dates).date().isoformat() if track_dates else ""
    window_end = max(track_dates).date().isoformat() if track_dates else ""

    methodology = (
        f"Cohort = {cohort_label} (manually filtered export). "
        "Each row is matched to the full REISift reference by normalized property address. "
        "This report lists REISift matches only; unmatched cohort rows are counted but not shown. "
        "Anchor date = List Purchased Web Leads tag month when present, else cohort Created on "
        "(fallback: REISift Created on). "
        "Prior history = distress list purchase or (8020) CC/SMS/DM strictly before anchor. "
        "New to database = matched rows with no 8020 tag on the REISift record. "
        f"List combinations require ≥{COMBO_MIN_ROWS} matched rows and cap at {COMBO_CAP}. "
        f"Journey paths cap at {PATH_CAP} compact routes ending in WEB."
    )
    if closings_path:
        methodology += " Closings enrichment uses stage-filtered closings matched by address."

    return _finalize_result(
        date_window_start=window_start,
        date_window_end=window_end,
        reisift_ingested=reisift_ingested,
        website_total=cohort_total,
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
        cohort_source=cohort_source,
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
            {"metric": "Cohort track rows", "value": result.website_ql_total},
            {"metric": "Cohort source", "value": result.cohort_source},
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
