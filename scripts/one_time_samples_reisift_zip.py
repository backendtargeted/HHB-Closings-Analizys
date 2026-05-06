"""
One-time ingest: Data_ingestion_samples → REISift four-CSV zip (RUNBOOK tag shapes).

Uses marketing_mapper.run_patch_pipeline + write_patch_exports (same as Past patches API).
"""

from __future__ import annotations

import json
import shutil
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path

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

SAMPLES = REPO / "Data_ingestion_samples"
CWEB = SAMPLES / "Weekly_and_monthly/Cweb Call Logs.csv"
CHARLES = SAMPLES / "Weekly_and_monthly/Charles SMS Logs.csv"
CRM = SAMPLES / "Weekly_and_monthly/weekly_podio_updates_2026-05-04.csv"
PODIO_CLOSINGS = SAMPLES / "past_patches/podio/Closings - Last view used.xlsx"

EXCLUDED_NOTE = (
    "Not in this mapper pass: podio/Seller Leads, podio/Opportunities, past_patches/Report-*.xlsx, "
    "past_patches/past_closings.xlsx (avoid duplicate closings vs Podio Closings)."
)


def _utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


# Token labels usaddress uses for US street lines (ordered parse walk builds street).
_STREET_LABELS = frozenset(
    {
        "AddressNumber",
        "StreetNamePreModifier",
        "StreetNamePreDirectional",
        "StreetName",
        "StreetNamePostDirectional",
        "StreetNamePostModifier",
        "StreetNamePostType",
        "OccupancyType",
        "OccupancyIdentifier",
        "CornerOf",
        "IntersectionSeparator",
        "LandmarkName",
        "NotAddress",
    }
)


def _usaddress_split_line(line: str) -> tuple[str, str, str, str]:
    """Return (street, city, state, zip) from a single US address string; best-effort."""
    line = sanitize_text(line)
    if not line:
        return "", "", "", ""
    try:
        import usaddress
    except ImportError:
        return line, "", "", ""
    try:
        parsed = usaddress.parse(line)
    except (usaddress.RepeatedLabelError, ValueError):
        return line, "", "", ""
    street_parts: list[str] = []
    city, state, zcode = "", "", ""
    for val, label in parsed:
        if label in _STREET_LABELS:
            street_parts.append(val)
        elif label == "PlaceName":
            city = (city + " " + val).strip()
        elif label == "StateName":
            state = (state + " " + val).strip()
        elif label == "ZipCode":
            zcode = (zcode + " " + val).strip()
    street = " ".join(street_parts).strip()
    if not street:
        street = line
    return street, city, state, zcode


def adapt_podio_closings_for_mapper(src: Path, dst_xlsx: Path) -> tuple[int, int, int]:
    """
    Podio Closings → Excel with split columns for process_closings_for_tags / REISift
    (Property address, Property city, State, Zip Code — not one blob in Address).

    If city/state/zip missing but street looks like a full line, uses usaddress (USA).

    Returns (rows_written, rows_skipped_no_date, usaddress_fallback_rows).
    """
    df0 = pd.read_excel(src, sheet_name="Closings", engine="openpyxl", nrows=0)
    phone_candidates = [
        "Phone Number - Mobile",
        "Phone Number - Work",
        "Phone Number - Home",
    ]
    phone_col = next((c for c in phone_candidates if c in df0.columns), None)
    need = ["Property - Address", "Property - City", "Date Closed"]
    missing = [c for c in need if c not in df0.columns]
    if missing:
        raise ValueError(f"Podio Closings missing columns: {missing}")

    extra = [c for c in ("Property - State", "Property - Postal Code") if c in df0.columns]
    usecols = need + extra + ([phone_col] if phone_col else [])
    df = pd.read_excel(src, sheet_name="Closings", engine="openpyxl", usecols=usecols)
    closed = pd.to_datetime(df["Date Closed"], errors="coerce")
    valid = closed.notna()
    skipped = int((~valid).sum())
    df = df.loc[valid].copy()

    prop_street: list[str] = []
    prop_city: list[str] = []
    prop_state: list[str] = []
    prop_zip: list[str] = []
    fallback_used = 0

    for _, row in df.iterrows():
        st = sanitize_text(row["Property - Address"])
        ci = sanitize_text(row.get("Property - City", ""))
        stt = sanitize_text(row.get("Property - State", ""))
        zp = sanitize_text(row.get("Property - Postal Code", ""))
        if ((not ci) or (not stt) or (not zp)) and st:
            ps, pc, pst, pz = _usaddress_split_line(st)
            if (not ci and pc) or (not stt and pst) or (not zp and pz):
                fallback_used += 1
            if not ci and pc:
                ci = pc
            if not stt and pst:
                stt = pst
            if not zp and pz:
                zp = pz
            if pc or pst or pz:
                st = ps or st
        prop_street.append(st)
        prop_city.append(ci)
        prop_state.append(stt)
        prop_zip.append(zp)

    out = pd.DataFrame(
        {
            "Property address": prop_street,
            "Property city": prop_city,
            "State": prop_state,
            "Zip Code": prop_zip,
            "Date Closed": df["Date Closed"].values,
        }
    )
    if phone_col:
        out["Phone"] = df[phone_col].map(sanitize_phone)
    else:
        out["Phone"] = ""

    dst_xlsx.parent.mkdir(parents=True, exist_ok=True)
    out.to_excel(dst_xlsx, index=False)
    return len(out), skipped, fallback_used


