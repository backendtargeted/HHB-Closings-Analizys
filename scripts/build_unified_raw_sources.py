"""
Build append-only unified raw CSVs from all Data_ingestion_samples/*.xlsx (no dedupe).

Outputs under _ingest_out/<UTC>_unified/:
  raw/<source_file>.csv          — per-file normalized extracts
  unified/closings.csv
  unified/opportunities.csv
  unified/status_snapshots.csv
  ingest_metrics.json
"""

from __future__ import annotations

import importlib.util
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "backend"))

from app.services.marketing_mapper import (  # noqa: E402
    make_address_key,
    sanitize_phone,
    sanitize_text,
)

SAMPLES = REPO / "Data_ingestion_samples"
EXCLUDE_PREFIX = "Weekly_and_monthly/"

CLOSINGS_COLUMNS = [
    "source_file",
    "source_row_id",
    "source_system",
    "source_sheet",
    "property_address",
    "property_city",
    "property_state",
    "property_zip",
    "date_closed",
    "phone",
    "stage",
    "lead_source",
    "opportunity_name",
    "account_name",
    "address_key",
    "has_valid_close_date",
]

OPPORTUNITIES_COLUMNS = [
    "source_file",
    "source_row_id",
    "source_system",
    "stage",
    "close_date",
    "created_date",
    "lead_source",
    "opportunity_name",
    "account_name",
    "property_address",
    "property_city",
    "property_state",
    "property_zip",
    "phone",
    "address_key",
]

STATUS_SNAPSHOT_COLUMNS = [
    "source_file",
    "source_row_id",
    "source_system",
    "source_sheet",
    "entity_type",
    "stage",
    "opportunity_name",
    "account_name",
    "property_address",
    "property_city",
    "property_state",
    "property_zip",
    "close_date",
    "created_date",
    "lead_source",
    "phone",
    "address_key",
]


def _utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _load_one_time_samples():
    path = REPO / "scripts" / "one_time_samples_reisift_zip.py"
    spec = importlib.util.spec_from_file_location("one_time_samples_reisift_zip", path)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader
    spec.loader.exec_module(mod)
    return mod


def _discover_xlsx() -> list[Path]:
    files: list[Path] = []
    seen: set[str] = set()
    for p in sorted(SAMPLES.rglob("*.xlsx")):
        rel = p.relative_to(SAMPLES).as_posix()
        if rel.startswith(EXCLUDE_PREFIX):
            continue
        key = rel.lower()
        if key in seen:
            continue
        seen.add(key)
        files.append(p)
    return files


def _safe_raw_name(source_file: str) -> str:
    stem = Path(source_file).stem
    return re.sub(r"[^\w\-.]+", "_", stem) + ".csv"


def _first_phone(*values: object) -> str:
    for v in values:
        p = sanitize_phone(v)
        if len(p) > 5:
            return p
    return ""


def _split_address(street: str, city: str, state: str, zip_code: str, usaddress_fn) -> tuple[str, str, str, str]:
    st = sanitize_text(street)
    ci = sanitize_text(city)
    stt = sanitize_text(state)
    zp = sanitize_text(zip_code)
    if ((not ci) or (not stt) or (not zp)) and st:
        ps, pc, pst, pz = usaddress_fn(st)
        if not ci and pc:
            ci = pc
        if not stt and pst:
            stt = pst
        if not zp and pz:
            zp = pz
        if pc or pst or pz:
            st = ps or st
    return st, ci, stt, zp


def _format_date(val: object) -> str:
    if pd.isna(val):
        return ""
    ts = pd.to_datetime(val, errors="coerce")
    if pd.isna(ts):
        return sanitize_text(val)
    return ts.strftime("%Y-%m-%d")


def _has_valid_close(val: object) -> bool:
    return pd.notna(pd.to_datetime(val, errors="coerce"))


def _address_key_row(addr: str, city: str, state: str, zip_code: str) -> str:
    return make_address_key(addr, city, state, zip_code)


def _sf_street_from_row(r: pd.Series, *, allow_opportunity_name: bool) -> str:
    street = r.get("Address (Street)") or r.get("Address") or r.get("Billing Street") or ""
    street = sanitize_text(street)
    if not street and allow_opportunity_name:
        street = sanitize_text(r.get("Opportunity Name", ""))
    return street


