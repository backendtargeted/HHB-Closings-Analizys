"""
Qualified leads consolidation API (Salesforce Total Qualified Leads export).
"""

from __future__ import annotations

import json
import math
import shutil
import uuid
from io import BytesIO
from pathlib import Path
from typing import Any, Dict

from flask import Blueprint, jsonify, request, send_file

from ..services.qualified_leads import analyze_file, parse_ymd_param, rows_to_export_csv
from ..utils.file_handler import UPLOAD_DIR

qualified_leads_bp = Blueprint("qualified_leads", __name__)

QL_ROOT = UPLOAD_DIR / "qualified_leads"
QL_ROOT.mkdir(parents=True, exist_ok=True)

_job_results: Dict[str, Dict[str, Any]] = {}


def _sanitize_for_json(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {k: _sanitize_for_json(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_sanitize_for_json(v) for v in obj]
    if isinstance(obj, float) and (math.isnan(obj) or math.isinf(obj)):
        return None
    return obj


@qualified_leads_bp.route("/analyze", methods=["POST"])
def qualified_leads_analyze():
    """
    Multipart: qualified_leads_file (csv/xlsx).
    Form fields:
      - use_full_file_span: true|false (default false)
      - start_date, end_date: YYYY-MM-DD (required unless use_full_file_span=true)
    """
    upload = request.files.get("qualified_leads_file")
    if not upload or not upload.filename:
        return jsonify({"detail": "qualified_leads_file is required"}), 400

    use_full = (request.form.get("use_full_file_span") or "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )
    start_raw = (request.form.get("start_date") or "").strip()
    end_raw = (request.form.get("end_date") or "").strip()

    job_id = str(uuid.uuid4())
    job_dir = QL_ROOT / job_id
    job_dir.mkdir(parents=True, exist_ok=True)

    safe_name = Path(upload.filename.replace("\\", "/")).name
    suffix = Path(safe_name).suffix.lower()
    if suffix not in (".csv", ".xlsx", ".xls"):
        shutil.rmtree(job_dir, ignore_errors=True)
        return jsonify({"detail": "qualified_leads_file must be .csv or .xlsx"}), 400

    file_path = job_dir / safe_name
    upload.save(str(file_path))

    try:
        if use_full:
            result = analyze_file(str(file_path), use_full_file_span=True)
        else:
            start_date = parse_ymd_param(start_raw, "start_date")
            end_date = parse_ymd_param(end_raw, "end_date")
            result = analyze_file(
                str(file_path),
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

    payload = {
        "job_id": job_id,
        "metrics": result.to_dict(),
        "use_full_file_span": use_full,
    }
    _job_results[job_id] = {
        "metrics": result.to_dict(),
        "rows": result.rows,
        "file_path": str(file_path),
    }

    meta_path = job_dir / "result.json"
    with open(meta_path, "w", encoding="utf-8") as fh:
        json.dump(_sanitize_for_json(payload), fh, indent=2)

    return jsonify(_sanitize_for_json(payload))


@qualified_leads_bp.route("/<job_id>", methods=["GET"])
def qualified_leads_get(job_id: str):
    cached = _job_results.get(job_id)
    if cached:
        return jsonify(
            _sanitize_for_json(
                {"job_id": job_id, "metrics": cached["metrics"]}
            )
        )
    meta_path = QL_ROOT / job_id / "result.json"
    if not meta_path.is_file():
        return jsonify({"detail": "Job not found"}), 404
    with open(meta_path, encoding="utf-8") as fh:
        data = json.load(fh)
    return jsonify(_sanitize_for_json(data))


@qualified_leads_bp.route("/<job_id>/export", methods=["GET"])
def qualified_leads_export(job_id: str):
    cached = _job_results.get(job_id)
    if not cached:
        meta_path = QL_ROOT / job_id / "result.json"
        if not meta_path.is_file():
            return jsonify({"detail": "Job not found"}), 404
        return jsonify({"detail": "Row export unavailable after server restart; re-run analysis"}), 404

    from ..services.qualified_leads import QualifiedLeadsResult

    result = QualifiedLeadsResult(
        rows_ingested=cached["metrics"]["rows_ingested"],
        qualified_total_file=cached["metrics"]["qualified_total_file"],
        posted_in_window=cached["metrics"]["posted_in_window"],
        posted_excluded_bad_date=cached["metrics"]["posted_excluded_bad_date"],
        posted_outside_window=cached["metrics"]["posted_outside_window"],
        date_window_start=cached["metrics"]["date_window_start"],
        date_window_end=cached["metrics"]["date_window_end"],
        create_date_min=cached["metrics"].get("create_date_min"),
        create_date_max=cached["metrics"].get("create_date_max"),
        channel_counts=cached["metrics"]["channel_counts"],
        channel_shares_pct=cached["metrics"]["channel_shares_pct"],
        in_scope_subtotal=cached["metrics"]["in_scope_subtotal"],
        in_scope_share_pct=cached["metrics"]["in_scope_share_pct"],
        lead_source_unmapped=cached["metrics"]["lead_source_unmapped"],
        lead_source_blank=cached["metrics"]["lead_source_blank"],
        rows=cached["rows"],
    )
    csv_text = rows_to_export_csv(result)
    buf = BytesIO(csv_text.encode("utf-8"))
    buf.seek(0)
    return send_file(
        buf,
        mimetype="text/csv",
        as_attachment=True,
        download_name=f"qualified_leads_{job_id}.csv",
    )


@qualified_leads_bp.route("/<job_id>", methods=["DELETE"])
def qualified_leads_delete(job_id: str):
    _job_results.pop(job_id, None)
    job_dir = QL_ROOT / job_id
    if job_dir.is_dir():
        shutil.rmtree(job_dir, ignore_errors=True)
        return jsonify({"detail": "Deleted"})
    return jsonify({"detail": "Job not found"}), 404
