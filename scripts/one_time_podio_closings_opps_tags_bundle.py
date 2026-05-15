"""
One-time REISift bundle: Podio Closings + Salesforce-style "New Opportunities Report"
closed rows, using existing process_closings_for_tags / run_patch_pipeline.

Grounded inputs (Data_ingestion_samples/past_patches/podio):
  - Closings - Last view used.xlsx  → adapt_podio_closings_for_mapper (Date Closed, property split)
  - New Opportunities Report - Tina-*.xlsx  → rows Stage in (Closed, Executed), Close Date + Address

Dedupe before tag generation: same make_address_key + calendar month as Date Closed keeps first row
(Podio closings rows are concatenated first so they win over Tina on collisions).

Outputs under _ingest_out/<UTC>_podio_closings_opps: reisift_import.zip, ingest_metrics.json,
opportunity_rows_sidecar.csv (all Tina rows for ops history QA — not a REISift four-pack file).
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from shutil import copy2

import pandas as pd

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "backend"))

from app.services.marketing_mapper import (  # noqa: E402
    make_address_key,
    run_patch_pipeline,
    sanitize_phone,
    sanitize_text,
    write_patch_exports,
)


def _utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _load_one_time_samples() -> object:
    path = REPO / "scripts" / "one_time_samples_reisift_zip.py"
    spec = importlib.util.spec_from_file_location("one_time_samples_reisift_zip", path)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader
    spec.loader.exec_module(mod)
    return mod


def _pick_latest_tina_report(podio_dir: Path) -> Path | None:
    candidates = sorted(podio_dir.glob("New Opportunities Report - Tina*.xlsx"))
    if not candidates:
        return None
    # Prefer latest by parsed trailing timestamp YYYY-MM-DD-HH-MM-SS when present
    def sort_key(p: Path) -> tuple:
        stem = p.stem
        parts = stem.split("-")
        tail = "-".join(parts[-6:]) if len(parts) >= 6 else stem
        return (p.stat().st_mtime, tail)

    return max(candidates, key=sort_key)


def _tina_closed_property_rows(path: Path) -> pd.DataFrame:
    df = pd.read_excel(path, engine="openpyxl")
    need = {"Stage", "Close Date", "Address (City)", "Address (ZIP/Postal Code)"}
    missing = need - set(df.columns)
    if missing:
        raise ValueError(f"Tina report missing columns {sorted(missing)}: {path}")
    if "Address" not in df.columns and "Address (Street)" not in df.columns:
        raise ValueError(f"Tina report missing Address / Address (Street): {path}")

    sub = df[df["Stage"].isin(["Closed", "Executed"])].copy()
    street = (
        sub["Address (Street)"]
        if "Address (Street)" in sub.columns
        else pd.Series("", index=sub.index)
    )
    street = street.fillna(sub.get("Address", pd.Series("", index=sub.index)))
    if "Billing Street" in sub.columns:
        street = street.fillna(sub["Billing Street"])

    out = pd.DataFrame(
        {
            "Property address": street.map(sanitize_text),
            "Property city": sub["Address (City)"].map(sanitize_text),
            "State": "",
            "Zip Code": sub["Address (ZIP/Postal Code)"].astype(str).map(sanitize_text),
            "Date Closed": sub["Close Date"],
            "Phone": sub["Opportunity Owner: Mobile Phone"]
            .fillna(sub["Opportunity Owner: Phone"])
            .map(sanitize_phone),
        }
    )
    out = out[out["Property address"].str.len() > 2]
    return out


def _merge_closings_sheets(podio_adapted: pd.DataFrame, tina_rows: pd.DataFrame) -> pd.DataFrame:
    comb = pd.concat([podio_adapted, tina_rows], ignore_index=True)
    comb["dc"] = pd.to_datetime(comb["Date Closed"], errors="coerce")
    comb = comb[comb["dc"].notna()].copy()
    comb["_k"] = comb.apply(
        lambda r: make_address_key(
            str(r.get("Property address", "")),
            str(r.get("Property city", "")),
            str(r.get("State", "")),
            str(r.get("Zip Code", "")),
        ),
        axis=1,
    )
    comb["_ym"] = comb["dc"].dt.to_period("M").astype(str)
    comb = comb.drop_duplicates(subset=["_k", "_ym"], keep="first")
    return comb.drop(columns=["_k", "_ym", "dc"])


def _write_opportunity_sidecar(tina_path: Path, out_csv: Path) -> int:
    """All opportunity rows from Tina report (stages, dates) for offline history / QA."""
    df = pd.read_excel(tina_path, engine="openpyxl")
    rows = []
    for _, r in df.iterrows():
        street = r.get("Address (Street)") or r.get("Address") or r.get("Billing Street") or ""
        rows.append(
            {
                "stage": sanitize_text(r.get("Stage", "")),
                "close_date_raw": r.get("Close Date"),
                "created_date_raw": r.get("Created Date"),
                "opportunity_name": sanitize_text(r.get("Opportunity Name", "")),
                "account_name": sanitize_text(r.get("Account Name", "")),
                "lead_source": sanitize_text(r.get("Lead Source", "")),
                "property_address": sanitize_text(street),
                "property_city": sanitize_text(r.get("Address (City)", "")),
                "zip": sanitize_text(str(r.get("Address (ZIP/Postal Code)", ""))),
                "phone": sanitize_phone(
                    r.get("Opportunity Owner: Mobile Phone") or r.get("Opportunity Owner: Phone") or ""
                ),
            }
        )
    side = pd.DataFrame(rows)
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    side.to_csv(out_csv, index=False)
    return len(side)


def main() -> Path:
    ap = argparse.ArgumentParser(description="One-time Podio closings + Tina closed opps → REISift zip")
    ap.add_argument(
        "--podio-dir",
        type=Path,
        default=REPO / "Data_ingestion_samples/past_patches/podio",
        help="Folder with Closings workbook and Tina opportunity exports",
    )
    ap.add_argument(
        "--skip-tina",
        action="store_true",
        help="Only Podio Closings (ignore New Opportunities Report - Tina*.xlsx)",
    )
    args = ap.parse_args()

    podio_dir: Path = args.podio_dir.resolve()
    closings_src = podio_dir / "Closings - Last view used.xlsx"
    if not closings_src.is_file():
        raise SystemExit(f"Missing Podio closings workbook: {closings_src}")

    ots = _load_one_time_samples()
    stamp = _utc_stamp()
    out_root = REPO / "_ingest_out" / f"{stamp}_podio_closings_opps"
    work = out_root / "work"
    work.mkdir(parents=True, exist_ok=True)

    adapted_path = work / "closings_from_podio_adapted.xlsx"
    n_close, n_skip, n_usaddr_fb = ots.adapt_podio_closings_for_mapper(closings_src, adapted_path)
    podio_adapted = pd.read_excel(adapted_path, engine="openpyxl")

    tina_path = None if args.skip_tina else _pick_latest_tina_report(podio_dir)
    tina_rows = pd.DataFrame()
    tina_sidecar_rows = 0
    if tina_path and tina_path.is_file():
        tina_rows = _tina_closed_property_rows(tina_path)
        tina_sidecar_rows = _write_opportunity_sidecar(
            tina_path, out_root / "opportunity_rows_sidecar.csv"
        )

    if tina_rows.empty:
        merged = podio_adapted
        merge_note = "Tina report absent or no Closed/Executed rows; closings tags from Podio only."
    else:
        merged = _merge_closings_sheets(podio_adapted, tina_rows)
        merge_note = (
            f"Merged adapted Podio closings ({len(podio_adapted)} rows) with Tina Closed+Executed "
            f"({len(tina_rows)} rows) → {len(merged)} rows after dedupe by address_key+month."
        )

    merged_xlsx = work / "merged_closings_for_mapper.xlsx"
    merged.to_excel(merged_xlsx, index=False)

    charles_ready = work / "Charles_as_Decision_Mapper.csv"
    n_sms = ots.build_charles_sms_for_mapper(ots.CHARLES, charles_ready)
    sms_entries = [("Decision Maker.csv", str(charles_ready))]

    cold_path = work / "cold_calling.csv"
    copy2(ots.CWEB, cold_path)
    crm_path = work / "crm_updates.csv"
    copy2(ots.CRM, crm_path)

    result = run_patch_pipeline(
        str(cold_path),
        sms_entries,
        str(crm_path),
        closings_xlsx_path=str(merged_xlsx),
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
    n_ls = ots.write_lead_source_sidecar(closings_src, lead_csv)

    metrics = {
        "stamp_utc": stamp,
        "merge_note": merge_note,
        "inputs": {
            "podio_closings": str(closings_src),
            "tina_opportunities_report": str(tina_path) if tina_path else None,
            "adapted_podio_rows": len(podio_adapted),
            "tina_closed_executed_rows": len(tina_rows),
            "merged_rows_before_tags": len(merged),
            "closings_tag_rows": result.closings_rows,
            "adapted_skipped_no_date": n_skip,
            "usaddress_fallback_rows": n_usaddr_fb,
            "charles_sms_rows_prepared": n_sms,
            "opportunity_sidecar_all_rows": tina_sidecar_rows,
        },
        "allow_unmapped": allow_unmapped,
        "cold_unmapped": result.cold_unmapped,
        "sms_unmapped": result.sms_unmapped,
        "crm_unmapped": result.crm_unmapped,
        "crm_metrics": result.crm_metrics,
        "csv_paths": written,
        "zip_path": str(zip_path),
        "zip_bytes": zip_path.stat().st_size,
        "lead_source_sidecar_rows": n_ls,
    }
    (out_root / "ingest_metrics.json").write_text(json.dumps(metrics, indent=2), encoding="utf-8")

    (out_root / "README.txt").write_text(
        "\n".join(
            [
                "One-time REISift bundle: Podio Closings + Tina New Opportunities (Closed/Executed).",
                "",
                merge_note,
                "",
                "reisift_import.zip — same four files as Past patches.",
                "opportunity_rows_sidecar.csv — every row from the Tina export (all stages) for ops history QA;",
                "not imported by the mapper; optional manual use.",
                "",
                f"Generated UTC {stamp}.",
            ]
        ),
        encoding="utf-8",
    )

    print("OUT", out_root)
    print("ZIP", zip_path, zip_path.stat().st_size, "bytes")
    print("closings_tag_rows", result.closings_rows)
    return out_root


if __name__ == "__main__":
    main()