def _main_sheet(path: Path, kind: str) -> str:
    xl = pd.ExcelFile(path, engine="openpyxl")
    names = xl.sheet_names
    if kind == "podio_closings":
        return "Closings"
    if kind == "podio_opportunities":
        return "Opportunities"
    if kind == "podio_seller_leads":
        return "Seller Leads"
    if kind == "tina_report":
        for n in names:
            if "Tina" in n:
                return n
    if kind in ("sf_report", "sf_past_closings"):
        if "Report" in names:
            return "Report"
    return names[0]


def _classify_file(path: Path) -> str:
    name = path.name
    if name == "Closings - Last view used.xlsx":
        return "podio_closings"
    if name.startswith("New Opportunities Report - Tina"):
        return "tina_report"
    if name == "past_closings.xlsx":
        return "sf_past_closings"
    if name.startswith("Report-"):
        return "sf_report"
    if name == "Opportunities - All Opportunities.xlsx":
        return "podio_opportunities"
    if name == "Seller Leads - All Seller Leads.xlsx":
        return "podio_seller_leads"
    return "unknown"


def _empty_frame(columns: list[str]) -> pd.DataFrame:
    return pd.DataFrame(columns=columns)


def _process_podio_closings(path: Path, usaddress_fn) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    sheet = _main_sheet(path, "podio_closings")
    df = pd.read_excel(path, sheet_name=sheet, engine="openpyxl")
    raw_rows: list[dict] = []
    closings: list[dict] = []
    source_file = path.name

    phone_candidates = ["Phone Number - Mobile", "Phone Number - Work", "Phone Number - Home"]
    phone_col = next((c for c in phone_candidates if c in df.columns), None)
    stage_col = "Stage" if "Stage" in df.columns else ("Master Stage" if "Master Stage" in df.columns else "")

    for idx, r in df.iterrows():
        source_row_id = int(idx) + 2  # Excel 1-based + header
        st, ci, stt, zp = _split_address(
            r.get("Property - Address", ""),
            r.get("Property - City", ""),
            r.get("Property - State", ""),
            r.get("Property - Postal Code", ""),
            usaddress_fn,
        )
        phone = _first_phone(r.get(phone_col)) if phone_col else ""
        stage = sanitize_text(r.get(stage_col, "")) if stage_col else ""
        lead_source = sanitize_text(r.get("Lead Source", ""))
        date_closed_raw = r.get("Date Closed")
        valid_close = _has_valid_close(date_closed_raw)

        row_common = {
            "source_file": source_file,
            "source_row_id": source_row_id,
            "property_address": st,
            "property_city": ci,
            "property_state": stt,
            "property_zip": zp,
            "phone": phone,
            "stage": stage,
            "lead_source": lead_source,
            "opportunity_name": "",
            "account_name": "",
            "address_key": _address_key_row(st, ci, stt, zp),
        }
        raw_rows.append(
            {
                **row_common,
                "source_system": "podio_closings",
                "source_sheet": sheet,
                "date_closed": _format_date(date_closed_raw),
                "has_valid_close_date": valid_close,
            }
        )
        closings.append(
            {
                **row_common,
                "source_system": "podio_closings",
                "source_sheet": sheet,
                "date_closed": _format_date(date_closed_raw),
                "has_valid_close_date": valid_close,
            }
        )

    raw_df = pd.DataFrame(raw_rows)
    closings_df = pd.DataFrame(closings, columns=CLOSINGS_COLUMNS)
    return raw_df, closings_df, _empty_frame(OPPORTUNITIES_COLUMNS), _empty_frame(STATUS_SNAPSHOT_COLUMNS)


