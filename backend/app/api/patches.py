"""
REISift patch CSV generator API (Past patches workspace).
"""

from __future__ import annotations

import json
import math
import shutil
import uuid
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from flask import Blueprint, jsonify, request, send_file

from ..services.marketing_mapper import PatchPipelineResult, run_patch_pipeline, write_patch_exports
from ..services.monthly_ingestion import run_monthly_ingestion, validate_report_month, write_monthly_exports
from ..utils.file_handler import UPLOAD_DIR

patches_bp = Blueprint("patches", __name__)

PATCHES_ROOT = UPLOAD_DIR / "patches"
PATCHES_ROOT.mkdir(parents=True, exist_ok=True)

# job_id -> {"out_dir": Path, "ready": bool}
_patch_job_meta: Dict[str, Dict[str, Any]] = {}
_monthly_workers = ThreadPoolExecutor(max_workers=2, thread_name_prefix="monthly-ingestion")
_monthly_jobs: Dict[str, Any] = {}


def _save_monthly_state(path: Path, payload: dict):
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(_sanitize_for_json(payload), indent=2), encoding="utf-8")
    temporary.replace(path)


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


@patches_bp.route("/monthly", methods=["POST"])
def patches_monthly():
    """Month-scoped calling/SMS imports and independent Salesforce milestone imports."""
    month = request.form.get("report_month", "").strip()
    try:
        validate_report_month(month)
    except ValueError as exc:
        return jsonify({"detail": str(exc)}), 400
    roles = ("cold_csv", "qualified_leads", "opportunities", "transactions")
    uploads = {role: request.files.get(role) for role in roles}
    sf_present = [bool(uploads[role] and uploads[role].filename) for role in roles[1:]]
    sms = [f for f in request.files.getlist("sms_files") if f.filename]
    if not any(sf_present) and not sms and not (uploads["cold_csv"] and uploads["cold_csv"].filename):
        return jsonify({"detail": "Upload at least one calling, SMS, or Salesforce report"}), 400
    for role, upload in [*uploads.items(), *(("sms_files", f) for f in sms)]:
        if not upload or not upload.filename:
            continue
        allowed = (".csv",) if role in ("cold_csv", "sms_files") else (".csv", ".xlsx")
        if Path(upload.filename).suffix.lower() not in allowed:
            return jsonify({"detail": f"{role} must be {' or '.join(allowed)}"}), 400
    job_id = str(uuid.uuid4())
    job_dir = PATCHES_ROOT / job_id
    raw_dir, out_dir = job_dir / "raw", job_dir / "out"
    raw_dir.mkdir(parents=True)

    def save(role, upload):
        if not upload or not upload.filename:
            return None
        # A role directory avoids both collisions and filename-based traversal.
        directory = raw_dir / role
        directory.mkdir()
        name = Path(upload.filename.replace("\\", "/")).name
        destination = directory / name
        upload.save(str(destination))
        return str(destination)

    try:
        paths = {role: save(role, upload) for role, upload in uploads.items()}
        entries = [(Path(f.filename.replace("\\", "/")).name, save(f"sms_{i}", f)) for i, f in enumerate(sms)]
        def process():
            frames, result = run_monthly_ingestion(
                month, cold_path=paths["cold_csv"], sms_entries=entries,
                qualified_leads=paths["qualified_leads"], opportunities=paths["opportunities"],
                transactions=paths["transactions"],
            )
            result = _sanitize_for_json({"job_id": job_id, **result})
            write_monthly_exports(frames, result, out_dir)
            _save_monthly_state(job_dir / "meta.json", result)
            return result

        if request.form.get("background") == "true":
            state_path = job_dir / "state.json"
            state = {"job_id": job_id, "status": "processing", "report_month": month}
            _save_monthly_state(state_path, state)

            def worker():
                try:
                    process()
                    _save_monthly_state(state_path, {**state, "status": "completed"})
                except Exception as exc:
                    _save_monthly_state(state_path, {**state, "status": "failed", "detail": str(exc)})

            _monthly_jobs[job_id] = _monthly_workers.submit(worker)
            return jsonify(state), 202
        payload = process()
    except Exception as exc:
        shutil.rmtree(job_dir, ignore_errors=True)
        return jsonify({"detail": str(exc)}), 400
    return jsonify(payload)


@patches_bp.route("/monthly/<uuid:job_id>", methods=["GET"])
def patches_monthly_status(job_id):
    job_id = str(job_id)
    job_dir = PATCHES_ROOT / job_id
    if (job_dir / "meta.json").is_file():
        payload = json.loads((job_dir / "meta.json").read_text(encoding="utf-8"))
        return jsonify({"status": "completed", **payload})
    state_path = job_dir / "state.json"
    if not state_path.is_file():
        return jsonify({"detail": "Unknown monthly job"}), 404
    state = json.loads(state_path.read_text(encoding="utf-8"))
    if state["status"] == "processing" and job_id not in _monthly_jobs:
        return jsonify({**state, "status": "failed", "detail": "Processing was interrupted by a server restart. Please run the month again."})
    return jsonify(state)


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

    clos_path: str | None = None
    if closings and closings.filename:
        clos_name = Path(closings.filename.replace("\\", "/")).name
        if not clos_name.lower().endswith((".xlsx", ".xls")):
            shutil.rmtree(job_dir, ignore_errors=True)
            return jsonify({"detail": "closings_xlsx must be .xlsx or .xls"}), 400
        clos_dest = raw_dir / clos_name
        closings.save(str(clos_dest))
        clos_path = str(clos_dest)

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
            clos_path,
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
    # Monthly runs use persisted reviewed exports; no in-memory job is required.
    try:
        if str(uuid.UUID(job_id)) != job_id:
            raise ValueError()
    except ValueError:
        return jsonify({"detail": "Invalid job_id"}), 400
    disk_meta = PATCHES_ROOT / job_id / "meta.json"
    if disk_meta.is_file():
        saved = json.loads(disk_meta.read_text(encoding="utf-8"))
        if "monthly" in saved:
            out = disk_meta.parent / "out"
            names = {"property": "property_status_updates.csv", "phone": "phone_status_tags_updates.csv",
                     "sf": "salesforce_status_tags.csv", "marketing": "marketing_activity_tags.csv",
                     "review": "ingestion_review.csv", "events": "salesforce_events.csv"}
            if file_kind == "all":
                archive = out / "monthly_import.zip"
                with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as zf:
                    for path in sorted(out.iterdir()):
                        if path.is_file() and path.suffix in (".csv", ".json", ".txt"):
                            zf.write(path, arcname=path.name)
                return send_file(str(archive), as_attachment=True,
                                 download_name=f"reisift_import_{saved['monthly']['report_month']}.zip", mimetype="application/zip")
            if file_kind not in names:
                return jsonify({"detail": "Invalid file= parameter"}), 400
            target = out / names[file_kind]
            if not target.is_file():
                return jsonify({"detail": "This source was not included in the run"}), 404
            return send_file(str(target), as_attachment=True, download_name=target.name, mimetype="text/csv")
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
    try:
        if str(uuid.UUID(job_id)) != job_id:
            raise ValueError()
    except ValueError:
        return jsonify({"detail": "Invalid job_id"}), 400
    running = _monthly_jobs.get(job_id)
    if running and not running.done():
        return jsonify({"detail": "This monthly run is still processing"}), 409
    job_dir = PATCHES_ROOT / job_id
    if job_dir.exists():
        shutil.rmtree(job_dir, ignore_errors=True)
    _patch_job_meta.pop(job_id, None)
    return jsonify({"detail": "deleted", "job_id": job_id})

