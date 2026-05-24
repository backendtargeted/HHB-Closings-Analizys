"""
Clean rerun ingest: Podio Closings + latest Tina (Closed/Executed) WITHOUT Weekly_and_monthly.

Uses minimal cold/SMS/CRM stubs so run_patch_pipeline succeeds; closings tags are real.
Expect salesforce_status_tags.csv with 0 data rows (CRM lives in Weekly_and_monthly).

Usage:
  python scripts/run_clean_rerun_no_weekly.py
"""

from __future__ import annotations

import importlib.util
import json
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "backend"))

from app.services.marketing_mapper import run_patch_pipeline, write_patch_exports  # noqa: E402

SAMPLES = REPO / "Data_ingestion_samples"
PODIO_DIR = SAMPLES / "past_patches" / "podio"
WEEKLY = SAMPLES / "Weekly_and_monthly"


def _utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _load_podio_bundle():
    path = REPO / "scripts" / "one_time_podio_closings_opps_tags_bundle.py"
    spec = importlib.util.spec_from_file_location("podio_bundle", path)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader
    spec.loader.exec_module(mod)
    return mod


def _inventory_samples() -> list[dict]:
    rows: list[dict] = []
    for p in sorted(SAMPLES.rglob("*.xlsx")):
        rel = p.relative_to(SAMPLES).as_posix()
        if rel.startswith("Weekly_and_monthly/"):
            continue
        used = False
        reason = ""
        if rel == "past_patches/podio/Closings - Last view used.xlsx":
            used, reason = True, "Primary Podio closings workbook."
        elif "New Opportunities Report - Tina" in rel:
            latest = _load_podio_bundle()._pick_latest_tina_report(PODIO_DIR)
            if latest and p.resolve() == latest.resolve():
                used, reason = True, "Latest Tina report (Closed/Executed merge)."
            else:
                reason = "Older Tina export."
        elif rel == "Closings - Last view used.xlsx":
            reason = "Duplicate of past_patches/podio copy."
        elif "Report-" in rel:
            reason = "Report export not wired in mapper pipeline."
        elif "past_closings" in rel:
            reason = "Skipped to avoid duplicate closings vs Podio workbook."
        elif "Opportunities" in rel or "Seller Leads" in rel:
            reason = "Not wired in closings/tags bundle."
        else:
            reason = "Not used in this ingest path."
        rows.append({"path": rel, "used": used, "reason": reason})
    return rows


def _write_stubs(work: Path) -> tuple[Path, Path, list[tuple[str, str]]]:
    cold = work / "stub_cold_calling.csv"
    cold.write_text(
        "Phone,Address,City,State,Zip Code,Log Type\n",
        encoding="utf-8",
    )
    crm = work / "stub_crm_updates.csv"
    crm.write_text("leadstatus\n", encoding="utf-8")
    sms = work / "Decision Maker.csv"
    sms.write_text(
        "Phone,Property address,Property city,Property state,Property zip\n"
        "0000000000,1 Stub St,Stubville,NY,11701\n",
        encoding="utf-8",
    )
    return cold, crm, [("Decision Maker.csv", str(sms))]


