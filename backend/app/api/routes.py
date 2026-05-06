"""
API routes for the contact attribution analysis (Flask)
"""

import json
import math
import uuid
import threading
from datetime import datetime, timezone, date
from typing import Dict, List, Any, Optional
from flask import Blueprint, request, jsonify, send_file
import pandas as pd
import os
from pathlib import Path

from ..services.analysis import perform_analysis
from ..services import object_storage
from ..utils.file_handler import save_uploaded_file, delete_file, validate_excel_file, validate_csv_file, EXPORT_DIR
from .models import (
    AnalysisResponse,
    AnalysisCompleteResponse,
    AnalysisResult,
    SummaryStats,
    ComparisonRequest,
    ComparisonResponse,
)

api_bp = Blueprint("api", __name__)


@api_bp.route("/health", methods=["GET", "HEAD"])
def api_health():
    """Same-origin health under /api (useful when debugging proxy routing)."""
    if request.method == "HEAD":
        return "", 200
    return jsonify({"status": "healthy"})


# Reports directory (persisted via Docker volume)
REPORTS_DIR = Path(os.environ.get("REPORTS_DIR", "/app/reports"))

# In-memory storage for analysis jobs; populated from disk at startup
analysis_jobs: Dict[str, Dict] = {}
analysis_results: Dict[str, Dict] = {}


def _ensure_reports_dir() -> None:
    """Ensure reports directory exists."""
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)


