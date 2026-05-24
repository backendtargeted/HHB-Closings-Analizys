"""Date confidence annotations for journey events."""

from __future__ import annotations

from typing import Any, Dict


def infer_precision(event_date: str) -> str:
    text = str(event_date or "").strip()
    if len(text) >= 10 and text[4] == "-" and text[7] == "-":
        return "day"
    return "month"


def classify_confidence(date_source: str, date_precision: str) -> str:
    src = str(date_source or "")
    prec = str(date_precision or "day")
    if src in ("close_date", "created_date", "date_closed") and prec == "day":
        return "high"
    if prec == "month":
        return "medium"
    if src in ("filename_proxy", "inferred"):
        return "low"
    return "medium"


def attach_confidence(event: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(event)
    prec = out.get("date_precision") or infer_precision(out.get("event_date", ""))
    src = out.get("date_source") or "unknown"
    out["date_precision"] = prec
    out["date_source"] = src
    out["date_confidence"] = classify_confidence(src, prec)
    return out


def summarize_confidence(events: list[Dict[str, Any]]) -> Dict[str, int]:
    summary = {"high": 0, "medium": 0, "low": 0}
    for ev in events:
        level = str(ev.get("date_confidence", "medium"))
        if level in summary:
            summary[level] += 1
    return summary
