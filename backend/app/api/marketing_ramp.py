"""
Marketing ramp report API.
"""

from __future__ import annotations

import json
import math
import shutil
import uuid
from io import BytesIO
from pathlib import Path
from typing import Any, Dict, Optional

from flask import Blueprint, jsonify, request, send_file

from ..services.monthly_consolidated import result_from_metrics_dict
from ..services.monthly_unified import analyze_unified, build_unified_export_workbook
from ..services.marketing_ramp import rows_to_export_csv
from ..services.qualified_leads import parse_ymd_param
from ..services.report_store import (
    REPORTS_DIR,
    delete_report_file,
    load_marketing_ramp_report,
    save_marketing_ramp_report,
)
from ..utils.file_handler import UPLOAD_DIR

marketing_ramp_bp = Blueprint("marketing_ramp", __name__)

MR_ROOT = UPLOAD_DIR / "marketing_ramp"
MR_ROOT.mkdir(parents=True, exist_ok=True)

_job_results: Dict[str, Dict[str, Any]] = {}


def load_marketing_ramp_from_disk() -> None:
    """Restore in-memory cache from persisted reports/marketing_ramp/*.json."""
    mr_dir = REPORTS_DIR / "marketing_ramp"
    if not mr_dir.is_dir():
        return
    for path in mr_dir.glob("*.json"):
        try:
            job_id = path.stem
            loaded = load_marketing_ramp_report(job_id)
            if loaded:
                entry: Dict[str, Any] = {
                    "metrics": loaded["metrics"],
                    "rows": loaded.get("rows", []),
                    "use_full_file_span": loaded.get("use_full_file_span", False),
                }
                if loaded.get("consolidated"):
                    entry["consolidated"] = loaded["consolidated"]
                _job_results[job_id] = entry
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


def _job_response(job_id: str, cached: Dict[str, Any]) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "job_id": job_id,
        "status": "completed",
        "metrics": cached["metrics"],
        "rows": cached.get("rows", []),
        "use_full_file_span": cached.get("use_full_file_span", False),
    }
    if cached.get("consolidated"):
        payload["consolidated"] = cached["consolidated"]
    return payload