def main() -> Path:
    bundle = _load_podio_bundle()
    ots = bundle._load_one_time_samples()

    stamp = _utc_stamp()
    out_root = REPO / "_ingest_out" / f"{stamp}_clean_rerun"
    work = out_root / "work"
    work.mkdir(parents=True, exist_ok=True)

    closings_src = PODIO_DIR / "Closings - Last view used.xlsx"
    if not closings_src.is_file():
        raise SystemExit(f"Missing: {closings_src}")

    adapted_path = work / "closings_from_podio_adapted.xlsx"
    n_close, n_skip, n_usaddr_fb = ots.adapt_podio_closings_for_mapper(closings_src, adapted_path)
    podio_adapted = pd.read_excel(adapted_path, engine="openpyxl")

    tina_path = bundle._pick_latest_tina_report(PODIO_DIR)
    tina_rows = pd.DataFrame()
    tina_sidecar_rows = 0
    if tina_path and tina_path.is_file():
        tina_rows = bundle._tina_closed_property_rows(tina_path)
        tina_sidecar_rows = bundle._write_opportunity_sidecar(
            tina_path, out_root / "opportunity_rows_sidecar.csv"
        )

    if tina_rows.empty:
        merged = podio_adapted
        merge_note = "Tina absent or no Closed/Executed rows; Podio closings only."
    else:
        merged = bundle._merge_closings_sheets(podio_adapted, tina_rows)
        merge_note = (
            f"Merged adapted Podio closings ({len(podio_adapted)} rows) with Tina Closed+Executed "
            f"({len(tina_rows)} rows) -> {len(merged)} rows after dedupe by address_key+month."
        )

    merged_xlsx = work / "merged_closings_for_mapper.xlsx"
    merged.to_excel(merged_xlsx, index=False)

    cold_path, crm_path, sms_entries = _write_stubs(work)
    result = run_patch_pipeline(
        str(cold_path),
        sms_entries,
        str(crm_path),
        closings_xlsx_path=str(merged_xlsx),
    )

    csv_dir = out_root / "csv"
    csv_dir.mkdir(parents=True, exist_ok=True)
    written = write_patch_exports(result, str(csv_dir), allow_unmapped=True)

    zip_path = out_root / "reisift_import.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for p in written:
            fp = Path(p)
            zf.write(fp, arcname=fp.name)

    lead_csv = out_root / "lead_source_by_property.csv"
    n_ls = ots.write_lead_source_sidecar(closings_src, lead_csv)

    sf_rows = len(result.sf_tags_df) if result.sf_tags_df is not None and not result.sf_tags_df.empty else 0
    inventory = _inventory_samples()

    metrics = {
        "stamp_utc": stamp,
        "mode": "clean_rerun_no_weekly",
        "merge_note": merge_note,
        "metrics_summary": {
            "closings_tag_rows": result.closings_rows,
            "sf_tags_rows": sf_rows,
            "sf_tags_note": (
                "SF tags require Weekly_and_monthly CRM CSV matching cold/SMS rows. "
                "This run uses empty stubs by design."
            ),
        },
        "inputs_used": {
            "podio_closings": str(closings_src),
            "tina_opportunities_report": str(tina_path) if tina_path else None,
            "cold_csv": str(cold_path),
            "sms_stub": str(sms_entries[0][1]),
            "crm_stub": str(crm_path),
            "merged_closings_xlsx": str(merged_xlsx),
            "adapted_podio_rows": len(podio_adapted),
            "tina_closed_executed_rows": len(tina_rows),
            "merged_rows_before_tags": len(merged),
            "adapted_skipped_no_date": n_skip,
            "usaddress_fallback_rows": n_usaddr_fb,
            "opportunity_sidecar_all_rows": tina_sidecar_rows,
            "lead_source_sidecar_rows": n_ls,
        },
        "weekly_and_monthly_excluded": str(WEEKLY),
        "allow_unmapped": True,
        "cold_unmapped": result.cold_unmapped,
        "sms_unmapped": result.sms_unmapped,
        "crm_unmapped": result.crm_unmapped,
        "crm_metrics": result.crm_metrics,
        "csv_paths": written,
        "zip_path": str(zip_path),
        "zip_bytes": zip_path.stat().st_size,
        "sample_files_inventory": inventory,
    }
    (out_root / "ingest_metrics.json").write_text(json.dumps(metrics, indent=2), encoding="utf-8")

    readme_lines = [
        "Clean rerun WITHOUT Weekly_and_monthly (see scripts/run_clean_rerun_no_weekly.py).",
        "",
        merge_note,
        "",
        f"closings_tag_rows: {result.closings_rows}",
        f"sf_tags_rows: {sf_rows} (expected 0 without CRM from Weekly_and_monthly)",
        "",
        "Import closings_status_tags.csv into REISift for settlement markers.",
        "salesforce_status_tags.csv is header-only in this mode.",
    ]
    (out_root / "README.txt").write_text("\n".join(readme_lines), encoding="utf-8")

    print("OUT", out_root)
    print("ZIP", zip_path, zip_path.stat().st_size, "bytes")
    print("closings_tag_rows", result.closings_rows)
    print("sf_tags_rows", sf_rows)
    return out_root


if __name__ == "__main__":
    main()