def _process_sf_report_like(
    path: Path,
    source_system: str,
    kind: str,
    *,
    allow_opportunity_name_for_address: bool,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    sheet = _main_sheet(path, kind)
    df = pd.read_excel(path, sheet_name=sheet, engine="openpyxl")
    source_file = path.name
    raw_rows: list[dict] = []
    closings: list[dict] = []
    opportunities: list[dict] = []
    snapshots: list[dict] = []

    for idx, r in df.iterrows():
        source_row_id = int(idx) + 2
        st = _sf_street_from_row(r, allow_opportunity_name=allow_opportunity_name_for_address)
        ci = sanitize_text(r.get("Address (City)", ""))
        stt = ""
        zp = sanitize_text(str(r.get("Address (ZIP/Postal Code)", "")))
        phone = _first_phone(r.get("Opportunity Owner: Mobile Phone"), r.get("Opportunity Owner: Phone"))
        stage = sanitize_text(r.get("Stage", ""))
        lead_source = sanitize_text(r.get("Lead Source", ""))
        opp_name = sanitize_text(r.get("Opportunity Name", ""))
        acct_name = sanitize_text(r.get("Account Name", ""))
        close_raw = r.get("Close Date")
        created_raw = r.get("Created Date")
        valid_close = _has_valid_close(close_raw)
        addr_key = _address_key_row(st, ci, stt, zp)

        raw_rows.append(
            {
                "source_file": source_file,
                "source_row_id": source_row_id,
                "source_system": source_system,
                "source_sheet": sheet,
                "stage": stage,
                "close_date": _format_date(close_raw),
                "created_date": _format_date(created_raw),
                "lead_source": lead_source,
                "opportunity_name": opp_name,
                "account_name": acct_name,
                "property_address": st,
                "property_city": ci,
                "property_state": stt,
                "property_zip": zp,
                "phone": phone,
                "address_key": addr_key,
                "has_valid_close_date": valid_close,
            }
        )

        opportunities.append(
            {
                "source_file": source_file,
                "source_row_id": source_row_id,
                "source_system": source_system,
                "stage": stage,
                "close_date": _format_date(close_raw),
                "created_date": _format_date(created_raw),
                "lead_source": lead_source,
                "opportunity_name": opp_name,
                "account_name": acct_name,
                "property_address": st,
                "property_city": ci,
                "property_state": stt,
                "property_zip": zp,
                "phone": phone,
                "address_key": addr_key,
            }
        )

        snapshots.append(
            {
                "source_file": source_file,
                "source_row_id": source_row_id,
                "source_system": source_system,
                "source_sheet": sheet,
                "entity_type": "opportunity_report",
                "stage": stage,
                "opportunity_name": opp_name,
                "account_name": acct_name,
                "property_address": st,
                "property_city": ci,
                "property_state": stt,
                "property_zip": zp,
                "close_date": _format_date(close_raw),
                "created_date": _format_date(created_raw),
                "lead_source": lead_source,
                "phone": phone,
                "address_key": addr_key,
            }
        )

        if valid_close:
            closings.append(
                {
                    "source_file": source_file,
                    "source_row_id": source_row_id,
                    "source_system": source_system,
                    "source_sheet": sheet,
                    "property_address": st,
                    "property_city": ci,
                    "property_state": stt,
                    "property_zip": zp,
                    "date_closed": _format_date(close_raw),
                    "phone": phone,
                    "stage": stage,
                    "lead_source": lead_source,
                    "opportunity_name": opp_name,
                    "account_name": acct_name,
                    "address_key": addr_key,
                    "has_valid_close_date": True,
                }
            )

    return (
        pd.DataFrame(raw_rows),
        pd.DataFrame(closings, columns=CLOSINGS_COLUMNS),
        pd.DataFrame(opportunities, columns=OPPORTUNITIES_COLUMNS),
        pd.DataFrame(snapshots, columns=STATUS_SNAPSHOT_COLUMNS),
    )


def _process_podio_opportunities(path: Path, usaddress_fn) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    sheet = _main_sheet(path, "podio_opportunities")
    df = pd.read_excel(path, sheet_name=sheet, engine="openpyxl")
    source_file = path.name
    raw_rows: list[dict] = []
    opportunities: list[dict] = []

    for idx, r in df.iterrows():
        source_row_id = int(idx) + 2
        st, ci, stt, zp = _split_address(
            r.get("Property Address - Address", ""),
            r.get("Property Address - City", ""),
            r.get("Property Address - State", ""),
            r.get("Property Address - Postal Code", ""),
            usaddress_fn,
        )
        phone = _first_phone(r.get("Phone (Salesforce) - Mobile"), r.get("Phone (Salesforce) - Home"))
        stage = sanitize_text(r.get("Stage", ""))
        lead_source = sanitize_text(r.get("Lead Source", ""))
        created_raw = r.get("Created Date (salesforce)") or r.get("Created on") or r.get("Created On")
        addr_key = _address_key_row(st, ci, stt, zp)

        row = {
            "source_file": source_file,
            "source_row_id": source_row_id,
            "source_system": "podio_opportunities",
            "stage": stage,
            "close_date": "",
            "created_date": _format_date(created_raw),
            "lead_source": lead_source,
            "opportunity_name": "",
            "account_name": "",
            "property_address": st,
            "property_city": ci,
            "property_state": stt,
            "property_zip": zp,
            "phone": phone,
            "address_key": addr_key,
        }
        raw_rows.append({**row, "source_sheet": sheet})
        opportunities.append(row)

    return (
        pd.DataFrame(raw_rows),
        _empty_frame(CLOSINGS_COLUMNS),
        pd.DataFrame(opportunities, columns=OPPORTUNITIES_COLUMNS),
        _empty_frame(STATUS_SNAPSHOT_COLUMNS),
    )


def _process_podio_seller_leads(path: Path, usaddress_fn) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    sheet = _main_sheet(path, "podio_seller_leads")
    df = pd.read_excel(path, sheet_name=sheet, engine="openpyxl")
    source_file = path.name
    raw_rows: list[dict] = []
    snapshots: list[dict] = []

    for idx, r in df.iterrows():
        source_row_id = int(idx) + 2
        st, ci, stt, zp = _split_address(
            r.get("Address - Address", ""),
            r.get("Address - City", ""),
            r.get("Address - State", ""),
            r.get("Address - Postal Code", ""),
            usaddress_fn,
        )
        phone = _first_phone(
            r.get("Phone (Salesforce) - Mobile"),
            r.get("Phone (Salesforce) - Home"),
            r.get("Seller Phone - Home"),
            r.get("Seller Phone - Work"),
        )
        stage = sanitize_text(r.get("Stage", ""))
        lead_source = sanitize_text(r.get("Lead Source", ""))
        created_raw = r.get("Created Date (Salesforce)") or r.get("Created on") or r.get("Date Lead Came in")
        addr_key = _address_key_row(st, ci, stt, zp)

        snap = {
            "source_file": source_file,
            "source_row_id": source_row_id,
            "source_system": "podio_seller_leads",
            "source_sheet": sheet,
            "entity_type": "seller_lead",
            "stage": stage,
            "opportunity_name": "",
            "account_name": "",
            "property_address": st,
            "property_city": ci,
            "property_state": stt,
            "property_zip": zp,
            "close_date": "",
            "created_date": _format_date(created_raw),
            "lead_source": lead_source,
            "phone": phone,
            "address_key": addr_key,
        }
        raw_rows.append(snap)
        snapshots.append(snap)

    return (
        pd.DataFrame(raw_rows),
        _empty_frame(CLOSINGS_COLUMNS),
        _empty_frame(OPPORTUNITIES_COLUMNS),
        pd.DataFrame(snapshots, columns=STATUS_SNAPSHOT_COLUMNS),
    )


def _process_file(path: Path, usaddress_fn) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, str]:
    kind = _classify_file(path)
    if kind == "podio_closings":
        return (*_process_podio_closings(path, usaddress_fn), kind)
    if kind in ("tina_report", "sf_report"):
        return (
            *_process_sf_report_like(
                path,
                "salesforce_tina" if kind == "tina_report" else "salesforce_report",
                kind,
                allow_opportunity_name_for_address=True,
            ),
            kind,
        )
    if kind == "sf_past_closings":
        return (
            *_process_sf_report_like(
                path,
                "salesforce_past_closings",
                kind,
                allow_opportunity_name_for_address=True,
            ),
            kind,
        )
    if kind == "podio_opportunities":
        return (*_process_podio_opportunities(path, usaddress_fn), kind)
    if kind == "podio_seller_leads":
        return (*_process_podio_seller_leads(path, usaddress_fn), kind)
    raise ValueError(f"Unclassified sample file: {path}")


