"""
Run sample Data_ingestion_inputs through marketing_mapper and report unmapped
statuses with row counts (cold, SMS-as-Decision-Maker, CRM).
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "backend"))

from app.services.marketing_mapper import (  # noqa: E402
    CRM_STATUS_TO_PHONE_STATUS_TAG,
    CRM_STATUS_TO_PROPERTY_STATUS,
    PHONE_STATUS_TAG_MAPPING,
    PROPERTY_STATUS_MAPPING,
    process_cold_calling,
    process_crm_updates,
    process_sms_files,
    sanitize_phone,
    sanitize_text,
)

SAMPLES = REPO / "Data_ingestion_samples"
CWEB = SAMPLES / "Weekly_and_monthly/Cweb Call Logs.csv"
CHARLES = SAMPLES / "Weekly_and_monthly/Charles SMS Logs.csv"
CRM = SAMPLES / "Weekly_and_monthly/weekly_podio_updates_2026-05-04.csv"


def _charles_as_decision_maker_csv(dst: Path) -> int:
    df = pd.read_csv(CHARLES, low_memory=False)
    out = pd.DataFrame(
        {
            "Phone": df["Phone 1"].map(sanitize_phone),
            "Property address": df["Address"].map(sanitize_text) if "Address" in df.columns else "",
            "Property city": df["City"].map(sanitize_text) if "City" in df.columns else "",
            "Property state": df["State"].map(sanitize_text) if "State" in df.columns else "",
            "Property zip": df["Zip Code"].astype(str).map(sanitize_text) if "Zip Code" in df.columns else "",
        }
    )
    out = out[out["Phone"].str.len() > 5]
    dst.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(dst, index=False)
    return len(out)


def _crm_row_unmapped(norm: object) -> bool:
    s = str(norm).strip() if norm is not None and not (isinstance(norm, float) and pd.isna(norm)) else ""
    if not s:
        return False
    return s not in CRM_STATUS_TO_PROPERTY_STATUS and s not in CRM_STATUS_TO_PHONE_STATUS_TAG


def main() -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    work = REPO / "_ingest_out" / f"unmapped_report_{stamp}"
    work.mkdir(parents=True, exist_ok=True)
    charles_ready = work / "Charles_as_Decision_Mapper.csv"
    n_sms_rows = _charles_as_decision_maker_csv(charles_ready)

    cold_df, cold_in, cold_out_counts, cold_un_list = process_cold_calling(
        str(CWEB), PROPERTY_STATUS_MAPPING
    )
    cold_bad = cold_df[cold_df["status"] == ""]
    cold_counts = cold_bad["normalized_status"].value_counts().to_dict()
    cold_top_raw = (
        cold_bad.groupby("normalized_status")["source_status"]
        .agg(lambda s: s.value_counts().head(5).to_dict())
        .to_dict()
    )

    sms_df, sms_in, sms_out_counts, sms_un_list = process_sms_files(
        [("Decision Maker.csv", str(charles_ready))],
        PHONE_STATUS_TAG_MAPPING,
    )
    sms_bad = sms_df[sms_df["phone_status"] == ""]
    sms_counts = sms_bad["normalized_status"].value_counts().to_dict()

    crm_df, crm_un_list = process_crm_updates(str(CRM))
    crm_mask = crm_df["crm_normalized_status"].map(_crm_row_unmapped)
    crm_counts = crm_df.loc[crm_mask, "crm_normalized_status"].value_counts().to_dict()

    report = {
        "generated_utc": stamp,
        "inputs": {"cold": str(CWEB), "sms_charles_rows": n_sms_rows, "crm": str(CRM)},
        "cold": {
            "unmapped_unique": cold_un_list,
            "unmapped_row_counts_by_normalized": cold_counts,
            "sample_raw_log_types_top5_per_normalized": cold_top_raw,
            "total_cold_rows": len(cold_df),
            "rows_empty_status": int((cold_df["status"] == "").sum()),
        },
        "sms_decision_maker_filename": {
            "unmapped_unique": sms_un_list,
            "unmapped_row_counts_by_normalized": sms_counts,
            "total_sms_rows": len(sms_df),
            "rows_empty_phone_status": int((sms_df["phone_status"] == "").sum()),
        },
        "crm": {
            "unmapped_unique": crm_un_list,
            "unmapped_row_counts_by_normalized": crm_counts,
            "total_crm_rows": len(crm_df),
            "rows_unmapped_status": int(crm_mask.sum()),
        },
    }

    out_path = work / "unmapped_status_report.json"
    out_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    txt = work / "unmapped_status_report.txt"
    lines = [
        f"Unmapped status report {stamp}",
        "",
        "=== COLD (Cweb) — rows with empty mapped property status ===",
        f"Rows: {report['cold']['rows_empty_status']} / {report['cold']['total_cold_rows']}",
    ]
    for k, v in sorted(cold_counts.items(), key=lambda x: -x[1]):
        lines.append(f"  {v:>8}  {k!r}")
    lines += ["", "=== SMS (Charles as Decision Maker.csv) — empty phone_status ==="]
    lines.append(
        f"Rows: {report['sms_decision_maker_filename']['rows_empty_phone_status']} / "
        f"{report['sms_decision_maker_filename']['total_sms_rows']}"
    )
    for k, v in sorted(sms_counts.items(), key=lambda x: -x[1]):
        lines.append(f"  {v:>8}  {k!r}")
    lines += ["", "=== CRM — normalized leadstatus not in CRM_STATUS maps ==="]
    lines.append(
        f"Rows: {report['crm']['rows_unmapped_status']} / {report['crm']['total_crm_rows']}"
    )
    for k, v in sorted(crm_counts.items(), key=lambda x: -x[1]):
        lines.append(f"  {v:>8}  {k!r}")
    txt.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print("\n".join(lines))
    print("\nWROTE", out_path)
    print("WROTE", txt)
    return work


if __name__ == "__main__":
    main()
