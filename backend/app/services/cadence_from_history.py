"""
Experimental cadence signals from REISift-style Tags strings.

Grounded in existing parse_tags + lifecycle Event ordering (no ATTOM / no DB).
Month-granular (8020) tags yield coarse gaps; (SF) day tags improve resolution.

Not a production "Golden Loop" — use for offline probes and future orchestration hooks.
"""

from __future__ import annotations

from statistics import median
from typing import Any, Dict, List, Optional

import pandas as pd

from .analysis import parse_tags
from .lifecycle import Event, build_events, events_before_close


def inter_event_day_gaps(events: List[Event]) -> List[int]:
    """Sorted chronological gaps in whole days between consecutive events."""
    if len(events) < 2:
        return []
    seq = sorted(events, key=lambda e: (e.sort_dt, e.sort_rank, e.date_iso))
    out: List[int] = []
    for a, b in zip(seq, seq[1:]):
        out.append(max(0, (b.sort_dt - a.sort_dt).days))
    return out


def _percentile(sorted_vals: List[int], p: float) -> Optional[int]:
    if not sorted_vals:
        return None
    if len(sorted_vals) == 1:
        return sorted_vals[0]
    k = (len(sorted_vals) - 1) * p
    f = int(k)
    c = min(f + 1, len(sorted_vals) - 1)
    if f == c:
        return sorted_vals[f]
    return int(sorted_vals[f] + (sorted_vals[c] - sorted_vals[f]) * (k - f))


def _gap_summary(gaps: List[int]) -> Dict[str, Any]:
    if not gaps:
        return {
            "n_gaps": 0,
            "min_days": None,
            "median_days": None,
            "p75_days": None,
            "max_days": None,
        }
    s = sorted(gaps)
    return {
        "n_gaps": len(s),
        "min_days": s[0],
        "median_days": int(median(s)) if s else None,
        "p75_days": _percentile(s, 0.75),
        "max_days": s[-1],
    }


def summarize_tag_cadence(tags_str: str) -> Dict[str, Any]:
    """
    Full timeline cadence (all parsed events, including after any implicit close).
    Good for vendor-style timelines when no close date is supplied.
    """
    parsed = parse_tags(tags_str)
    events = build_events(parsed)
    gaps = inter_event_day_gaps(events)
    by_type: Dict[str, int] = {}
    for e in events:
        by_type[e.type] = by_type.get(e.type, 0) + 1
    return {
        "n_events": len(events),
        "events_by_type": by_type,
        "inter_event_gaps_days": gaps,
        "gap_summary": _gap_summary(gaps),
    }


def summarize_cadence_before_close(tags_str: str, closed_date_iso: str) -> Dict[str, Any]:
    """
    Same as lifecycle analysis: only events strictly before Date Closed.
    Use for "what rhythm led to this close" experiments.
    """
    closed = pd.to_datetime(closed_date_iso, errors="coerce")
    if closed is None or pd.isna(closed):
        return {
            "error": "invalid_closed_date",
            "closed_date_iso": closed_date_iso,
        }
    parsed = parse_tags(tags_str)
    events = build_events(parsed)
    before = events_before_close(events, closed)
    gaps = inter_event_day_gaps(before)
    by_type: Dict[str, int] = {}
    for e in before:
        by_type[e.type] = by_type.get(e.type, 0) + 1
    return {
        "n_events_before_close": len(before),
        "events_by_type": by_type,
        "inter_event_gaps_days": gaps,
        "gap_summary": _gap_summary(gaps),
        "closed_date_iso": closed_date_iso,
    }