def build_charles_sms_for_mapper(charles_csv: Path, dst_csv: Path) -> int:
    """Charles export uses Phone 1 / Address; SMS pipeline requires Phone (+ optional Property*)."""
    df = pd.read_csv(charles_csv, low_memory=False)
    if "Phone 1" not in df.columns:
        raise ValueError("Charles SMS CSV missing Phone 1")
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
    dst_csv.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(dst_csv, index=False)
    return len(out)


def write_lead_source_sidecar(podio_closings: Path, dst_csv: Path) -> int:
    """REISift four-pack has no Lead Source column; sidecar for manual import / QA."""
    df0 = pd.read_excel(podio_closings, sheet_name="Closings", engine="openpyxl", nrows=0)
    cols = ["Property - Address", "Property - City", "Property - State", "Property - Postal Code", "Lead Source", "Date Closed"]
    use = [c for c in cols if c in df0.columns]
    if "Lead Source" not in use or "Property - Address" not in use:
        raise ValueError("Podio Closings missing Lead Source or Property - Address for sidecar")
    df = pd.read_excel(podio_closings, sheet_name="Closings", engine="openpyxl", usecols=use)
    df = df.dropna(subset=["Date Closed", "Property - Address"], how="any")
    rows = []
    for _, r in df.iterrows():
        addr = sanitize_text(r["Property - Address"])
        city = sanitize_text(r.get("Property - City", ""))
        state = sanitize_text(r.get("Property - State", ""))
        z = sanitize_text(r.get("Property - Postal Code", ""))
        rows.append(
            {
                "address_key": make_address_key(addr, city, state, z),
                "property_address": addr,
                "property_city": city,
                "property_state": state,
                "property_zip": z,
                "lead_source": sanitize_text(r.get("Lead Source", "")),
                "date_closed": pd.to_datetime(r["Date Closed"], errors="coerce"),
            }
        )
    side = pd.DataFrame(rows)
    side = side.dropna(subset=["date_closed"])
    side["date_closed"] = side["date_closed"].dt.strftime("%Y-%m-%d")
    dst_csv.parent.mkdir(parents=True, exist_ok=True)
    side.to_csv(dst_csv, index=False)
    return len(side)


def main() -> Path:
    stamp = _utc_stamp()
    out_root = REPO / "_ingest_out" / stamp
    work = out_root / "work"
    work.mkdir(parents=True, exist_ok=True)

    adapted_closings = work / "closings_for_mapper.xlsx"
    n_close, n_skip, n_usaddr_fb = adapt_podio_closings_for_mapper(PODIO_CLOSINGS, adapted_closings)

    charles_ready = work / "Charles_as_Decision_Mapper.csv"
    n_sms = build_charles_sms_for_mapper(CHARLES, charles_ready)
    sms_entries = [("Decision Maker.csv", str(charles_ready))]

    cold_path = work / "cold_calling.csv"
    shutil.copy2(CWEB, cold_path)
    crm_path = work / "crm_updates.csv"
    shutil.copy2(CRM, crm_path)

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
    n_ls = write_lead_source_sidecar(PODIO_CLOSINGS, lead_csv)

    metrics = {
        "inputs": {
            "cold_csv": str(CWEB),
            "sms_csv": str(CHARLES),
            "crm_csv": str(CRM),
            "podio_closings": str(PODIO_CLOSINGS),
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
        "excluded_from_mapper": EXCLUDED_NOTE,
    }
    meta_path = out_root / "ingest_metrics.json"
    meta_path.write_text(json.dumps(metrics, indent=2), encoding="utf-8")

    readme = out_root / "README.txt"
    readme.write_text(
        "\n".join(
            [
                "One-time REISift bundle from Data_ingestion_samples (RUNBOOK Past patches / mapper).",
                "",
                "ZIP: reisift_import.zip contains property_status_updates.csv, phone_status_tags_updates.csv,",
                "salesforce_status_tags.csv, closings_status_tags.csv.",
                "Closings rows use split Property address / city / State / Zip Code for REISift;",
                "usaddress may fill gaps when Podio omits city/state/zip (see ingest_metrics usaddress_closings_fallback_rows).",
                "",
                "Tag vocabulary: see RUNBOOK.md Tag vocabulary cheat sheet.",
                "CRM caveat: updated_on must match Salesforce-style TZ offset or rows may skip (ingest_metrics.json).",
                "",
                EXCLUDED_NOTE,
                "",
                f"Generated UTC {stamp}.",
            ]
        ),
        encoding="utf-8",
    )

    print("OUT", out_root)
    print("ZIP", zip_path, zip_path.stat().st_size, "bytes")
    print("CSV", written)
    return out_root


if __name__ == "__main__":
    main()
