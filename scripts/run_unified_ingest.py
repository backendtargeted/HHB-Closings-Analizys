"""
Unified ingest: build raw unified CSVs → journey stitch → REISift tag bundle.

Uses minimal cold/SMS/CRM stubs for property/phone CSV shells (weekly data out of scope).

Usage:
  python scripts/run_unified_ingest.py
  python scripts/run_unified_ingest.py --qa-sidecar
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "backend"))

from app.services.journey_stitch import (  # noqa: E402
    stitch_journey,
    write_mapper_closings_xlsx,
)
from app.services.marketing_mapper import (  # noqa: E402
    export_outputs,
    process_closings_for_tags,
    process_cold_calling,
    process_sms_files,
    PROPERTY_STATUS_MAPPING,
)
from app.services.reisift_tag_builder import (  # noqa: E402
    build_closed_lost_tags,
    build_sf_tags_from_crm_rows,
    merge_sf_tag_frames,
)
from app.services.unified_crm_adapter import synthesize_crm_rows  # noqa: E402
from app.services.unified_precedence import load_precedence_policy  # noqa: E402


def _utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _load_builder():
    path = REPO / "scripts" / "build_unified_raw_sources.py"
    spec = importlib.util.spec_from_file_location("build_unified_raw_sources", path)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader
    spec.loader.exec_module(mod)
    return mod


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


def _write_address_audit(events_df, closings_df, out_path: Path) -> int:
    import pandas as pd

    keys = set()
    if events_df is not None and not events_df.empty:
        keys.update(events_df["address_key"].astype(str).tolist())
    if closings_df is not None and not closings_df.empty:
        keys.update(closings_df["address_key"].astype(str).tolist())
    keys = {k for k in keys if k and k != "|||"}
    rows = []
    for key in sorted(keys):
        ev_sub = (
            events_df[events_df["address_key"] == key]
            if events_df is not None and not events_df.empty
            else pd.DataFrame()
        )
        cl_sub = (
            closings_df[closings_df["address_key"] == key]
            if closings_df is not None and not closings_df.empty
            else pd.DataFrame()
        )
        rows.append(
            {
                "address_key": key,
                "journey_events": len(ev_sub),
                "unified_closing_rows": len(cl_sub),
                "has_closing_event": bool(
                    len(ev_sub) and (ev_sub["event_kind"] == "closing").any()
                ),
                "has_closed_lost": bool(
                    len(ev_sub) and (ev_sub["event_kind"] == "closed_lost").any()
                ),
            }
        )
    audit = pd.DataFrame(rows)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    audit.to_csv(out_path, index=False)
    return len(audit)


def main() -> Path:
    parser = argparse.ArgumentParser(description="Unified ingest with journey stitch")
    parser.add_argument(
        "--qa-sidecar",
        action="store_true",
        help="Write work/journey_events.csv and work/address_audit.csv (not in zip)",
    )
    args = parser.parse_args()

    builder = _load_builder()
    policy = load_precedence_policy()
    stamp = _utc_stamp()
    out_root = REPO / "_ingest_out" / f"{stamp}_unified_ingest"

    raw_root = out_root / "raw_build"
    builder.build_unified_raw_sources(raw_root)

    unified_dir = raw_root / "unified"
    closings_csv = unified_dir / "closings.csv"
    raw_metrics_path = raw_root / "ingest_metrics.json"
    raw_metrics = json.loads(raw_metrics_path.read_text(encoding="utf-8"))

    work = out_root / "work"
    work.mkdir(parents=True, exist_ok=True)

    events_df, journey_stats = stitch_journey(unified_dir, policy)
    events_path = work / "journey_events.csv"
    events_df.to_csv(events_path, index=False)

    import pandas as pd

    closings_df = pd.read_csv(closings_csv, low_memory=False)
    mapper_xlsx = work / "closings_for_mapper.xlsx"
    raw_eligible, mapper_rows = write_mapper_closings_xlsx(closings_df, mapper_xlsx)
    deduped_removed = max(0, raw_eligible - mapper_rows)

    closings_tags_df = (
        process_closings_for_tags(str(mapper_xlsx)) if mapper_rows > 0 else pd.DataFrame()
    )

    crm_df = synthesize_crm_rows(events_df)
    sf_from_crm, sf_metrics = build_sf_tags_from_crm_rows(crm_df, policy)
    sf_lost, lost_metrics = build_closed_lost_tags(events_df, policy)
    sf_tags_df = merge_sf_tag_frames([sf_from_crm, sf_lost])

    cold_path, _crm_stub, sms_entries = _write_stubs(work)
    cold_df, _, _, _ = process_cold_calling(str(cold_path), dict(PROPERTY_STATUS_MAPPING))
    sms_df, _, _, _ = process_sms_files(sms_entries, {})

    csv_dir = out_root / "csv"
    csv_dir.mkdir(parents=True, exist_ok=True)
    written = export_outputs(
        cold_df,
        sms_df,
        sf_tags_df,
        str(csv_dir),
        allow_unmapped=True,
        closings_tags_df=closings_tags_df,
    )

    zip_path = out_root / "reisift_import.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for p in written:
            fp = Path(p)
            zf.write(fp, arcname=fp.name)

    qa_written = False
    if args.qa_sidecar:
        _write_address_audit(events_df, closings_df, work / "address_audit.csv")
        qa_written = True

    sf_rows = len(sf_tags_df) if sf_tags_df is not None and not sf_tags_df.empty else 0
    closings_tag_rows = len(closings_tags_df) if closings_tags_df is not None else 0

    metrics = {
        "stamp_utc": stamp,
        "mode": "unified_ingest",
        "raw_build_root": str(raw_root),
        "merge_note": (
            "Append-only raw ingest; journey stitch from closings + opportunities + "
            "status_snapshots; closings deduped at mapper step by address_key."
        ),
        "journey": {
            **journey_stats,
            "deduped_closings_removed": deduped_removed,
            "journey_events_path": str(events_path),
        },
        "closings_metrics": {
            "unified_raw_closings_rows": len(closings_df),
            "tag_eligible_closings_rows": raw_eligible,
            "mapper_xlsx_rows": mapper_rows,
            "closings_tag_rows": closings_tag_rows,
            "skipped_no_valid_close_date": len(closings_df) - raw_eligible,
        },
        "tags": {
            "closings_tag_rows": closings_tag_rows,
            **sf_metrics,
            **lost_metrics,
            "sf_tags_rows": sf_rows,
            "crm_synthetic_rows": len(crm_df),
        },
        "precedence": {
            "policy_id": policy.policy_id,
            "o1_unresolved": False,
            "o2_unresolved": False,
            "note": "Default field-scoped policy in config/precedence_policy.json",
        },
        "confidence_summary": journey_stats.get("confidence_summary", {}),
        "qa_sidecar_written": qa_written,
        "raw_build_totals": raw_metrics.get("unified_totals", {}),
        "per_file": raw_metrics.get("per_file", {}),
        "sample_files_inventory": raw_metrics.get("sample_files_inventory", []),
        "inputs_used": {
            "unified_dir": str(unified_dir),
            "unified_closings_csv": str(closings_csv),
            "mapper_closings_xlsx": str(mapper_xlsx),
            "journey_events_csv": str(events_path),
        },
        "allow_unmapped": True,
        "csv_paths": written,
        "zip_path": str(zip_path),
        "zip_bytes": zip_path.stat().st_size,
    }
    (out_root / "ingest_metrics.json").write_text(json.dumps(metrics, indent=2), encoding="utf-8")

    readme_lines = [
        "Unified ingest: raw unified sources → journey stitch → REISift tags.",
        "",
        f"unified_raw_closings_rows: {len(closings_df)}",
        f"mapper_closings_rows (deduped): {mapper_rows}",
        f"closings_tag_rows: {closings_tag_rows}",
        f"sf_tags_rows: {sf_rows} (from unified opps/snapshots + closed lost)",
        f"journey_events: {journey_stats.get('events_total', 0)}",
        "",
        "SF tags are synthesized from unified opportunities/status_snapshots (not weekly CRM stub).",
        "Marketing first-touch remains existing (8020) tags already in REISift.",
        "",
        "Raw build: raw_build/unified/*.csv",
    ]
    (out_root / "README.txt").write_text("\n".join(readme_lines), encoding="utf-8")

    print("OUT", out_root)
    print("ZIP", zip_path, zip_path.stat().st_size, "bytes")
    print("journey_events", journey_stats.get("events_total", 0))
    print("sf_tags_rows", sf_rows)
    print("closings_tag_rows", closings_tag_rows)
    return out_root


if __name__ == "__main__":
    main()