def build_unified_raw_sources(out_root: Path | None = None) -> Path:
    ots = _load_one_time_samples()
    usaddress_fn = ots._usaddress_split_line

    stamp = _utc_stamp()
    if out_root is None:
        out_root = REPO / "_ingest_out" / f"{stamp}_unified"
    raw_dir = out_root / "raw"
    unified_dir = out_root / "unified"
    raw_dir.mkdir(parents=True, exist_ok=True)
    unified_dir.mkdir(parents=True, exist_ok=True)

    files = _discover_xlsx()
    all_closings: list[pd.DataFrame] = []
    all_opps: list[pd.DataFrame] = []
    all_snapshots: list[pd.DataFrame] = []
    per_file_metrics: dict[str, dict] = {}
    inventory: list[dict] = []

    for path in files:
        rel = path.relative_to(SAMPLES).as_posix()
        raw_df, closings_df, opps_df, snap_df, kind = _process_file(path, usaddress_fn)

        raw_path = raw_dir / _safe_raw_name(path.name)
        raw_df.to_csv(raw_path, index=False)

        all_closings.append(closings_df)
        all_opps.append(opps_df)
        all_snapshots.append(snap_df)

        per_file_metrics[path.name] = {
            "path": rel,
            "kind": kind,
            "raw_rows": len(raw_df),
            "closings_rows": len(closings_df),
            "opportunities_rows": len(opps_df),
            "status_snapshot_rows": len(snap_df),
            "raw_csv": str(raw_path),
        }
        inventory.append(
            {
                "path": rel,
                "used": True,
                "kind": kind,
                "reason": f"Ingested into unified raw layer ({kind}).",
            }
        )

    closings_unified = pd.concat(all_closings, ignore_index=True) if all_closings else _empty_frame(CLOSINGS_COLUMNS)
    opps_unified = pd.concat(all_opps, ignore_index=True) if all_opps else _empty_frame(OPPORTUNITIES_COLUMNS)
    snap_unified = pd.concat(all_snapshots, ignore_index=True) if all_snapshots else _empty_frame(STATUS_SNAPSHOT_COLUMNS)

    closings_path = unified_dir / "closings.csv"
    opps_path = unified_dir / "opportunities.csv"
    snap_path = unified_dir / "status_snapshots.csv"
    closings_unified.to_csv(closings_path, index=False)
    opps_unified.to_csv(opps_path, index=False)
    snap_unified.to_csv(snap_path, index=False)

    tag_eligible = int(closings_unified["has_valid_close_date"].sum()) if len(closings_unified) else 0

    metrics = {
        "stamp_utc": stamp,
        "mode": "unified_raw_sources",
        "samples_root": str(SAMPLES),
        "excluded_prefix": EXCLUDE_PREFIX,
        "output_root": str(out_root),
        "unified_totals": {
            "closings_rows": len(closings_unified),
            "closings_tag_eligible_rows": tag_eligible,
            "closings_skipped_no_valid_date": len(closings_unified) - tag_eligible,
            "opportunities_rows": len(opps_unified),
            "status_snapshot_rows": len(snap_unified),
            "source_files_count": len(files),
        },
        "per_file": per_file_metrics,
        "unified_paths": {
            "closings": str(closings_path),
            "opportunities": str(opps_path),
            "status_snapshots": str(snap_path),
        },
        "sample_files_inventory": inventory,
    }
    (out_root / "ingest_metrics.json").write_text(json.dumps(metrics, indent=2), encoding="utf-8")

    print("OUT", out_root)
    print("closings", len(closings_unified), "tag_eligible", tag_eligible)
    print("opportunities", len(opps_unified))
    print("status_snapshots", len(snap_unified))
    return out_root


