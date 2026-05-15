"""
Validate Data_ingestion_samples/past_patches/podio/new_ingest Report-*.xlsx files,
then emit REISift zip using Weekly_and_monthly + adapted Podio Closings workbook.

new_ingest Podio exports (May 2026) omit property address columns; they cannot be
used as closings_xlsx for process_closings_for_tags. Closings tags use
Closings - Last view used.xlsx (adapted) instead — see new_ingest_validation.json.
"""

from __future__ import annotations

import importlib.util
import json
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from shutil import copy2

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "backend"))

import pandas as pd  # noqa: E402

from app.services.marketing_mapper import (  # noqa: E402
    process_closings_for_tags,
    run_patch_pipeline,
    write_patch_exports,
)


def _utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _load_one_time_module():
    path = REPO / "scripts" / "one_time_samples_reisift_zip.py"
    spec = importlib.util.spec_from_file_location("one_time_samples_reisift_zip", path)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader
    spec.loader.exec_module(mod)
    return mod


def _compare_reports(paths: list[Path]) -> dict:
    out: dict = {"files": [str(p) for p in paths]}
    if len(paths) != 2:
        out["error"] = "expected two Report-*.xlsx"
        return out
    a = pd.read_excel(paths[0], engine="openpyxl")
    b = pd.read_excel(paths[1], engine="openpyxl")
    out["same_column_order"] = list(a.columns) == list(b.columns)
    out["rows_a"] = len(a)
    out["rows_b"] = len(b)
    out["columns_a"] = [str(c) for c in a.columns]
    out["columns_b"] = [str(c) for c in b.columns]
    if out["same_column_order"] and len(a) == len(b):
        out["dataframes_equal"] = bool(a.fillna("__NA__").equals(b.fillna("__NA__")))
    else:
        out["dataframes_equal"] = None
    return out


def _try_closings(path: Path) -> dict:
    try:
        df = process_closings_for_tags(str(path))
        return {"ok": True, "closings_tag_rows": len(df)}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def main() -> Path:
    stamp = _utc_stamp()
    out_root = REPO / "_ingest_out" / f"{stamp}_new_ingest"
    out_root.mkdir(parents=True, exist_ok=True)
    work = out_root / "work"
    work.mkdir(parents=True, exist_ok=True)

    new_ingest = REPO / "Data_ingestion_samples/past_patches/podio/new_ingest"
    reports = sorted(new_ingest.glob("Report-*.xlsx"))

    cmp = _compare_reports(reports)
    closings_try = {p.name: _try_closings(p) for p in reports}

    ots = _load_one_time_module()
    podio_closings: Path = ots.PODIO_CLOSINGS
    cweb: Path = ots.CWEB
    charles: Path = ots.CHARLES
    crm: Path = ots.CRM

    adapted_closings = work / "closings_for_mapper.xlsx"
    n_close, n_skip, n_usaddr_fb = ots.adapt_podio_closings_for_mapper(podio_closings, adapted_closings)

    charles_ready = work / "Charles_as_Decision_Mapper.csv"
    n_sms = ots.build_charles_sms_for_mapper(charles, charles_ready)
    sms_entries = [("Decision Maker.csv", str(charles_ready))]

    cold_path = work / "cold_calling.csv"
    copy2(cweb, cold_path)
    crm_path = work / "crm_updates.csv"
    copy2(crm, crm_path)

    result = run_patch_pipeline(
        str(cold_path),
        sms_entries,
        str(crm_path),
        closings_xlsx_path=str(adapted_closings),
    )

    csv_dir = out_root / "csv"
    csv_dir.mkdir(parents=True, exist_ok=True)
    allow_unmapped = True
    written = write_patch_exports(result, str(csv_dir), allow_unmapped=allow_unmapped)

    zip_path = out_root / "reisift_import.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for p in written:
            fp = Path(p)
            zf.write(fp, arcname=fp.name)

    lead_csv = out_root / "lead_source_by_property.csv"
    n_ls = ots.write_lead_source_sidecar(podio_closings, lead_csv)

    validation = {
        "stamp_utc": stamp,
        "new_ingest_dir": str(new_ingest),
        "report_files_compared": cmp,
        "process_closings_for_tags_each_report": closings_try,
        "resolution": (
            "new_ingest Report exports lack Address / Billing Street / split address columns; "
            "they are opportunity-summary layouts (see columns_a). closings_xlsx for the bundle "
            "uses adapted Podio Closings - Last view used.xlsx (same as one_time_samples_reisift_zip.py)."
        ),
        "reference_report_with_addresses": str(
            REPO / "Data_ingestion_samples/past_patches/Report-2026-05-04-16-02-00.xlsx"
        ),
    }
    (out_root / "new_ingest_validation.json").write_text(
        json.dumps(validation, indent=2),
        encoding="utf-8",
    )

    metrics = {
        "inputs": {
            "cold_csv": str(cweb),
            "sms_csv": str(charles),
            "crm_csv": str(crm),
            "podio_closings_adapted_from": str(podio_closings),
            "adapted_closings_rows": n_close,
            "adapted_closings_skipped_no_date": n_skip,
            "usaddress_closings_fallback_rows": n_usaddr_fb,
            "charles_sms_rows_prepared": n_sms,
        },
        "allow_unmapped": allow_unmapped,
        "cold_unmapped": result.cold_unmapped,
        "sms_unmapped": result.sms_unmapped,
        "crm_unmapped": result.crm_unmapped,
        "crm_metrics": result.crm_metrics,
        "closings_rows": result.closings_rows,
        "csv_paths": written,
        "zip_path": str(zip_path),
        "zip_bytes": zip_path.stat().st_size,
        "lead_source_sidecar_rows": n_ls,
        "new_ingest_validation": str(out_root / "new_ingest_validation.json"),
    }
    (out_root / "ingest_metrics.json").write_text(json.dumps(metrics, indent=2), encoding="utf-8")

    readme = out_root / "README.txt"
    readme.write_text(
        "\n".join(
            [
                "REISift bundle after new_ingest validation (Podio Report-2026-05-07-*.xlsx).",
                "",
                "new_ingest_validation.json: those exports omit property address columns required",
                "by process_closings_for_tags; closings_status_tags.csv is built from adapted",
                "Closings - Last view used.xlsx instead.",
                "",
                "ZIP: reisift_import.zip — property_status_updates.csv, phone_status_tags_updates.csv,",
                "salesforce_status_tags.csv, closings_status_tags.csv.",
                "",
                f"Generated UTC {stamp}.",
            ]
        ),
        encoding="utf-8",
    )

    print("OUT", out_root)
    print("ZIP", zip_path, zip_path.stat().st_size, "bytes")
    print("validation", out_root / "new_ingest_validation.json")
    return out_root


if __name__ == "__main__":
    main()
