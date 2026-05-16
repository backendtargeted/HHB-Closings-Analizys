"""
Lead lifecycle: ordered events, funnel stages, paths, and first-touch metrics.

Stage label sets are normalized with marketing_mapper.normalize_status for parity
with CRM / mapper vocabulary. Older saved reports may omit lifecycle fields.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

from .marketing_mapper import normalize_status

# ---------------------------------------------------------------------------
# Stage classification (normalized lowercase status strings)
# ---------------------------------------------------------------------------

# SF "converted" / under contract — contract signed, not settlement closed (mapper CRM keys).
CONVERTED_LABELS: frozenset[str] = frozenset(
    normalize_status(x) for x in ("converted", "under contract", "under_contract")
)

# Engagement: active CRM / outreach states before conversion (seeded from CRM + common follow-ups).
_ENGAGED_SEED = (
    "new",
    "follow up",
    "not yet reached",
    "decision maker - lead",
    "callback",
    "influencer",
    "listed property",
    "spanish speaker",
    "maybe later",
    "maybe later (sms)",
    "abv mv",
    "abv mv (sms)",
    "not interested",
    "bluffer",
    "bluffer (sms)",
    "agent",
    "voicemail",
    "wrong number",
    "dnc - decision maker",
    "dnc - unknown",
    "dnc",
)
ENGAGED_LABELS: frozenset[str] = frozenset(normalize_status(x) for x in _ENGAGED_SEED) - CONVERTED_LABELS

STAGE_ORDER = (
    "ACQUIRED",
    "RESEARCHED",
    "FIRST_CONTACTED",
    "ENGAGED",
    "CONVERTED",
    "CLOSED",
)

# CLOSED is always true for a closed deal — do not use it for "highest" ranking.
_STAGES_FOR_HIGHEST = ("ACQUIRED", "RESEARCHED", "FIRST_CONTACTED", "ENGAGED", "CONVERTED")


@dataclass
class Event:
    """Single parsed tag occurrence for lifecycle ordering."""

    type: str
    label: str
    date_iso: str
    precision: str  # "day" | "month"
    tag: str
    sort_dt: datetime
    sort_rank: int  # lower = earlier on same calendar day tie-break


def _parse_iso(dt: str) -> datetime:
    return datetime.fromisoformat(dt.replace("Z", "+00:00"))


def _type_sort_rank(etype: str) -> int:
    """SF day events before month-granularity tags on the same calendar day."""
    order = {
        "sf_updated": 0,
        "sf_status": 1,
        "list_purchase": 10,
        "skip_trace": 11,
        "contact": 20,
        "closing": 30,
    }
    return order.get(etype, 50)


def build_events(parsed: List[Dict[str, Any]]) -> List[Event]:
    """
    Build ordered Event list from parse_tags output.
    Sort: by datetime, then by type_sort_rank (day SF before month contact on same day).
    """
    events: List[Event] = []
    for p in parsed:
        etype = str(p.get("type", ""))
        if etype not in (
            "contact",
            "list_purchase",
            "skip_trace",
            "closing",
            "sf_updated",
            "sf_status",
        ):
            continue
        date_iso = str(p.get("date", ""))
        if not date_iso:
            continue
        try:
            sort_dt = _parse_iso(date_iso)
        except ValueError:
            continue
        precision = str(p.get("precision", "month"))
        label = str(p.get("label", "") or p.get("channel", "") or "")
        tag = str(p.get("tag", ""))
        events.append(
            Event(
                type=etype,
                label=label,
                date_iso=date_iso,
                precision=precision,
                tag=tag,
                sort_dt=sort_dt,
                sort_rank=_type_sort_rank(etype),
            )
        )
    events.sort(key=lambda e: (e.sort_dt, e.sort_rank, e.date_iso))
    return events


def events_before_close(events: List[Event], closed_date: pd.Timestamp) -> List[Event]:
    out: List[Event] = []
    for e in events:
        try:
            if _parse_iso(e.date_iso) < closed_date.to_pydatetime():
                out.append(e)
        except ValueError:
            continue
    return out


def compute_stage_funnel(
    events: List[Event], closed_date: pd.Timestamp
) -> Dict[str, Dict[str, Any]]:
    """
    Per-stage {reached: bool, date: ISO|None} using events strictly before close.
    CLOSED uses the actual deal close date from Excel.
    """
    before = events_before_close(events, closed_date)
    closed_iso = (
        closed_date.isoformat()
        if isinstance(closed_date, pd.Timestamp)
        else str(closed_date)
    )

    def first_date(predicate) -> Optional[str]:
        for e in before:
            if predicate(e):
                return e.date_iso
        return None

    acquired = first_date(lambda e: e.type == "list_purchase")
    researched = first_date(lambda e: e.type == "skip_trace")
    first_contact = first_date(lambda e: e.type == "contact")

    def _sf_label_norm(e: Event) -> str:
        return normalize_status(e.label) if e.label else ""

    engaged = first_date(
        lambda e: e.type in ("sf_updated", "sf_status")
        and _sf_label_norm(e) in ENGAGED_LABELS
    )
    converted = first_date(
        lambda e: e.type in ("sf_updated", "sf_status")
        and _sf_label_norm(e) in CONVERTED_LABELS
    )

    stages = {
        "ACQUIRED": {"reached": acquired is not None, "date": acquired},
        "RESEARCHED": {"reached": researched is not None, "date": researched},
        "FIRST_CONTACTED": {"reached": first_contact is not None, "date": first_contact},
        "ENGAGED": {"reached": engaged is not None, "date": engaged},
        "CONVERTED": {"reached": converted is not None, "date": converted},
        "CLOSED": {"reached": True, "date": closed_iso},
    }
    return stages


def get_highest_stage(stages: Dict[str, Dict[str, Any]]) -> str:
    highest = "NONE"
    for name in _STAGES_FOR_HIGHEST:
        if stages.get(name, {}).get("reached"):
            highest = name
    return highest


def compute_ordered_path(events: List[Event], closed_date: pd.Timestamp) -> str:
    """
    Human-readable path, e.g. LIST -> SKIP -> CC -> SMS -> SF:follow_up -> CLOSED.
    Dedupes consecutive identical tokens.
    """
    before = events_before_close(events, closed_date)
    tokens: List[str] = []
    for e in before:
        if e.type == "list_purchase":
            t = "LIST"
        elif e.type == "skip_trace":
            t = "SKIP"
        elif e.type == "contact":
            t = e.label or "CONTACT"
        elif e.type in ("sf_updated", "sf_status"):
            slug = re.sub(r"\s+", "_", (e.label or "sf").lower())[:40]
            t = f"SF:{slug}"
        elif e.type == "closing":
            t = "CLOSED_TAG"
        else:
            continue
        if not tokens or tokens[-1] != t:
            tokens.append(t)
    tokens.append("CLOSED")
    return " -> ".join(tokens)


def compute_first_touch(
    events: List[Event], closed_date: pd.Timestamp
) -> Dict[str, Any]:
    """First (8020) channel before close; optional deltas vs list purchase and first engagement."""
    before = events_before_close(events, closed_date)
    close_dt = closed_date.to_pydatetime()

    first_contact_ev = next((e for e in before if e.type == "contact"), None)
    channel = first_contact_ev.label if first_contact_ev else None
    first_touch_date = first_contact_ev.date_iso if first_contact_ev else None

    list_ev = next((e for e in before if e.type == "list_purchase"), None)
    engaged_ev = next(
        (
            e
            for e in before
            if e.type in ("sf_updated", "sf_status")
            and normalize_status(e.label) in ENGAGED_LABELS
        ),
        None,
    )

    def _days(a: Optional[datetime], b: Optional[datetime]) -> Optional[int]:
        if a is None or b is None:
            return None
        return (b - a).days

    ftd = _parse_iso(first_touch_date) if first_touch_date else None
    ltd = _parse_iso(list_ev.date_iso) if list_ev else None
    engd = _parse_iso(engaged_ev.date_iso) if engaged_ev else None

    return {
        "channel": channel,
        "first_touch_date": first_touch_date,
        "days_list_to_first_touch": _days(ltd, ftd),
        "days_to_close": _days(ftd, close_dt) if ftd else None,
        "days_to_engagement": _days(ftd, engd) if ftd and engd else None,
    }


def sf_status_trail(events: List[Event], closed_date: pd.Timestamp) -> List[Dict[str, str]]:
    """Chronological SF tag events before close (label + date)."""
    out: List[Dict[str, str]] = []
    for e in events_before_close(events, closed_date):
        if e.type in ("sf_updated", "sf_status"):
            out.append({"label": e.label, "date": e.date_iso, "kind": e.type})
    return out


def first_dates_for_markers(events: List[Event], closed_date: pd.Timestamp) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    before = events_before_close(events, closed_date)
    lp = next((e.date_iso for e in before if e.type == "list_purchase"), None)
    sk = next((e.date_iso for e in before if e.type == "skip_trace"), None)
    cl = next((e.date_iso for e in before if e.type == "closing"), None)
    return lp, sk, cl


def _coerce_stages(val: Any) -> Dict[str, Any]:
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return {}
    if isinstance(val, str):
        try:
            return json.loads(val)
        except json.JSONDecodeError:
            return {}
    if isinstance(val, dict):
        return val
    return {}


def aggregate_lifecycle_stats(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Funnel counts, top paths, first-touch breakdown from per-deal row dicts
    (already includes lifecycle keys from analyze_contacts).
    """
    matched = [r for r in rows if r.get("Match Found")]
    if not matched:
        return {}

    def _stage_count(stage: str) -> int:
        return sum(
            1
            for r in matched
            if _coerce_stages(r.get("Stages Reached")).get(stage, {}).get("reached")
        )

    n = len(matched)
    acquired_n = _stage_count("ACQUIRED")
    researched_n = _stage_count("RESEARCHED")
    first_c_n = _stage_count("FIRST_CONTACTED")
    engaged_n = _stage_count("ENGAGED")
    converted_n = _stage_count("CONVERTED")

    def rate(a: int, b: int) -> Optional[float]:
        if b <= 0:
            return None
        return round(100.0 * a / b, 1)

    # Paths
    path_counts: Dict[str, int] = {}
    path_dtc: Dict[str, List[int]] = {}
    for r in matched:
        p = r.get("Path Sequence") or ""
        path_counts[p] = path_counts.get(p, 0) + 1
        dtc = r.get("Days to Close")
        if dtc is not None and not (isinstance(dtc, float) and pd.isna(dtc)):
            path_dtc.setdefault(p, []).append(int(dtc))

    top_paths: List[Dict[str, Any]] = []
    for path, cnt in sorted(path_counts.items(), key=lambda x: -x[1])[:5]:
        med = None
        vals = path_dtc.get(path, [])
        if vals:
            med = float(pd.Series(vals).median())
        top_paths.append({"path": path, "count": cnt, "median_days_to_close": med})

    # First touch
    ft_counts: Dict[str, int] = {}
    ft_dtc: Dict[str, List[int]] = {}
    for r in matched:
        ch = r.get("First Touch Channel") or "None"
        ft_counts[ch] = ft_counts.get(ch, 0) + 1
        dtc = r.get("Days to Close")
        if dtc is not None and not (isinstance(dtc, float) and pd.isna(dtc)):
            ft_dtc.setdefault(ch, []).append(int(dtc))

    first_touch_breakdown: List[Dict[str, Any]] = []
    for ch, cnt in sorted(ft_counts.items(), key=lambda x: -x[1]):
        vals = ft_dtc.get(ch, [])
        med = float(pd.Series(vals).median()) if vals else None
        first_touch_breakdown.append({"channel": ch, "count": cnt, "median_days_to_close": med})

    engaged_converted = sum(
        1
        for r in matched
        if _coerce_stages(r.get("Stages Reached")).get("ENGAGED", {}).get("reached")
        and _coerce_stages(r.get("Stages Reached")).get("CONVERTED", {}).get("reached")
    )

    return {
        "Funnel Acquired Count": acquired_n,
        "Funnel Researched Count": researched_n,
        "Funnel First Contacted Count": first_c_n,
        "Funnel Engaged Count": engaged_n,
        "Funnel Converted Count": converted_n,
        "Funnel Acquired Rate Pct": rate(acquired_n, n),
        "Funnel Researched Rate Pct": rate(researched_n, max(acquired_n, 1)) if acquired_n else rate(researched_n, n),
        "Funnel First Contact Rate Pct": rate(first_c_n, n),
        "Funnel Engaged Rate Pct": rate(engaged_n, n),
        "Funnel Converted Rate Pct": rate(converted_n, n),
        "Engaged To Converted Rate Pct": rate(engaged_converted, engaged_n) if engaged_n else None,
        "Top Paths Json": json.dumps(top_paths),
        "First Touch Breakdown Json": json.dumps(first_touch_breakdown),
    }


def events_to_jsonable(events: List[Event]) -> List[Dict[str, str]]:
    return [
        {"type": e.type, "label": e.label, "date": e.date_iso, "precision": e.precision, "tag": e.tag}
        for e in events
    ]