@marketing_ramp_bp.route("/analyze", methods=["POST"])
def marketing_ramp_analyze():
    """
    Multipart: qualified_leads_file, reisift_file, closings_file.
    Form: use_full_file_span, start_date, end_date.
    """
    ql_upload = request.files.get("qualified_leads_file")
    reisift_upload = request.files.get("reisift_file")
    closings_upload = request.files.get("closings_file")

    if not ql_upload or not ql_upload.filename:
        return jsonify({"detail": "qualified_leads_file is required"}), 400
    if not reisift_upload or not reisift_upload.filename:
        return jsonify({"detail": "reisift_file is required"}), 400
    if not closings_upload or not closings_upload.filename:
        return jsonify({"detail": "closings_file is required"}), 400

    use_full = (request.form.get("use_full_file_span") or "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )
    start_raw = (request.form.get("start_date") or "").strip()
    end_raw = (request.form.get("end_date") or "").strip()

    job_id = str(uuid.uuid4())
    job_dir = MR_ROOT / job_id
    job_dir.mkdir(parents=True, exist_ok=True)

    def save_upload(upload, label: str) -> str:
        safe_name = Path(upload.filename.replace("\\", "/")).name
        path = job_dir / safe_name
        upload.save(str(path))
        return str(path)

    try:
        ql_path = save_upload(ql_upload, "qualified_leads")
        reisift_path = save_upload(reisift_upload, "reisift")
        closings_path = save_upload(closings_upload, "closings")
    except OSError as exc:
        shutil.rmtree(job_dir, ignore_errors=True)
        return jsonify({"detail": f"Failed to save uploads: {exc}"}), 500

    try:
        if use_full:
            unified = analyze_unified(
                ql_path,
                reisift_path,
                closings_path,
                use_full_file_span=True,
            )
        else:
            start_date = parse_ymd_param(start_raw, "start_date")
            end_date = parse_ymd_param(end_raw, "end_date")
            unified = analyze_unified(
                ql_path,
                reisift_path,
                closings_path,
                start_date=start_date,
                end_date=end_date,
                use_full_file_span=False,
            )
    except ValueError as exc:
        shutil.rmtree(job_dir, ignore_errors=True)
        return jsonify({"detail": str(exc)}), 400
    except Exception as exc:
        shutil.rmtree(job_dir, ignore_errors=True)
        return jsonify({"detail": f"Analysis failed: {exc}"}), 500

    api_data = unified.to_api_dict()
    metrics = api_data["metrics"]
    rows = api_data["rows"]
    consolidated = api_data["consolidated"]

    payload = {
        "job_id": job_id,
        "status": "completed",
        "metrics": metrics,
        "rows": rows,
        "use_full_file_span": use_full,
        "consolidated": consolidated,
    }
    _job_results[job_id] = {
        "metrics": metrics,
        "rows": rows,
        "use_full_file_span": use_full,
        "consolidated": consolidated,
    }

    try:
        save_marketing_ramp_report(
            job_id,
            metrics=metrics,
            use_full_file_span=use_full,
            rows=rows,
            consolidated=consolidated,
        )
    except OSError as exc:
        return jsonify({"detail": f"Failed to save report: {exc}"}), 500

    meta_path = job_dir / "result.json"
    with open(meta_path, "w", encoding="utf-8") as fh:
        json.dump(_sanitize_for_json(payload), fh, indent=2)

    return jsonify(_sanitize_for_json(payload))


@marketing_ramp_bp.route("/<job_id>", methods=["GET"])
def marketing_ramp_get(job_id: str):
    cached = _job_results.get(job_id)
    if cached:
        return jsonify(_sanitize_for_json(_job_response(job_id, cached)))
    loaded = load_marketing_ramp_report(job_id)
    if loaded:
        entry: Dict[str, Any] = {
            "metrics": loaded["metrics"],
            "rows": loaded.get("rows", []),
            "use_full_file_span": loaded.get("use_full_file_span", False),
        }
        if loaded.get("consolidated"):
            entry["consolidated"] = loaded["consolidated"]
        _job_results[job_id] = entry
        return jsonify(_sanitize_for_json(_job_response(job_id, entry)))
    meta_path = MR_ROOT / job_id / "result.json"
    if not meta_path.is_file():
        return jsonify({"detail": "Job not found"}), 404
    with open(meta_path, encoding="utf-8") as fh:
        data = json.load(fh)
    return jsonify(_sanitize_for_json(data))


@marketing_ramp_bp.route("/<job_id>/export", methods=["GET"])
def marketing_ramp_export(job_id: str):
    cached = _job_results.get(job_id)
    if not cached:
        loaded = load_marketing_ramp_report(job_id)
        if loaded:
            cached = {
                "metrics": loaded["metrics"],
                "rows": loaded.get("rows", []),
            }
            if loaded.get("consolidated"):
                cached["consolidated"] = loaded["consolidated"]
            _job_results[job_id] = cached
    if not cached:
        return jsonify({"detail": "Job not found"}), 404
    if not cached.get("rows"):
        return jsonify({"detail": "Row export unavailable; re-run analysis to regenerate rows"}), 404

    export_format = (request.args.get("format") or "xlsx").strip().lower()
    consolidated_block = cached.get("consolidated") or {}
    consolidated_metrics = consolidated_block.get("metrics")

    if export_format == "csv" or not consolidated_metrics:
        csv_text = rows_to_export_csv(cached["rows"])
        buf = BytesIO(csv_text.encode("utf-8"))
        buf.seek(0)
        return send_file(
            buf,
            mimetype="text/csv",
            as_attachment=True,
            download_name=f"marketing_ramp_{job_id}.csv",
        )

    try:
        consolidated_result = result_from_metrics_dict(consolidated_metrics)
        xlsx_bytes = build_unified_export_workbook(consolidated_result, cached["rows"])
    except (ValueError, KeyError) as exc:
        return jsonify({"detail": f"Export failed: {exc}"}), 500

    buf = BytesIO(xlsx_bytes)
    buf.seek(0)
    return send_file(
        buf,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        as_attachment=True,
        download_name=f"monthly_report_{job_id}.xlsx",
    )


@marketing_ramp_bp.route("/<job_id>", methods=["DELETE"])
def marketing_ramp_delete(job_id: str):
    _job_results.pop(job_id, None)
    delete_report_file(job_id)
    job_dir = MR_ROOT / job_id
    if job_dir.is_dir():
        shutil.rmtree(job_dir, ignore_errors=True)
    return jsonify({"detail": "Deleted"})
