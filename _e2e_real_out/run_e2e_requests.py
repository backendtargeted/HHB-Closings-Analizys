#!/usr/bin/env python3
"""
HTTP E2E against local Flask backend: patches upload+export_zip, main upload+analyze+export_csv.
Writes artifacts under this directory (caller runs build_derived_inputs.py first).
"""

from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
OUT = Path(__file__).resolve().parent
DERIVED = OUT / "derived"
BASE_URL = "http://127.0.0.1:8000"


def curl_file(args: list[str], out_body: Path) -> int:
    cmd = ["curl.exe", "-s", "-S", "-o", str(out_body), "-w", "%{http_code}"] + args
    proc = subprocess.run(cmd, cwd=str(REPO), capture_output=True, text=True, check=False)
    raw = proc.stdout.strip()
    code = ""
    if raw:
        parts = raw.split("\n")
        code = parts[-1]
    err = proc.stderr.strip()
    (out_body.parent / (out_body.name + ".stderr.txt")).write_text(
        err + "\ncmd:" + json.dumps(cmd), encoding="utf-8"
    )
    try:
        return int(code) if code.isdigit() else 0
    except ValueError:
        return 0


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    DERIVED.mkdir(parents=True, exist_ok=True)

    cold = REPO / "Data_ingestion_samples/Weekly_and_monthly/Cweb Call Logs.csv"
    crm = REPO / "Data_ingestion_samples/Weekly_and_monthly/weekly_podio_updates_2026-05-04.csv"
    closings = REPO / "Data_ingestion_samples/past_patches/Report-2026-05-04-16-02-00.xlsx"
    sms = DERIVED / "Decision Maker.csv"
    exe = DERIVED / "e2e_report_paired_closings.xlsx"
    hist_csv = DERIVED / "e2e_report_paired_history.csv"

    for p in [cold, crm, closings, sms, exe, hist_csv]:
        if not p.exists():
            raise SystemExit(f"Missing required path: {p}")

    subprocess.run(["curl.exe", "-s", "-o", str(OUT / "health_raw.json"), f"{BASE_URL}/health"], check=False)

    # --- PATCHES ---
    pj = OUT / "patches_upload_http.json"
    status = curl_file(
        [
            "-X",
            "POST",
            f"{BASE_URL}/api/patches/upload",
            "-F",
            f"cold_csv=@{cold.as_posix()};type=text/csv",
            "-F",
            f"crm_csv=@{crm.as_posix()};type=text/csv",
            "-F",
            f"closings_xlsx=@{closings.as_posix()};type=application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            "-F",
            f"sms_files=@{sms.as_posix()};type=text/csv",
        ],
        pj,
    )
    (OUT / "patches_upload_http_status.txt").write_text(str(status), encoding="utf-8")

    job_id_p = ""
    parsed: dict = {}
    try:
        parsed = json.loads(pj.read_bytes().decode("utf-8"))
        job_id_p = str(parsed.get("job_id", ""))
    except json.JSONDecodeError:
        parsed = {}

    zip_path = OUT / "reisift_import_patchexport.zip"
    if job_id_p and status == 200:
        zs = curl_file(
            ["-L", f"{BASE_URL}/api/patches/{job_id_p}/export?file=all&allow_unmapped=true"],
            zip_path,
        )
        (OUT / "patches_zip_http_status.txt").write_text(str(zs), encoding="utf-8")
    else:
        zip_path.write_bytes(b"No zip produced (patch upload failed or no job id).\n")

    # --- MAIN ANALYSIS ---
    up = OUT / "main_upload_response.json"
    us = curl_file(
        [
            "-X",
            "POST",
            f"{BASE_URL}/api/upload",
            "-F",
            f"excel_file=@{exe.as_posix()};type=application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            "-F",
            f"csv_file=@{hist_csv.as_posix()};type=text/csv",
        ],
        up,
    )
    (OUT / "main_upload_http_status.txt").write_text(str(us), encoding="utf-8")

    excel_path_srv = csv_path_srv = ""
    try:
        jd = json.loads(up.read_bytes().decode("utf-8"))
        excel_path_srv = jd.get("excel_path", "")
        csv_path_srv = jd.get("csv_path", "")
    except json.JSONDecodeError:
        jd = {}

    an = OUT / "main_analyze_response.json"
    job_main = ""
    if excel_path_srv and csv_path_srv:
        ap = subprocess.run(
            [
                "curl.exe",
                "-s",
                "-S",
                "-X",
                "POST",
                f"{BASE_URL}/api/analyze",
                "-H",
                "Content-Type: application/json",
                "-d",
                json.dumps({"excel_path": excel_path_srv, "csv_path": csv_path_srv}),
            ],
            capture_output=True,
        )
        an.write_bytes(ap.stdout)
        if ap.stderr:
            (OUT / "main_analyze_response.stderr.txt").write_bytes(ap.stderr)
        try:
            job_main = str(json.loads(ap.stdout.decode("utf-8")).get("job_id", ""))
        except (json.JSONDecodeError, UnicodeDecodeError):
            job_main = ""

    deadline = time.time() + 300
    stat_path = OUT / "main_analysis_completed_status.json"
    while job_main and time.time() < deadline:
        ss = subprocess.run(
            ["curl.exe", "-s", "-S", f"{BASE_URL}/api/analysis/{job_main}/status"],
            capture_output=True,
            text=True,
        )
        stat_path.write_text(ss.stdout, encoding="utf-8")
        try:
            st = json.loads(ss.stdout or "{}")
        except json.JSONDecodeError:
            st = {}
        if st.get("status") in ("completed", "failed"):
            break
        time.sleep(0.35)

    if job_main:
        rr = subprocess.run(
            ["curl.exe", "-s", "-S", f"{BASE_URL}/api/analysis/{job_main}"],
            capture_output=True,
        )
        (OUT / "main_analysis_complete_response.json").write_bytes(rr.stdout)

        subprocess.run(
            [
                "curl.exe",
                "-s",
                "-S",
                "-f",
                "-o",
                str(OUT / "main_analysis_export_results.csv"),
                f"{BASE_URL}/api/analysis/{job_main}/export?format=csv",
            ],
            capture_output=True,
        )
        subprocess.run(
            [
                "curl.exe",
                "-s",
                "-S",
                "-f",
                "-o",
                str(OUT / "main_analysis_export_full.json"),
                f"{BASE_URL}/api/analysis/{job_main}/export?format=json",
            ],
            capture_output=True,
        )
    else:
        stat_path.write_text(json.dumps({"note": "no job_id from analyze"}), encoding="utf-8")

    lines = []
    for f in sorted(OUT.rglob("*")):
        if f.is_file():
            lines.append({"path": f.relative_to(REPO).as_posix(), "bytes": f.stat().st_size})
    (OUT / "artifact_sizes_manifest.json").write_text(json.dumps(lines, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()