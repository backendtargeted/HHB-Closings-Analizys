"""
Monthly consolidated report API.
"""

from __future__ import annotations

import json
import math
import shutil
import threading
import uuid
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from typing import Any, Dict

from flask import Blueprint, jsonify, request, send_file

from ..services.monthly_consolidated import (
    REPORT_TYPE,
    analyze,
    build_export_workbook,
    parse_report_month,
)
from ..services.report_store import (
    delete_report_file,
    load_monthly_consolidated_report,
    save_monthly_consolidated_report,
)
from ..services.resumable_uploads import resolve_trusted_final_path
from ..utils.file_handler import UPLOAD_DIR

monthly_consolidated_bp = Blueprint("monthly_consolidated", __name__)

MCR_ROOT = UPLOAD_DIR / "monthly_consolidated"
MCR_ROOT.mkdir(parents=True, exist_ok=True)

_job_results: Dict[str, Dict[str, Any]] = {}
_jobs: Dict[str, Dict[str, Any]] = {}


def _job_snapshot(job_id: str) -> Dict[str, Any] | None:
    live = _jobs.get(job_id)
    if live:
        return live
    cached = _job_results.get(job_id)
    if cached:
        return {
            "status": "completed",
            "progress": 100,
            "message": "Analysis complete",
            "metrics": cached.get("metrics"),
            "warnings": cached.get("metrics", {}).get("warnings", []),
            "created_at": cached.get("created_at"),
        }
    return None


def load_monthly_consolidated_from_disk() -> None:
    from ..services.report_store import get_reports_dir

    mcr_dir = get_reports_dir() / "monthly_consolidated"
    if not mcr_dir.is_dir():
        return
    for path in mcr_dir.glob("*.json"):
        try:
            job_id = path.stem
            loaded = load_monthly_consolidated_report(job_id)
            if loaded:
                _job_results[job_id] = {
                    "metrics": loaded["metrics"],
                    "created_at": loaded.get("created_at"),
                }
        except (json.JSONDecodeError, OSError):
            continue


