"""
Monthly consolidated report API.
"""

from __future__ import annotations

import json
import math
import shutil
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
from ..utils.file_handler import UPLOAD_DIR

monthly_consolidated_bp = Blueprint("monthly_consolidated", __name__)

MCR_ROOT = UPLOAD_DIR / "monthly_consolidated"
MCR_ROOT.mkdir(parents=True, exist_ok=True)

_job_results: Dict[str, Dict[str, Any]] = {}


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
                _job_results[job_id] = {"metrics": loaded["metrics"]}
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


@monthly_consolidated_bp.route("/analyze", methods=["POST"])
def monthly_consolidated_analyze():
    reisift = request.files.get("reisift_file")
    ql = request.files.get("qualified_leads_file")
    report_month = (request.form.get("report_month") or "").strip()

    if not reisift or not reisift.filename:
        return jsonify({"detail": "reisift_file is required"}), 400
    if not ql or not ql.filename:
        return jsonify({"detail": "qualified_leads_file is required"}), 400

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

    try:
        result = analyze(str(reisift_path), str(ql_path), report_month)
    except ValueError as exc:
        shutil.rmtree(job_dir, ignore_errors=True)
        return jsonify({"detail": str(exc)}), 400
    except Exception as exc:
        shutil.rmtree(job_dir, ignore_errors=True)
        return jsonify({"detail": f"Analysis failed: {exc}"}), 500

    metrics = result.to_dict()
    created_at = datetime.now(timezone.utc).isoformat()
    payload = {
        "job_id": job_id,
        "status": "completed",
        "metrics": metrics,
        "warnings": metrics.get("warnings", []),
        "created_at": created_at,
    }
    _job_results[job_id] = {"metrics": metrics}

    try:
        save_monthly_consolidated_report(job_id, metrics=metrics, created_at=created_at)
    except OSError as exc:
        return jsonify({"detail": f"Failed to save report: {exc}"}), 500

    meta_path = job_dir / "result.json"
    with open(meta_path, "w", encoding="utf-8") as fh:
        json.dump(_sanitize_for_json(payload), fh, indent=2)

    return jsonify(_sanitize_for_json(payload))


@monthly_consolidated_bp.route("/<job_id>", methods=["GET"])
def monthly_consolidated_get(job_id: str):
    cached = _job_results.get(job_id)
    if cached:
        return jsonify(
            _sanitize_for_json(
                {
                    "job_id": job_id,
                    "status": "completed",
                    "metrics": cached["metrics"],
                    "warnings": cached["metrics"].get("warnings", []),
                }
            )
        )
    loaded = load_monthly_consolidated_report(job_id)
    if loaded:
        _job_results[job_id] = {"metrics": loaded["metrics"]}
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
    delete_report_file(job_id)
    job_dir = MCR_ROOT / job_id
    if job_dir.is_dir():
        shutil.rmtree(job_dir, ignore_errors=True)
    return jsonify({"detail": "Deleted"})
