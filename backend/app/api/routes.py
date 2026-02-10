"""
API routes for the contact attribution analysis (Flask)
"""

import json
import math
import uuid
import threading
from datetime import datetime, timezone
from typing import Dict, List, Any
from flask import Blueprint, request, jsonify, send_file
import pandas as pd
import os
from pathlib import Path

from ..services.analysis import perform_analysis
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
    """Persist analysis result to reports/{job_id}.json."""
    _ensure_reports_dir()
    path = REPORTS_DIR / f"{job_id}.json"
    payload = {
        "results": result.get("results", []),
        "stats": result.get("stats", {}),
        "matched_count": result.get("matched_count", 0),
        "total_deals": result.get("total_deals", 0),
        "created_at": created_at,
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(_sanitize_for_json(payload), f, indent=2)


def load_reports_from_disk() -> None:
    """Load all persisted reports from REPORTS_DIR into memory."""
    _ensure_reports_dir()
    for path in REPORTS_DIR.glob("*.json"):
        try:
            job_id = path.stem
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            created_at = data.get("created_at", datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).isoformat())
            analysis_results[job_id] = {
                "results": data.get("results", []),
                "stats": data.get("stats", {}),
                "matched_count": data.get("matched_count", 0),
                "total_deals": data.get("total_deals", 0),
            }
            analysis_jobs[job_id] = {
                "status": "completed",
                "progress": 100,
                "message": "Analysis complete",
                "created_at": created_at,
            }
        except (json.JSONDecodeError, OSError) as e:
            # Skip broken files
            continue


def generate_job_id() -> str:
    """Generate a unique job ID."""
    return str(uuid.uuid4())


def run_analysis_sync(job_id: str, excel_path: str, csv_path: str):
    """Run analysis in a background thread and update job status."""
    try:
        analysis_jobs[job_id]["status"] = "running"

        def progress_callback(message: str, progress: int):
            analysis_jobs[job_id]["progress"] = progress
            analysis_jobs[job_id]["message"] = message

        result = perform_analysis(excel_path, csv_path, progress_callback)

        analysis_results[job_id] = result
        created_at = datetime.now(timezone.utc).isoformat()
        analysis_jobs[job_id]["status"] = "completed"
        analysis_jobs[job_id]["progress"] = 100
        analysis_jobs[job_id]["message"] = "Analysis complete"
        analysis_jobs[job_id]["created_at"] = created_at
        save_report_to_disk(job_id, result, created_at)

    except Exception as e:
        analysis_jobs[job_id]["status"] = "failed"
        analysis_jobs[job_id]["message"] = str(e)


@api_bp.route("/upload", methods=["POST"])
def upload_files():
    """
    Upload Excel and CSV files for analysis.
    """
    try:
        excel_file = request.files.get("excel_file")
        csv_file = request.files.get("csv_file")

        if not excel_file or not excel_file.filename:
            return jsonify({"detail": "Excel file is required"}), 400
        if not csv_file or not csv_file.filename:
            return jsonify({"detail": "CSV file is required"}), 400

        excel_path = save_uploaded_file(excel_file, "excel")
        csv_path = save_uploaded_file(csv_file, "csv")

        if not validate_excel_file(excel_path):
            delete_file(excel_path)
            delete_file(csv_path)
            return jsonify({"detail": "Invalid Excel file"}), 400

        if not validate_csv_file(csv_path):
            delete_file(excel_path)
            delete_file(csv_path)
            return jsonify({"detail": "Invalid CSV file"}), 400

        return jsonify({
            "excel_path": excel_path,
            "csv_path": csv_path,
            "message": "Files uploaded successfully",
        })
    except Exception as e:
        return jsonify({"detail": str(e)}), 500


@api_bp.route("/analyze", methods=["POST"])
def start_analysis():
    """
    Start an analysis job. Expects JSON body: { "excel_path": "...", "csv_path": "..." }
    """
    data = request.get_json() or {}
    excel_path = data.get("excel_path")
    csv_path = data.get("csv_path")

    if not excel_path or not csv_path:
        return jsonify({"detail": "excel_path and csv_path are required"}), 400

    job_id = generate_job_id()
    created_at = datetime.now(timezone.utc).isoformat()

    analysis_jobs[job_id] = {
        "status": "pending",
        "progress": 0,
        "message": "Starting analysis...",
        "excel_path": excel_path,
        "csv_path": csv_path,
        "created_at": created_at,
    }

    thread = threading.Thread(
        target=run_analysis_sync,
        args=(job_id, excel_path, csv_path),
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


def _transform_result(r: dict) -> dict:
    """Transform result dict to match API model field names."""
    return {
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
    }


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
    path = REPORTS_DIR / f"{job_id}.json"
    if path.exists():
        try:
            path.unlink()
        except OSError:
            pass
    analysis_jobs.pop(job_id, None)
    analysis_results.pop(job_id, None)
    return jsonify({"detail": "Deleted", "job_id": job_id})