def _sanitize_for_json(obj: Any) -> Any:
    """Convert nan/inf to None so JSON serialization works."""
    if isinstance(obj, dict):
        return {k: _sanitize_for_json(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_sanitize_for_json(v) for v in obj]
    if isinstance(obj, float) and (math.isnan(obj) or math.isinf(obj)):
        return None
    return obj


def save_report_to_disk(job_id: str, result: Dict, created_at: str) -> None:
    """Persist analysis result to reports/{job_id}.json or reports/snapshots/{as_of}/{job_id}.json."""
    _ensure_reports_dir()
    as_of = result.get("as_of")
    if as_of:
        snap_dir = REPORTS_DIR / "snapshots" / str(as_of)
        snap_dir.mkdir(parents=True, exist_ok=True)
        path = snap_dir / f"{job_id}.json"
    else:
        path = REPORTS_DIR / f"{job_id}.json"
    payload = {
        "results": result.get("results", []),
        "stats": result.get("stats", {}),
        "matched_count": result.get("matched_count", 0),
        "total_deals": result.get("total_deals", 0),
        "created_at": created_at,
        "as_of": as_of,
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(_sanitize_for_json(payload), f, indent=2)


def load_reports_from_disk() -> None:
    """Load all persisted reports from REPORTS_DIR (including snapshots/*/) into memory."""
    _ensure_reports_dir()
    for path in REPORTS_DIR.rglob("*.json"):
        try:
            job_id = path.stem
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            created_at = data.get("created_at", datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).isoformat())
            as_of = data.get("as_of")
            analysis_results[job_id] = {
                "results": data.get("results", []),
                "stats": data.get("stats", {}),
                "matched_count": data.get("matched_count", 0),
                "total_deals": data.get("total_deals", 0),
                "as_of": as_of,
            }
            analysis_jobs[job_id] = {
                "status": "completed",
                "progress": 100,
                "message": "Analysis complete",
                "created_at": created_at,
                "as_of": as_of,
            }
        except (json.JSONDecodeError, OSError) as e:
            # Skip broken files
            continue


def generate_job_id() -> str:
    """Generate a unique job ID."""
    return str(uuid.uuid4())


def run_analysis_sync(
    job_id: str,
    closings_path: Optional[str],
    csv_path: Optional[str],
    as_of: Optional[str] = None,
    closings_object_key: Optional[str] = None,
    csv_object_key: Optional[str] = None,
):
    """Run analysis in a background thread and update job status."""
    temp_paths: List[str] = []
    keys_to_maybe_delete: List[str] = []
    closings_local = closings_path
    csv_local = csv_path
    try:
        analysis_jobs[job_id]["status"] = "running"

        if csv_object_key:
            csv_local = object_storage.download_object_to_tempfile(csv_object_key)
            temp_paths.append(csv_local)
            keys_to_maybe_delete.append(csv_object_key)
        if closings_object_key:
            closings_local = object_storage.download_object_to_tempfile(closings_object_key)
            temp_paths.append(closings_local)
            keys_to_maybe_delete.append(closings_object_key)

        if not csv_local:
            raise ValueError("Internal error: missing CSV path after object download")

        def progress_callback(message: str, progress: int):
            analysis_jobs[job_id]["progress"] = progress
            analysis_jobs[job_id]["message"] = message

        result = perform_analysis(closings_local, csv_local, progress_callback, as_of_date=as_of)

        analysis_results[job_id] = result
        created_at = datetime.now(timezone.utc).isoformat()
        analysis_jobs[job_id]["status"] = "completed"
        analysis_jobs[job_id]["progress"] = 100
        analysis_jobs[job_id]["message"] = "Analysis complete"
        analysis_jobs[job_id]["created_at"] = created_at
        save_report_to_disk(job_id, result, created_at)

        if object_storage.delete_after_analysis_enabled():
            for key in keys_to_maybe_delete:
                try:
                    object_storage.delete_object(key)
                except Exception:
                    pass

    except Exception as e:
        analysis_jobs[job_id]["status"] = "failed"
        analysis_jobs[job_id]["message"] = str(e)
    finally:
        for p in temp_paths:
            delete_file(p)


@api_bp.route("/upload", methods=["POST"])
def upload_files():
    """
    Upload files for analysis.
    Core path only requires contact history CSV. Optional closings workbook support is legacy-only.
    """
    try:
        closings_file = request.files.get("closings_file") or request.files.get("excel_file")
        csv_file = request.files.get("csv_file")

        if not csv_file or not csv_file.filename:
            return jsonify({"detail": "Contact history CSV file is required"}), 400

        closings_path: Optional[str] = None
        if closings_file and closings_file.filename:
            closings_path = save_uploaded_file(closings_file, "closings")
        csv_path = save_uploaded_file(csv_file, "csv")

        if closings_path and not validate_excel_file(closings_path):
            delete_file(closings_path)
            delete_file(csv_path)
            return jsonify({"detail": "Invalid closings workbook (optional/deprecated path)"}), 400

        if not validate_csv_file(csv_path):
            if closings_path:
                delete_file(closings_path)
            delete_file(csv_path)
            return jsonify({"detail": "Invalid contact history CSV file"}), 400

        return jsonify({
            "closings_path": closings_path,
            "excel_path": closings_path,  # Backward-compatible legacy key
            "csv_path": csv_path,
            "message": "Files uploaded successfully",
        })
    except Exception as e:
        return jsonify({"detail": str(e)}), 500


@api_bp.route("/upload/capabilities", methods=["GET"])
def upload_capabilities():
    """Whether presigned direct-to-storage uploads are available."""
    return jsonify({"presigned_upload": object_storage.is_object_storage_configured()})


@api_bp.route("/upload/presign", methods=["POST"])
def upload_presign():
    """
    Mint a presigned PUT URL for browser upload to S3-compatible storage (MinIO).
    JSON body: { "kind": "csv" | "closings", "filename": "..." }
    """
    if not object_storage.is_object_storage_configured():
        return jsonify(
            {"detail": "Object storage is not configured. Set S3_ENDPOINT, S3_PUBLIC_ENDPOINT, S3_BUCKET, S3_ACCESS_KEY, S3_SECRET_KEY."}
        ), 503
    data = request.get_json() or {}
    kind = data.get("kind")
    filename = str(data.get("filename") or "")
    if kind not in ("csv", "closings"):
        return jsonify({"detail": "kind must be csv or closings"}), 400
    try:
        object_key = object_storage.build_object_key(str(kind), filename)
    except ValueError as exc:
        return jsonify({"detail": str(exc)}), 400
    content_type = object_storage.content_type_for_upload(str(kind), filename)
    try:
        url, headers, expires_in = object_storage.generate_presigned_put(object_key, content_type)
    except Exception as exc:
        return jsonify({"detail": f"Could not create upload URL: {exc}"}), 500
    return jsonify(
        {
            "object_key": object_key,
            "upload": {"url": url, "method": "PUT", "headers": headers},
            "expires_in": expires_in,
        }
    )


@api_bp.route("/analyze", methods=["POST"])
def start_analysis():
    """
    Start an analysis job.
    JSON: provide exactly one of csv_path or csv_object_key; optional closings_path or closings_object_key (not both); optional as_of.
    """
    data = request.get_json() or {}
    closings_path = data.get("closings_path") or data.get("excel_path")
    csv_path = data.get("csv_path")
    csv_object_key = data.get("csv_object_key")
    closings_object_key = data.get("closings_object_key")
    as_of_raw = data.get("as_of")

    has_csv_path = bool(csv_path and str(csv_path).strip())
    has_csv_key = bool(csv_object_key and str(csv_object_key).strip())
    if has_csv_path == has_csv_key:
        return jsonify(
            {"detail": "Provide exactly one of csv_path (multipart upload) or csv_object_key (presigned upload)"}
        ), 400

    has_closings_path = bool(closings_path and str(closings_path).strip())
    has_closings_key = bool(closings_object_key and str(closings_object_key).strip())
    if has_closings_path and has_closings_key:
        return jsonify(
            {"detail": "Provide at most one of closings_path and closings_object_key"}
        ), 400

    as_of: Optional[str] = None
    if as_of_raw is not None and str(as_of_raw).strip() != "":
        try:
            date.fromisoformat(str(as_of_raw).strip())
            as_of = str(as_of_raw).strip()
        except ValueError:
            return jsonify({"detail": "as_of must be YYYY-MM-DD"}), 400

    job_id = generate_job_id()
    created_at = datetime.now(timezone.utc).isoformat()

    csv_path_clean = str(csv_path).strip() if has_csv_path else None
    closings_path_clean = str(closings_path).strip() if has_closings_path else None
    csv_key_clean = str(csv_object_key).strip() if has_csv_key else None
    closings_key_clean = str(closings_object_key).strip() if has_closings_key else None

    analysis_jobs[job_id] = {
        "status": "pending",
        "progress": 0,
        "message": "Starting analysis...",
        "closings_path": closings_path_clean,
        "csv_path": csv_path_clean,
        "closings_object_key": closings_key_clean,
        "csv_object_key": csv_key_clean,
        "created_at": created_at,
        "as_of": as_of,
    }

    thread = threading.Thread(
        target=run_analysis_sync,
        args=(job_id, closings_path_clean, csv_path_clean, as_of, closings_key_clean, csv_key_clean),
        daemon=True,
    )
    thread.start()

    return jsonify(
        AnalysisResponse(
            job_id=job_id,
            status="started",
            message="Analysis started",
        ).model_dump()
    )


def _optional_int(val):
    """Convert value to int for API; None/nan become None."""
    if val is None:
        return None
    try:
        f = float(val)
        return int(f) if math.isfinite(f) else None
    except (TypeError, ValueError):
        return None


def _optional_float(val):
    """Convert value to float for API; None/nan become None."""
    if val is None:
        return None
    try:
        f = float(val)
        return f if math.isfinite(f) else None
    except (TypeError, ValueError):
        return None


def _json_maybe(val):
    if val is None:
        return None
    if isinstance(val, (dict, list)):
        return val
    if isinstance(val, str) and not str(val).strip():
        return None
    try:
        return json.loads(val)
    except (json.JSONDecodeError, TypeError):
        return None


def _normalize_stages(stages):
    """Coerce nested stage dicts for Pydantic (e.g. numpy bool from DataFrame)."""
    if stages is None or not isinstance(stages, dict):
        return None
    out = {}
    for k, v in stages.items():
        if isinstance(v, dict):
            out[k] = {"reached": bool(v.get("reached")), "date": v.get("date")}
    return out or None


def _transform_result(r: dict) -> dict:
    """Transform result dict to match API model field names."""
    stages = _normalize_stages(r.get("Stages Reached"))
    lev = _json_maybe(r.get("Lifecycle Events"))
    if lev == []:
        lev = None
    out = {
        "Address": r.get("Address", ""),
        "Date_Closed": r.get("Date Closed", ""),
        "Lead_Source": r.get("Lead Source", ""),
        "Total_Contacts": r.get("Total Contacts", 0),
        "CC_Count": r.get("CC Count", 0),
        "SMS_Count": r.get("SMS Count", 0),
        "DM_Count": r.get("DM Count", 0),
        "First_Contact_Date": r.get("First Contact Date"),
        "Last_Contact_Date": r.get("Last Contact Date"),
        "Days_to_Close": _optional_int(r.get("Days to Close")),
        "Days_Since_Last_Contact": _optional_int(r.get("Days Since Last Contact")),
        "Contact_Timeline": r.get("Contact Timeline", ""),
        "Match_Found": r.get("Match Found", False),
        "Stages_Reached": stages,
        "Highest_Stage": r.get("Highest Stage"),
        "Stage_Dates": _json_maybe(r.get("Stage Dates")),
        "Path_Sequence": r.get("Path Sequence"),
        "First_Touch_Channel": r.get("First Touch Channel"),
        "Days_To_First_Touch": _optional_int(r.get("Days To First Touch")),
        "Days_To_Engagement": _optional_int(r.get("Days To Engagement")),
        "SF_Status_Trail": _json_maybe(r.get("SF Status Trail")),
        "List_Purchased_Date": r.get("List Purchased Date"),
        "Skip_Traced_Date": r.get("Skip Traced Date"),
        "Closed_Marker_Date": r.get("Closed Marker Date"),
        "Lifecycle_Events": lev,
    }
    return out


def _transform_stats(s: dict) -> dict:
    """Transform stats dict to match API model field names."""
    return {
        "Total_Deals": s.get("Total Deals", 0),
        "Matched_Deals": s.get("Matched Deals", 0),
        "Unmatched_Deals": s.get("Unmatched Deals", 0),
        "Match_Rate": s.get("Match Rate", "0%"),
        "Average_Contacts_per_Deal": s.get("Average Contacts per Deal", 0.0),
        "Median_Contacts_per_Deal": s.get("Median Contacts per Deal", 0.0),
        "Max_Contacts": s.get("Max Contacts", 0),
        "Min_Contacts": s.get("Min Contacts", 0),
        "Total_CC_Contacts": s.get("Total CC Contacts", 0),
        "Total_SMS_Contacts": s.get("Total SMS Contacts", 0),
        "Total_DM_Contacts": s.get("Total DM Contacts", 0),
        "Average_Days_to_Close": _optional_float(s.get("Average Days to Close")),
        "Median_Days_to_Close": _optional_float(s.get("Median Days to Close")),
        "Funnel_Acquired_Count": _optional_int(s.get("Funnel Acquired Count")),
        "Funnel_Researched_Count": _optional_int(s.get("Funnel Researched Count")),
        "Funnel_First_Contacted_Count": _optional_int(s.get("Funnel First Contacted Count")),
        "Funnel_Engaged_Count": _optional_int(s.get("Funnel Engaged Count")),
        "Funnel_Converted_Count": _optional_int(s.get("Funnel Converted Count")),
        "Funnel_Acquired_Rate_Pct": _optional_float(s.get("Funnel Acquired Rate Pct")),
        "Funnel_Researched_Rate_Pct": _optional_float(s.get("Funnel Researched Rate Pct")),
        "Funnel_First_Contact_Rate_Pct": _optional_float(s.get("Funnel First Contact Rate Pct")),
        "Funnel_Engaged_Rate_Pct": _optional_float(s.get("Funnel Engaged Rate Pct")),
        "Funnel_Converted_Rate_Pct": _optional_float(s.get("Funnel Converted Rate Pct")),
        "Engaged_To_Converted_Rate_Pct": _optional_float(s.get("Engaged To Converted Rate Pct")),
        "Top_Paths_Json": s.get("Top Paths Json"),
        "First_Touch_Breakdown_Json": s.get("First Touch Breakdown Json"),
    }


@api_bp.route("/analysis/<job_id>", methods=["GET"])
def get_analysis_results(job_id: str):
    """
    Get analysis results for a completed job.
    """
    if job_id not in analysis_results:
        return jsonify({"detail": "Analysis not found"}), 404

    result = analysis_results[job_id]

    analysis_results_list = [AnalysisResult(**_transform_result(r)) for r in result["results"]]
    stats = SummaryStats(**_transform_stats(result["stats"]))

    return jsonify(
        AnalysisCompleteResponse(
            job_id=job_id,
            status="completed",
            results=analysis_results_list,
            stats=stats,
            matched_count=result["matched_count"],
            total_deals=result["total_deals"],
            as_of=result.get("as_of"),
        ).model_dump()
    )


@api_bp.route("/analysis/<job_id>/status", methods=["GET"])
def get_analysis_status(job_id: str):
    """
    Get current status of an analysis job.
    """
    if job_id not in analysis_jobs:
        return jsonify({"detail": "Job not found"}), 404

    job = analysis_jobs[job_id]
    return jsonify({
        "job_id": job_id,
        "status": job["status"],
        "progress": job["progress"],
        "message": job["message"],
    })


@api_bp.route("/analysis/<job_id>/progress", methods=["GET"])
def get_analysis_progress(job_id: str):
    """
    Get progress (same as status). Provided for compatibility; frontend can poll this or use status.
    WebSocket is not used with Flask; use polling on status or this endpoint.
    """
    if job_id not in analysis_jobs:
        return jsonify({"error": "Job not found"}), 404
    job = analysis_jobs[job_id]
    return jsonify({
        "job_id": job_id,
        "progress": job["progress"],
        "message": job["message"],
        "step": job.get("step", ""),
    })


@api_bp.route("/analysis/<job_id>/export", methods=["GET"])
def export_results(job_id: str):
    """
    Export analysis results. Query param: format=excel|csv|json
    """
    if job_id not in analysis_results:
        return jsonify({"detail": "Analysis not found"}), 404

    format_type = request.args.get("format", "excel")
    result = analysis_results[job_id]
    results_df = pd.DataFrame(result["results"])

    if format_type == "excel":
        output_path = str(EXPORT_DIR / f"{job_id}.xlsx")
        with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
            results_df.to_excel(writer, sheet_name="Detailed Results", index=False)
            stats_data = [{"Metric": k, "Value": v} for k, v in result["stats"].items()]
            pd.DataFrame(stats_data).to_excel(writer, sheet_name="Summary Statistics", index=False)
            long_rows: List[Dict[str, Any]] = []
            for _, row in results_df.iterrows():
                addr = row.get("Address")
                raw_ev = row.get("Lifecycle Events")
                events = _json_maybe(raw_ev) if raw_ev is not None else None
                if isinstance(events, list):
                    for i, ev in enumerate(events):
                        if isinstance(ev, dict):
                            row_out = dict(ev)
                            row_out["Address"] = addr
                            row_out["Order"] = i + 1
                            long_rows.append(row_out)
            if long_rows:
                pd.DataFrame(long_rows).to_excel(writer, sheet_name="Lifecycle Events", index=False)
        return send_file(
            output_path,
            as_attachment=True,
            download_name=f"analysis_{job_id}.xlsx",
            mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

    if format_type == "csv":
        output_path = str(EXPORT_DIR / f"{job_id}.csv")
        results_df.to_csv(output_path, index=False)
        return send_file(
            output_path,
            as_attachment=True,
            download_name=f"analysis_{job_id}.csv",
            mimetype="text/csv",
        )

    if format_type == "json":
        return jsonify(result)

    return jsonify({"detail": "Invalid format. Use: excel, csv, or json"}), 400


@api_bp.route("/compare", methods=["POST"])
def compare_analyses():
    """
    Compare multiple analysis runs. Expects JSON body: { "job_ids": ["id1", "id2", ...] }
    """
    data = request.get_json() or {}
    try:
        req = ComparisonRequest(**data)
    except Exception:
        return jsonify({"detail": "Invalid request; job_ids array required"}), 400

    comparisons = {}
    differences = {}

    for job_id in req.job_ids:
        if job_id not in analysis_results:
            continue
        result = analysis_results[job_id]
        comparisons[job_id] = {
            "stats": result["stats"],
            "matched_count": result["matched_count"],
            "total_deals": result["total_deals"],
            "as_of": result.get("as_of"),
        }

    if len(comparisons) > 1:
        job_ids = list(comparisons.keys())
        base_stats = comparisons[job_ids[0]]["stats"]
        for job_id in job_ids[1:]:
            compare_stats = comparisons[job_id]["stats"]
            diff = {}
            for key in base_stats:
                if isinstance(base_stats.get(key), (int, float)) and isinstance(
                    compare_stats.get(key), (int, float)
                ):
                    diff[key] = compare_stats[key] - base_stats[key]
            differences[job_id] = diff

    return jsonify(
        ComparisonResponse(
            comparisons=comparisons,
            differences=differences,
        ).model_dump()
    )


@api_bp.route("/analyses", methods=["GET"])
def list_analyses():
    """
    List all saved analyses (persisted and in-memory).
    """
    analyses = [
        {
            "job_id": job_id,
            "status": job["status"],
            "created_at": job.get("created_at", ""),
            "matched_count": analysis_results.get(job_id, {}).get("matched_count", 0),
            "total_deals": analysis_results.get(job_id, {}).get("total_deals", 0),
            "as_of": job.get("as_of") or analysis_results.get(job_id, {}).get("as_of"),
        }
        for job_id, job in analysis_jobs.items()
    ]
    analyses.sort(key=lambda x: x.get("created_at", ""), reverse=True)
    return jsonify({"analyses": analyses})


@api_bp.route("/analysis/<job_id>", methods=["DELETE"])
def delete_analysis(job_id: str):
    """
    Delete a saved report (JSON file and in-memory entry).
    """
    for path in REPORTS_DIR.rglob(f"{job_id}.json"):
        try:
            path.unlink()
        except OSError:
            pass
    analysis_jobs.pop(job_id, None)
    analysis_results.pop(job_id, None)
    return jsonify({"detail": "Deleted", "job_id": job_id})
