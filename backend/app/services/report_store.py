"""
Persist and list saved report snapshots (attribution, qualified leads, etc.).
"""

from __future__ import annotations

import json
import logging
import math
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

REPORT_TYPE_ATTRIBUTION = "attribution"
REPORT_TYPE_QUALIFIED_LEADS = "qualified_leads"
REPORT_TYPE_MONTHLY_CONSOLIDATED = "monthly_consolidated"


def _candidate_reports_dirs() -> List[Path]:
    raw = os.environ.get("REPORTS_DIR", "").strip()
    candidates: List[Path] = []
    if raw:
        candidates.append(Path(raw))
    candidates.extend(
        [
            Path("/app/reports"),
            Path(__file__).resolve().parent.parent.parent / "reports",
            Path.cwd() / "reports",
        ]
    )
    return candidates


def get_reports_dir() -> Path:
    for candidate in _candidate_reports_dirs():
        try:
            candidate.mkdir(parents=True, exist_ok=True)
            return candidate
        except OSError:
            continue
    fallback = Path(__file__).resolve().parent.parent.parent / "reports"
    fallback.mkdir(parents=True, exist_ok=True)
    return fallback


def _sanitize_for_json(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {k: _sanitize_for_json(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_sanitize_for_json(v) for v in obj]
    if isinstance(obj, float) and (math.isnan(obj) or math.isinf(obj)):
        return None
    return obj


def _write_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(_sanitize_for_json(payload), fh, indent=2)


def save_attribution_report(
    job_id: str,
    result: Dict[str, Any],
    created_at: str,
    reports_dir: Optional[Path] = None,
) -> Path:
    root = reports_dir or get_reports_dir()
    as_of = result.get("as_of")
    if as_of:
        path = root / "snapshots" / str(as_of) / f"{job_id}.json"
    else:
        path = root / f"{job_id}.json"
    payload = {
        "report_type": REPORT_TYPE_ATTRIBUTION,
        "job_id": job_id,
        "results": result.get("results", []),
        "stats": result.get("stats", {}),
        "matched_count": result.get("matched_count", 0),
        "total_deals": result.get("total_deals", 0),
        "created_at": created_at,
        "as_of": as_of,
    }
    _write_json(path, payload)
    return path


def save_monthly_consolidated_report(
    job_id: str,
    metrics: Dict[str, Any],
    created_at: Optional[str] = None,
    reports_dir: Optional[Path] = None,
) -> Path:
    root = reports_dir or get_reports_dir()
    path = root / "monthly_consolidated" / f"{job_id}.json"
    ts = created_at or datetime.now(timezone.utc).isoformat()
    payload = {
        "report_type": REPORT_TYPE_MONTHLY_CONSOLIDATED,
        "job_id": job_id,
        "created_at": ts,
        "metrics": metrics,
    }
    _write_json(path, payload)
    return path


def load_monthly_consolidated_report(
    job_id: str, reports_dir: Optional[Path] = None
) -> Optional[Dict[str, Any]]:
    root = reports_dir or get_reports_dir()
    path = root / "monthly_consolidated" / f"{job_id}.json"
    if not path.is_file():
        return None
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    return {
        "job_id": job_id,
        "metrics": data.get("metrics", {}),
        "created_at": data.get("created_at"),
    }


def save_qualified_leads_report(
    job_id: str,
    metrics: Dict[str, Any],
    use_full_file_span: bool,
    rows: List[Dict[str, Any]],
    created_at: Optional[str] = None,
    reports_dir: Optional[Path] = None,
) -> Path:
    root = reports_dir or get_reports_dir()
    path = root / "qualified_leads" / f"{job_id}.json"
    ts = created_at or datetime.now(timezone.utc).isoformat()
    payload = {
        "report_type": REPORT_TYPE_QUALIFIED_LEADS,
        "job_id": job_id,
        "created_at": ts,
        "metrics": metrics,
        "use_full_file_span": use_full_file_span,
        "rows": rows,
    }
    _write_json(path, payload)
    return path


def _is_attribution_payload(data: Dict[str, Any]) -> bool:
    rtype = data.get("report_type")
    if rtype and rtype != REPORT_TYPE_ATTRIBUTION:
        return False
    return "results" in data or "stats" in data


def _summary_for_qualified(metrics: Dict[str, Any]) -> str:
    posted = metrics.get("posted_in_window", 0)
    return f"{posted:,} posted in window"


def _summary_for_attribution(matched: int, total: int) -> str:
    return f"{matched:,} / {total:,} matched"


def _summary_for_monthly(metrics: Dict[str, Any]) -> str:
    month = metrics.get("report_month", "—")
    cohort = metrics.get("cohort", {}).get("total_rows", 0)
    closings = metrics.get("cohort", {}).get("closing_rows", 0)
    return f"{month} · {cohort:,} cohort · {closings:,} closings"


def list_report_index(reports_dir: Optional[Path] = None) -> List[Dict[str, Any]]:
    """Scan REPORTS_DIR for all saved report JSON files."""
    root = reports_dir or get_reports_dir()
    items: List[Dict[str, Any]] = []
    if not root.is_dir():
        return items

    for path in root.rglob("*.json"):
        try:
            with open(path, encoding="utf-8") as fh:
                data = json.load(fh)
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("Skipping unreadable report %s: %s", path, exc)
            continue

        rtype = data.get("report_type", REPORT_TYPE_ATTRIBUTION)
        job_id = data.get("job_id") or path.stem
        created_at = data.get(
            "created_at",
            datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).isoformat(),
        )

        if rtype == REPORT_TYPE_QUALIFIED_LEADS:
            metrics = data.get("metrics") or {}
            items.append(
                {
                    "job_id": job_id,
                    "report_type": rtype,
                    "status": "completed",
                    "created_at": created_at,
                    "summary": _summary_for_qualified(metrics),
                    "posted_in_window": metrics.get("posted_in_window", 0),
                    "rows_ingested": metrics.get("rows_ingested", 0),
                    "date_window_start": metrics.get("date_window_start"),
                    "date_window_end": metrics.get("date_window_end"),
                }
            )
        elif rtype == REPORT_TYPE_MONTHLY_CONSOLIDATED:
            metrics = data.get("metrics") or {}
            cohort = metrics.get("cohort", {})
            items.append(
                {
                    "job_id": job_id,
                    "report_type": rtype,
                    "status": "completed",
                    "created_at": created_at,
                    "summary": _summary_for_monthly(metrics),
                    "report_month": metrics.get("report_month"),
                    "cohort_rows": cohort.get("total_rows", 0),
                    "closing_rows": cohort.get("closing_rows", 0),
                }
            )
        elif _is_attribution_payload(data):
            matched = int(data.get("matched_count", 0) or 0)
            total = int(data.get("total_deals", 0) or 0)
            items.append(
                {
                    "job_id": job_id,
                    "report_type": REPORT_TYPE_ATTRIBUTION,
                    "status": "completed",
                    "created_at": created_at,
                    "summary": _summary_for_attribution(matched, total),
                    "matched_count": matched,
                    "total_deals": total,
                    "as_of": data.get("as_of"),
                }
            )

    items.sort(key=lambda x: x.get("created_at", ""), reverse=True)
    return items


def load_qualified_leads_report(
    job_id: str, reports_dir: Optional[Path] = None
) -> Optional[Dict[str, Any]]:
    root = reports_dir or get_reports_dir()
    path = root / "qualified_leads" / f"{job_id}.json"
    if not path.is_file():
        return None
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    return {
        "job_id": job_id,
        "metrics": data.get("metrics", {}),
        "use_full_file_span": data.get("use_full_file_span", False),
        "rows": data.get("rows", []),
        "created_at": data.get("created_at"),
    }


def delete_report_file(job_id: str, reports_dir: Optional[Path] = None) -> bool:
    root = reports_dir or get_reports_dir()
    deleted = False
    for path in root.rglob(f"{job_id}.json"):
        try:
            path.unlink()
            deleted = True
        except OSError as exc:
            logger.warning("Failed to delete %s: %s", path, exc)
    return deleted