def _sanitize_for_json(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {k: _sanitize_for_json(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_sanitize_for_json(v) for v in obj]
    if isinstance(obj, float) and (math.isnan(obj) or math.isinf(obj)):
        return None
    return obj


def _run_monthly_consolidated_job(
    job_id: str,
    reisift_path: str,
    ql_path: str,
    report_month: str | None,
) -> None:
    job_dir = MCR_ROOT / job_id
    try:
        _jobs[job_id]["status"] = "running"
        _jobs[job_id]["progress"] = 10
        _jobs[job_id]["message"] = "Analyzing REISift export…"

        result = analyze(reisift_path, ql_path, report_month)

        _jobs[job_id]["progress"] = 90
        _jobs[job_id]["message"] = "Saving report…"

        metrics = result.to_dict()
        created_at = datetime.now(timezone.utc).isoformat()
        payload = {
            "job_id": job_id,
            "status": "completed",
            "metrics": metrics,
            "warnings": metrics.get("warnings", []),
            "created_at": created_at,
        }
        _job_results[job_id] = {"metrics": metrics, "created_at": created_at}
        save_monthly_consolidated_report(job_id, metrics=metrics, created_at=created_at)

        meta_path = job_dir / "result.json"
        with open(meta_path, "w", encoding="utf-8") as fh:
            json.dump(_sanitize_for_json(payload), fh, indent=2)

        _jobs[job_id].update(
            {
                "status": "completed",
                "progress": 100,
                "message": "Analysis complete",
                "metrics": metrics,
                "warnings": metrics.get("warnings", []),
                "created_at": created_at,
            }
        )
    except ValueError as exc:
        shutil.rmtree(job_dir, ignore_errors=True)
        _jobs[job_id].update(
            {"status": "failed", "progress": 0, "message": str(exc)}
        )
    except Exception as exc:
        shutil.rmtree(job_dir, ignore_errors=True)
        _jobs[job_id].update(
            {"status": "failed", "progress": 0, "message": f"Analysis failed: {exc}"}
        )


def _start_monthly_consolidated_job(
    reisift_path: str,
    ql_path: str,
    report_month: str | None,
    job_id: str | None = None,
) -> tuple[dict[str, Any], int]:
    job_id = job_id or str(uuid.uuid4())
    job_dir = MCR_ROOT / job_id
    job_dir.mkdir(parents=True, exist_ok=True)

    _jobs[job_id] = {
        "job_id": job_id,
        "status": "pending",
        "progress": 0,
        "message": "Analysis queued…",
        "metrics": None,
        "warnings": [],
        "created_at": None,
    }

    thread = threading.Thread(
        target=_run_monthly_consolidated_job,
        args=(job_id, reisift_path, ql_path, report_month),
        daemon=True,
    )
    thread.start()

    return (
        {
            "job_id": job_id,
            "status": "started",
            "message": "Analysis started",
        },
        202,
    )


@monthly_consolidated_bp.route("/analyze", methods=["POST"])
def monthly_consolidated_analyze():
    if request.is_json:
        data = request.get_json() or {}
        report_month = (data.get("report_month") or "").strip() or None
        reisift_raw = (data.get("reisift_path") or "").strip()
        ql_raw = (data.get("qualified_leads_path") or "").strip()
        if not reisift_raw:
            return jsonify({"detail": "reisift_path is required"}), 400
        if not ql_raw:
            return jsonify({"detail": "qualified_leads_path is required"}), 400
        if report_month:
            try:
                parse_report_month(report_month)
            except ValueError as exc:
                return jsonify({"detail": str(exc)}), 400
        try:
            reisift_path = str(resolve_trusted_final_path(reisift_raw))
            ql_path = str(resolve_trusted_final_path(ql_raw))
        except ValueError as exc:
            return jsonify({"detail": str(exc)}), 400
        payload, status = _start_monthly_consolidated_job(
            reisift_path, ql_path, report_month
        )
        return jsonify(_sanitize_for_json(payload)), status

    reisift = request.files.get("reisift_file")
    ql = request.files.get("qualified_leads_file")
    report_month = (request.form.get("report_month") or "").strip() or None

    if not reisift or not reisift.filename:
        return jsonify({"detail": "reisift_file is required"}), 400
    if not ql or not ql.filename:
        return jsonify({"detail": "qualified_leads_file is required"}), 400

    if report_month:
        try:
            parse_report_month(report_month)
        except ValueError as exc:
            return jsonify({"detail": str(exc)}), 400

    job_id = str(uuid.uuid4())
    job_dir = MCR_ROOT / job_id
    job_dir.mkdir(parents=True, exist_ok=True)

    reisift_name = Path(reisift.filename.replace("\\", "/")).name
    ql_name = Path(ql.filename.replace("\\", "/")).name
    reisift_path = job_dir / reisift_name
    ql_path = job_dir / ql_name
    reisift.save(str(reisift_path))
    ql.save(str(ql_path))

    payload, status = _start_monthly_consolidated_job(
        str(reisift_path), str(ql_path), report_month, job_id=job_id
    )
    return jsonify(_sanitize_for_json(payload)), status


@monthly_consolidated_bp.route("/<job_id>/status", methods=["GET"])
def monthly_consolidated_status(job_id: str):
    snap = _job_snapshot(job_id)
    if not snap:
        meta_path = MCR_ROOT / job_id / "result.json"
        if meta_path.is_file():
            with open(meta_path, encoding="utf-8") as fh:
                data = json.load(fh)
            return jsonify(
                _sanitize_for_json(
                    {
                        "job_id": job_id,
                        "status": "completed",
                        "progress": 100,
                        "message": "Analysis complete",
                    }
                )
            )
        return jsonify({"detail": "Job not found"}), 404

    return jsonify(
        _sanitize_for_json(
            {
                "job_id": job_id,
                "status": snap.get("status", "pending"),
                "progress": snap.get("progress", 0),
                "message": snap.get("message", ""),
            }
        )
    )


@monthly_consolidated_bp.route("/<job_id>", methods=["GET"])
def monthly_consolidated_get(job_id: str):
    snap = _job_snapshot(job_id)
    if snap:
        status = snap.get("status", "completed")
        if status in ("pending", "running", "started"):
            return jsonify(
                _sanitize_for_json(
                    {
                        "job_id": job_id,
                        "status": status,
                        "message": snap.get("message", ""),
                    }
                )
            )
        if status == "failed":
            return jsonify(
                _sanitize_for_json(
                    {
                        "job_id": job_id,
                        "status": "failed",
                        "message": snap.get("message", "Analysis failed"),
                    }
                ),
                400,
            )
        metrics = snap.get("metrics")
        if metrics:
            return jsonify(
                _sanitize_for_json(
                    {
                        "job_id": job_id,
                        "status": "completed",
                        "metrics": metrics,
                        "warnings": snap.get("warnings") or metrics.get("warnings", []),
                        "created_at": snap.get("created_at"),
                    }
                )
            )

    loaded = load_monthly_consolidated_report(job_id)
    if loaded:
        _job_results[job_id] = {
            "metrics": loaded["metrics"],
            "created_at": loaded.get("created_at"),
        }
        return jsonify(
            _sanitize_for_json(
                {
                    "job_id": job_id,
                    "status": "completed",
                    "metrics": loaded["metrics"],
                    "warnings": loaded["metrics"].get("warnings", []),
                }
            )
        )
    meta_path = MCR_ROOT / job_id / "result.json"
    if not meta_path.is_file():
        return jsonify({"detail": "Job not found"}), 404
    with open(meta_path, encoding="utf-8") as fh:
        data = json.load(fh)
    return jsonify(_sanitize_for_json(data))


@monthly_consolidated_bp.route("/<job_id>/export", methods=["GET"])
def monthly_consolidated_export(job_id: str):
    from ..services.monthly_consolidated import build_export_workbook, result_from_metrics_dict

    cached = _job_results.get(job_id)
    if not cached:
        loaded = load_monthly_consolidated_report(job_id)
        if loaded:
            cached = {"metrics": loaded["metrics"]}
            _job_results[job_id] = cached
    if not cached:
        return jsonify({"detail": "Job not found"}), 404

    result = result_from_metrics_dict(cached["metrics"])

    try:
        xlsx = build_export_workbook(result)
    except ValueError as exc:
        return jsonify({"detail": str(exc)}), 400

    buf = BytesIO(xlsx)
    buf.seek(0)
    month = cached["metrics"].get("report_month", job_id)
    return send_file(
        buf,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        as_attachment=True,
        download_name=f"monthly_consolidated_{month}_{job_id}.xlsx",
    )


@monthly_consolidated_bp.route("/<job_id>", methods=["DELETE"])
def monthly_consolidated_delete(job_id: str):
    _job_results.pop(job_id, None)
    _jobs.pop(job_id, None)
    delete_report_file(job_id)
    job_dir = MCR_ROOT / job_id
    if job_dir.is_dir():
        shutil.rmtree(job_dir, ignore_errors=True)
    return jsonify({"detail": "Deleted"})
