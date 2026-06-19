"""
Gate 4 — Web Leads report API.
"""

from __future__ import annotations

import json
import math
import multiprocessing
import shutil
import threading
import uuid
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from typing import Any, Dict, Optional

from flask import Blueprint, jsonify, request, send_file

from ..services.qualified_leads import parse_ymd_param
from ..services.report_store import (
    REPORTS_DIR,
    delete_report_file,
    load_web_leads_report,
    save_web_leads_report,
)
from ..services.resumable_uploads import resolve_trusted_final_path
from ..services.web_leads import (
    analyze,
    build_export_workbook,
    result_from_metrics_dict,
)
from ..utils.file_handler import UPLOAD_DIR

web_leads_bp = Blueprint("web_leads", __name__)

WL_ROOT = UPLOAD_DIR / "web_leads"
WL_ROOT.mkdir(parents=True, exist_ok=True)

_job_results: Dict[str, Dict[str, Any]] = {}
_jobs: Dict[str, Dict[str, Any]] = {}


def _sanitize_for_json(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {k: _sanitize_for_json(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_sanitize_for_json(v) for v in obj]
    if isinstance(obj, float) and (math.isnan(obj) or math.isinf(obj)):
        return None
    return obj


def _progress_path(job_dir: Path) -> Path:
    return job_dir / "progress.json"


def _write_job_progress(job_dir: Path, payload: Dict[str, Any]) -> None:
    job_dir.mkdir(parents=True, exist_ok=True)
    with open(_progress_path(job_dir), "w", encoding="utf-8") as fh:
        json.dump(_sanitize_for_json(payload), fh)


def _read_job_progress(job_dir: Path) -> Dict[str, Any] | None:
    path = _progress_path(job_dir)
    if not path.is_file():
        return None
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def _analyze_in_subprocess(
    job_id: str,
    reisift_path: str,
    ql_path: Optional[str],
    use_full: bool,
    start_raw: str,
    end_raw: str,
    job_dir_str: str,
) -> None:
    job_dir = Path(job_dir_str)

    def on_progress(progress: int, message: str) -> None:
        _write_job_progress(
            job_dir,
            {
                "job_id": job_id,
                "status": "running",
                "progress": progress,
                "message": message,
            },
        )

    try:
        _write_job_progress(
            job_dir,
            {
                "job_id": job_id,
                "status": "running",
                "progress": 10,
                "message": "Starting web leads analysis…",
            },
        )
        if use_full:
            result = analyze(
                reisift_path,
                ql_path,
                use_full_file_span=True,
                on_progress=on_progress,
            )
        else:
            start_date = parse_ymd_param(start_raw, "start_date")
            end_date = parse_ymd_param(end_raw, "end_date")
            result = analyze(
                reisift_path,
                ql_path,
                use_full_file_span=False,
                start_date=start_date,
                end_date=end_date,
                on_progress=on_progress,
            )

        metrics = result.to_api_dict()
        created_at = datetime.now(timezone.utc).isoformat()
        payload = {
            "job_id": job_id,
            "status": "completed",
            "metrics": metrics,
            "warnings": metrics.get("warnings", []),
            "created_at": created_at,
        }
        save_web_leads_report(job_id, metrics=metrics, created_at=created_at)
        with open(job_dir / "result.json", "w", encoding="utf-8") as fh:
            json.dump(_sanitize_for_json(payload), fh, indent=2)
        _write_job_progress(
            job_dir,
            {
                "job_id": job_id,
                "status": "completed",
                "progress": 100,
                "message": "Analysis complete",
                "created_at": created_at,
            },
        )
    except ValueError as exc:
        _write_job_progress(
            job_dir,
            {"job_id": job_id, "status": "failed", "progress": 0, "message": str(exc)},
        )
    except Exception as exc:
        _write_job_progress(
            job_dir,
            {
                "job_id": job_id,
                "status": "failed",
                "progress": 0,
                "message": f"Analysis failed: {exc}",
            },
        )


def _sync_job_from_disk(job_id: str) -> None:
    job_dir = WL_ROOT / job_id
    progress = _read_job_progress(job_dir)
    if not progress:
        return
    status = progress.get("status")
    if status == "running":
        _jobs[job_id] = {
            "job_id": job_id,
            "status": "running",
            "progress": progress.get("progress", 0),
            "message": progress.get("message", ""),
            "metrics": None,
            "warnings": [],
            "created_at": progress.get("created_at"),
        }
        return
    if status == "failed":
        _jobs[job_id] = {
            "job_id": job_id,
            "status": "failed",
            "progress": 0,
            "message": progress.get("message", "Analysis failed"),
            "metrics": None,
            "warnings": [],
            "created_at": None,
        }
        return
    if status == "completed":
        meta_path = job_dir / "result.json"
        if meta_path.is_file():
            with open(meta_path, encoding="utf-8") as fh:
                data = json.load(fh)
            metrics = data.get("metrics")
            created_at = data.get("created_at")
            if metrics:
                _job_results[job_id] = {"metrics": metrics, "created_at": created_at}
                _jobs[job_id] = {
                    "job_id": job_id,
                    "status": "completed",
                    "progress": 100,
                    "message": "Analysis complete",
                    "metrics": metrics,
                    "warnings": metrics.get("warnings", []),
                    "created_at": created_at,
                }


def _job_snapshot(job_id: str) -> Dict[str, Any] | None:
    live = _jobs.get(job_id)
    if live:
        if live.get("status") == "running":
            progress = _read_job_progress(WL_ROOT / job_id)
            if progress:
                live = {**live, **progress}
        return live
    _sync_job_from_disk(job_id)
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


def load_web_leads_from_disk() -> None:
    wl_dir = REPORTS_DIR / "web_leads"
    if not wl_dir.is_dir():
        return
    for path in wl_dir.glob("*.json"):
        try:
            job_id = path.stem
            loaded = load_web_leads_report(job_id)
            if loaded:
                _job_results[job_id] = {
                    "metrics": loaded["metrics"],
                    "created_at": loaded.get("created_at"),
                }
        except (json.JSONDecodeError, OSError):
            continue


def _watch_analysis_process(job_id: str, proc: multiprocessing.Process) -> None:
    proc.join()
    _sync_job_from_disk(job_id)
    live = _jobs.get(job_id, {})
    if live.get("status") == "running":
        _jobs[job_id].update(
            {
                "status": "failed",
                "progress": 0,
                "message": "Analysis process exited unexpectedly",
            }
        )


def _run_web_leads_job(
    job_id: str,
    reisift_path: str,
    ql_path: Optional[str],
    use_full: bool,
    start_raw: str,
    end_raw: str,
) -> None:
    job_dir = WL_ROOT / job_id
    job_dir.mkdir(parents=True, exist_ok=True)
    _jobs[job_id]["status"] = "running"
    _jobs[job_id]["progress"] = 10
    _jobs[job_id]["message"] = "Starting analysis…"
    _write_job_progress(
        job_dir,
        {
            "job_id": job_id,
            "status": "running",
            "progress": 10,
            "message": "Starting analysis…",
        },
    )

    proc = multiprocessing.Process(
        target=_analyze_in_subprocess,
        args=(job_id, reisift_path, ql_path, use_full, start_raw, end_raw, str(job_dir)),
        daemon=True,
    )
    proc.start()
    threading.Thread(
        target=_watch_analysis_process, args=(job_id, proc), daemon=True
    ).start()


def _start_web_leads_job(
    reisift_path: str,
    ql_path: Optional[str],
    use_full: bool,
    start_raw: str,
    end_raw: str,
    job_id: str | None = None,
) -> tuple[dict[str, Any], int]:
    job_id = job_id or str(uuid.uuid4())
    job_dir = WL_ROOT / job_id
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
        target=_run_web_leads_job,
        args=(job_id, reisift_path, ql_path, use_full, start_raw, end_raw),
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


@web_leads_bp.route("/analyze", methods=["POST"])
def web_leads_analyze():
    use_full = request.form.get("use_full_file_span", "1").strip().lower() in (
        "1",
        "true",
        "yes",
    )
    start_raw = (request.form.get("start_date") or "").strip()
    end_raw = (request.form.get("end_date") or "").strip()

    if request.is_json:
        data = request.get_json() or {}
        use_full = data.get("use_full_file_span", True)
        if isinstance(use_full, str):
            use_full = use_full.strip().lower() in ("1", "true", "yes")
        start_raw = (data.get("start_date") or "").strip()
        end_raw = (data.get("end_date") or "").strip()
        reisift_raw = (data.get("reisift_path") or "").strip()
        ql_raw = (data.get("qualified_leads_path") or "").strip() or None
        if not reisift_raw:
            return jsonify({"detail": "reisift_path is required"}), 400
        if not use_full and ql_raw:
            try:
                parse_ymd_param(start_raw, "start_date")
                parse_ymd_param(end_raw, "end_date")
            except ValueError as exc:
                return jsonify({"detail": str(exc)}), 400
        try:
            reisift_path = str(resolve_trusted_final_path(reisift_raw))
            ql_path = (
                str(resolve_trusted_final_path(ql_raw)) if ql_raw else None
            )
        except ValueError as exc:
            return jsonify({"detail": str(exc)}), 400
        payload, status = _start_web_leads_job(
            reisift_path, ql_path, use_full, start_raw, end_raw
        )
        return jsonify(_sanitize_for_json(payload)), status

    reisift = request.files.get("reisift_file")
    ql = request.files.get("qualified_leads_file")
    if not reisift or not reisift.filename:
        return jsonify({"detail": "reisift_file is required"}), 400

    if not use_full and ql and ql.filename:
        try:
            parse_ymd_param(start_raw, "start_date")
            parse_ymd_param(end_raw, "end_date")
        except ValueError as exc:
            return jsonify({"detail": str(exc)}), 400

    job_id = str(uuid.uuid4())
    job_dir = WL_ROOT / job_id
    job_dir.mkdir(parents=True, exist_ok=True)

    reisift_name = Path(reisift.filename.replace("\\", "/")).name
    reisift_path = job_dir / reisift_name
    reisift.save(str(reisift_path))
    ql_path: Optional[str] = None
    if ql and ql.filename:
        ql_name = Path(ql.filename.replace("\\", "/")).name
        ql_path_obj = job_dir / ql_name
        ql.save(str(ql_path_obj))
        ql_path = str(ql_path_obj)

    payload, status = _start_web_leads_job(
        str(reisift_path),
        ql_path,
        use_full,
        start_raw,
        end_raw,
        job_id=job_id,
    )
    return jsonify(_sanitize_for_json(payload)), status


@web_leads_bp.route("/<job_id>/status", methods=["GET"])
def web_leads_status(job_id: str):
    _sync_job_from_disk(job_id)
    snap = _job_snapshot(job_id)
    if not snap:
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


@web_leads_bp.route("/<job_id>", methods=["GET"])
def web_leads_get(job_id: str):
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

    loaded = load_web_leads_report(job_id)
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
                    "created_at": loaded.get("created_at"),
                }
            )
        )
    return jsonify({"detail": "Job not found"}), 404


@web_leads_bp.route("/<job_id>/export", methods=["GET"])
def web_leads_export(job_id: str):
    cached = _job_results.get(job_id)
    if not cached:
        loaded = load_web_leads_report(job_id)
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
    return send_file(
        buf,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        as_attachment=True,
        download_name=f"web_leads_{job_id}.xlsx",
    )


@web_leads_bp.route("/<job_id>", methods=["DELETE"])
def web_leads_delete(job_id: str):
    _job_results.pop(job_id, None)
    _jobs.pop(job_id, None)
    delete_report_file(job_id)
    job_dir = WL_ROOT / job_id
    if job_dir.is_dir():
        shutil.rmtree(job_dir, ignore_errors=True)
    return jsonify({"detail": "Deleted"})
