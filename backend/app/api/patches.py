"""
REISift patch CSV generator API (Past patches workspace).
"""

from __future__ import annotations

import json
import math
import shutil
import uuid
import zipfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from flask import Blueprint, jsonify, request, send_file

from ..services.marketing_mapper import PatchPipelineResult, run_patch_pipeline, write_patch_exports
from ..utils.file_handler import UPLOAD_DIR

patches_bp = Blueprint("patches", __name__)

PATCHES_ROOT = UPLOAD_DIR / "patches"
PATCHES_ROOT.mkdir(parents=True, exist_ok=True)

# job_id -> {"out_dir": Path, "ready": bool}
_patch_job_meta: Dict[str, Dict[str, Any]] = {}


def _sanitize_for_json(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {k: _sanitize_for_json(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_sanitize_for_json(v) for v in obj]
    if isinstance(obj, float) and (math.isnan(obj) or math.isinf(obj)):
        return None
    return obj


def _df_sample_records(df, n: int = 5) -> List[dict]:
    if df is None or df.empty:
        return []
    chunk = df.head(n).copy()
    # JSON-safe: replace nan/NaT
    chunk = chunk.astype(object).where(chunk.notna(), None)
    return _sanitize_for_json(chunk.to_dict(orient="records"))


def _build_response_payload(job_id: str, result: PatchPipelineResult) -> Dict[str, Any]:
    metrics = {
        **result.crm_metrics,
        "cold_unmapped": result.cold_unmapped,
        "sms_unmapped": result.sms_unmapped,
        "crm_unmapped": result.crm_unmapped,
        "cold_input_counts": result.cold_input_counts,
        "cold_output_counts": result.cold_output_counts,
        "sms_input_counts": result.sms_input_counts,
        "sms_output_counts": result.sms_output_counts,
        "closings_rows": result.closings_rows,
    }
    samples = {
        "cold_calling": _df_sample_records(result.cold_df),
        "sms": _df_sample_records(result.sms_df),
        "salesforce_tags": _df_sample_records(result.sf_tags_df),
        "closings_tags": _df_sample_records(result.closings_tags_df)
        if result.closings_tags_df is not None
        else [],
    }
    return {"job_id": job_id, "metrics": metrics, "samples": samples}


@patches_bp.route("/upload", methods=["POST"])
def patches_upload():
    """
    Multipart: cold_csv, crm_csv, closings_xlsx (file), sms_files (0+ CSV, preserve basenames).
    """
    cold = request.files.get("cold_csv")
    crm = request.files.get("crm_csv")
    closings = request.files.get("closings_xlsx")
    sms_list = request.files.getlist("sms_files")

    if not cold or not cold.filename:
        return jsonify({"detail": "cold_csv is required"}), 400
    if not crm or not crm.filename:
        return jsonify({"detail": "crm_csv is required"}), 400
    if not closings or not closings.filename:
        return jsonify({"detail": "closings_xlsx is required"}), 400
    if not sms_list or not any(f.filename for f in sms_list):
        return jsonify({"detail": "At least one sms_files CSV is required"}), 400

    job_id = str(uuid.uuid4())
    job_dir = PATCHES_ROOT / job_id
    raw_dir = job_dir / "raw"
    out_dir = job_dir / "out"
    raw_dir.mkdir(parents=True, exist_ok=True)
    out_dir.mkdir(parents=True, exist_ok=True)

    cold_path = raw_dir / "cold_calling.csv"
    cold.save(str(cold_path))

    crm_path = raw_dir / "crm_updates.csv"
    crm.save(str(crm_path))

    clos_name = Path(closings.filename.replace("\\", "/")).name
    if not clos_name.lower().endswith((".xlsx", ".xls")):
        shutil.rmtree(job_dir, ignore_errors=True)
        return jsonify({"detail": "closings_xlsx must be .xlsx or .xls"}), 400
    clos_path = raw_dir / clos_name
    closings.save(str(clos_path))

    sms_entries: List[Tuple[str, str]] = []
    for f in sms_list:
        if not f.filename:
            continue
        orig = Path(f.filename.replace("\\", "/")).name
        if not orig.lower().endswith(".csv"):
            continue
        dest = raw_dir / orig
        counter = 1
        stem, suf = dest.stem, dest.suffix
        while dest.exists():
            dest = raw_dir / f"{stem}_{counter}{suf}"
            counter += 1
        f.save(str(dest))
        sms_entries.append((orig, str(dest)))

    if not sms_entries:
        shutil.rmtree(job_dir, ignore_errors=True)
        return jsonify({"detail": "No valid SMS CSV files after filtering"}), 400

    try:
        result = run_patch_pipeline(
            str(cold_path),
            sms_entries,
            str(crm_path),
            str(clos_path),
        )
    except Exception as exc:
        shutil.rmtree(job_dir, ignore_errors=True)
        return jsonify({"detail": str(exc)}), 400

    meta_path = job_dir / "meta.json"
    payload = _build_response_payload(job_id, result)
    with open(meta_path, "w", encoding="utf-8") as fp:
        json.dump(_sanitize_for_json(payload), fp, indent=2)

    # Persist pipeline result for export (pickle-free: re-run export from stored CSVs is heavy;
    # store parquet optional — instead keep in memory for job_id)
    _patch_job_meta[job_id] = {"result": result, "out_dir": str(out_dir), "ready": False}

    return jsonify(payload)


@patches_bp.route("/<job_id>/export", methods=["GET"])
def patches_export(job_id: str):
    file_kind = (request.args.get("file") or "all").lower()
    meta = _patch_job_meta.get(job_id)
    if not meta:
        return jsonify({"detail": "Unknown or expired job_id"}), 404

    result: PatchPipelineResult = meta["result"]
    out_dir = Path(meta["out_dir"])
    allow_raw = request.args.get("allow_unmapped", "false").lower() in ("1", "true", "yes")

    try:
        paths = write_patch_exports(result, str(out_dir), allow_unmapped=allow_raw)
    except ValueError as exc:
        return jsonify({"detail": str(exc)}), 400

    meta["ready"] = True

    if file_kind == "all":
        zip_path = out_dir / f"patches_{job_id}.zip"
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for p in paths:
                zp = Path(p)
                zf.write(zp, arcname=zp.name)
        return send_file(
            str(zip_path),
            as_attachment=True,
            download_name=f"reisift_import_{job_id}.zip",
            mimetype="application/zip",
        )

    name_map = {
        "property": "property_status_updates.csv",
        "phone": "phone_status_tags_updates.csv",
        "sf": "salesforce_status_tags.csv",
        "closings": "closings_status_tags.csv",
    }
    if file_kind not in name_map:
        return jsonify({"detail": "Invalid file= parameter"}), 400

    target = out_dir / name_map[file_kind]
    if not target.exists():
        return jsonify({"detail": f"File not generated: {name_map[file_kind]}"}), 404

    return send_file(
        str(target),
        as_attachment=True,
        download_name=name_map[file_kind],
        mimetype="text/csv",
    )


@patches_bp.route("/<job_id>", methods=["DELETE"])
def patches_delete(job_id: str):
    job_dir = PATCHES_ROOT / job_id
    if job_dir.exists():
        shutil.rmtree(job_dir, ignore_errors=True)
    _patch_job_meta.pop(job_id, None)
    return jsonify({"detail": "deleted", "job_id": job_id})