def unified_closings_to_mapper_xlsx(closings_csv: Path, dst_xlsx: Path) -> tuple[int, int]:
    """Filter tag-eligible closings → mapper Excel (Property address, city, State, Zip, Date Closed, Phone)."""
    df = pd.read_csv(closings_csv, low_memory=False)
    total = len(df)
    if "has_valid_close_date" in df.columns:
        eligible = df[df["has_valid_close_date"].astype(str).str.lower().isin(["true", "1", "yes"])].copy()
    else:
        eligible = df[df["date_closed"].astype(str).str.len() > 0].copy()

    out = pd.DataFrame(
        {
            "Property address": eligible["property_address"].map(sanitize_text),
            "Property city": eligible["property_city"].map(sanitize_text),
            "State": eligible["property_state"].map(sanitize_text),
            "Zip Code": eligible["property_zip"].map(sanitize_text),
            "Date Closed": pd.to_datetime(eligible["date_closed"], errors="coerce"),
            "Phone": eligible["phone"].map(sanitize_phone),
        }
    )
    out = out[out["Date Closed"].notna()].copy()
    dst_xlsx.parent.mkdir(parents=True, exist_ok=True)
    out.to_excel(dst_xlsx, index=False)
    return total, len(out)


def main() -> Path:
    return build_unified_raw_sources()


if __name__ == "__main__":
    main()
