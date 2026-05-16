"""
Marketing ingestion mapper (server-side).

Ported from marketing_ingestion_mapper.py (Tk GUI). Keep in sync when mappings change.

Outputs REISift-oriented CSVs:
- property_status_updates.csv
- phone_status_tags_updates.csv
- salesforce_status_tags.csv
- closings_status_tags.csv (when closings Excel is provided)
"""

import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import pandas as pd


# ---------------------------------------------------------------------------
# Mappings
# ---------------------------------------------------------------------------

PROPERTY_STATUS_MAPPING: Dict[str, str] = {
    # Salesforce / CRM
    "converted": "Under Contract",
    "new": "Lead",
    "follow up": "Follow Up",
    "not yet reached": "Prospecting",
    "dead deal": "Dead Deal",
    # CC (Call)
    "decision maker - lead": "Lead",
    "callback": "Lead",
    "spanish speaker": "Follow Up",
    "influencer": "Follow Up",
    "listed property": "On Market Listing",
    "dnc - decision maker": "DNC",
    "dnc - unknown": "DNC",
    "wrong number": "Wrong Number",
    "voicemail": "Follow Up",
    "dead call": "Dead Deal",
    "dead call / dead deal": "Dead Deal",
    "agent": "DNC",
    # SMS
    "decision maker": "Lead",
    "maybe later": "Follow Up",
    "abv mv": "Follow Up",
    "abv mv (sms)": "Follow Up",
    "bluffer": "DNC",
    "bluffer (sms)": "DNC",
    "not interested": "Not Interested",
    "dnc": "DNC",
    "sold": "Sold",
}

PHONE_STATUS_TAG_MAPPING: Dict[str, Tuple[str, str]] = {
    # Salesforce / CRM
    "converted": ("CORRECT", "Contacted"),
    "new": ("CORRECT", "Contacted"),
    "follow up": ("CORRECT", "Contacted"),
    "not yet reached": ("UNKNOWN", "Voicemail"),
    "dead deal": ("DEAD", "Dead Number"),
    # CC (Call)
    "decision maker - lead": ("CORRECT", "Contacted"),
    "wrong number": ("WRONG", "Wrong Number"),
    "dnc - decision maker": ("CORRECT DNC", "DNC"),
    "dnc - unknown": ("DNC", "DNC"),
    "dead call": ("DEAD", "Dead Number"),
    "dead call / dead deal": ("DEAD", "Dead Number"),
    "dead call / disconnected": ("DEAD", "Dead Number"),
    "spanish speaker": ("CORRECT", "Contacted"),
    "agent": ("WRONG", "DNC"),
    "voicemail": ("NO ANSWER", "Voicemail"),
    "callback": ("CORRECT", "Contacted"),
    "influencer": ("CORRECT", "Contacted"),
    "listed property": ("CORRECT", "Contacted"),
    # SMS
    "decision maker": ("CORRECT", "Contacted"),
    "maybe later": ("CORRECT", "Contacted"),
    "abv mv": ("CORRECT", "Contacted"),
    "abv mv (sms)": ("CORRECT", "Contacted"),
    "bluffer": ("CORRECT", "DNC"),
    "bluffer (sms)": ("CORRECT", "DNC"),
    "maybe later (sms)": ("CORRECT", "Contacted"),
    "not interested": ("CORRECT", "Contacted"),
    "dnc": ("DNC", "DNC"),
}


# Optional aliases to absorb common variants found in raw files.
STATUS_ALIASES: Dict[str, str] = {
    # Canonical variants observed in source files.
    "decision maker": "decision maker - lead",
    "decision maker - nyi": "decision maker - lead",
    "abv mv": "abv mv (sms)",
    "bluffer": "bluffer (sms)",
    "maybe later": "maybe later (sms)",
    "not interested (sms)": "not interested",
    "dnc": "dnc - unknown",
    # Formatting variants.
    "dnc (any)": "dnc",
    "follow-up": "follow up",
    "dead call": "dead call / dead deal",
    "dead deal": "dead call / dead deal",
}


REQUIRED_COLD_COLUMNS = ["Phone", "Address", "City", "State", "Zip Code", "Log Type"]
CRM_STATUS_TO_PROPERTY_STATUS: Dict[str, str] = {
    "converted": "Under Contract",
    "new": "Lead",
    "follow up": "Follow Up",
    "not yet reached": "Prospecting",
    "dead deal": "Dead Deal",
}

CRM_STATUS_TO_PHONE_STATUS_TAG: Dict[str, Tuple[str, str]] = {
    "converted": ("CORRECT", "Contacted"),
    "new": ("CORRECT", "Contacted"),
    "follow up": ("CORRECT", "Contacted"),
    "not yet reached": ("UNKNOWN", "Voicemail"),
    "dead deal": ("DEAD", "Dead Number"),
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def smart_read_csv(file_path: str) -> pd.DataFrame:
    """Read CSV with robust encoding fallback."""
    encodings = ["utf-8", "utf-8-sig", "cp1252", "latin1", "iso-8859-1"]
    last_error = None
    for enc in encodings:
        try:
            return pd.read_csv(file_path, encoding=enc, low_memory=False)
        except Exception as exc:
            last_error = exc
    raise ValueError(f"Could not read CSV file: {file_path}. Last error: {last_error}")


def normalize_status(raw: object) -> str:
    """Normalize raw status text for stable dictionary lookup."""
    if pd.isna(raw):
        return ""
    value = str(raw).strip().lower()
    if not value:
        return ""
    value = re.sub(r"\s+", " ", value)
    value = value.replace("_", " ")
    value = value.replace("–", "-")
    value = re.sub(r"\s*-\s*", " - ", value)
    value = re.sub(r"\s+", " ", value).strip()
    value = STATUS_ALIASES.get(value, value)
    return value


def sanitize_phone(raw: object) -> str:
    """Keep digits only; remove leading US country code when length is 11."""
    if pd.isna(raw):
        return ""
    digits = re.sub(r"\D", "", str(raw))
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    return digits


def sanitize_text(raw: object) -> str:
    if pd.isna(raw):
        return ""
    return re.sub(r"\s+", " ", str(raw).strip())


def make_address_key(address: object, city: object, state: object, zip_code: object) -> str:
    """Create normalized address key used for matching across sources."""
    addr = sanitize_text(address).lower()
    city_clean = sanitize_text(city).lower()
    state_clean = sanitize_text(state).lower()
    zip_clean = sanitize_text(zip_code).lower()
    return f"{addr}|{city_clean}|{state_clean}|{zip_clean}"


def strip_trailing_count_from_filename(filename: str) -> str:
    """
    Converts 'Wrong Number (6).csv' -> 'Wrong Number'
    and keeps normal names unchanged.
    """
    stem = Path(filename).stem
    return re.sub(r"\s*\(\d+\)$", "", stem).strip()


def preview_counts(series: pd.Series) -> Dict[str, int]:
    out: Dict[str, int] = {}
    for val in series.fillna(""):
        key = str(val)
        out[key] = out.get(key, 0) + 1
    return dict(sorted(out.items(), key=lambda item: (-item[1], item[0])))


def find_column_name(df: pd.DataFrame, candidates: List[str]) -> Optional[str]:
    """Find first matching column (case-insensitive)."""
    normalized = {col.lower(): col for col in df.columns}
    for name in candidates:
        if name.lower() in normalized:
            return normalized[name.lower()]
    return None


def parse_any_date_to_ymd(raw: object) -> Tuple[str, bool]:
    """Parse date-like value and return (YYYY-MM-DD, is_valid)."""
    if pd.isna(raw):
        return "", False
    text = str(raw).strip()
    if not text:
        return "", False
    parsed = pd.to_datetime(text, errors="coerce", utc=False)
    if pd.isna(parsed):
        return "", False
    return parsed.strftime("%Y-%m-%d"), True


def parse_updated_on_to_ymd(raw: object) -> Tuple[str, bool]:
    """Parse Salesforce updated_on format like 2026-04-27T10:47:44.523-0400."""
    if pd.isna(raw):
        return "", False
    text = str(raw).strip()
    if not text:
        return "", False
    try:
        parsed = datetime.strptime(text, "%Y-%m-%dT%H:%M:%S.%f%z")
        return parsed.strftime("%Y-%m-%d"), True
    except ValueError:
        return "", False


def build_salesforce_tags(crm_row: pd.Series) -> Tuple[List[Dict[str, str]], List[Tuple[str, str]]]:
    """
    Build independent Salesforce tags.
    Returns:
      - list of tag rows
      - list of validation skips: [(status, reason), ...]
    """
    tag_rows: List[Dict[str, str]] = []
    skips: List[Tuple[str, str]] = []

    status_label = crm_row["crm_source_status"]
    normalized = crm_row["crm_normalized_status"]
    updated_on_parsed = crm_row["updated_on_parsed"]
    leadcreated_parsed = crm_row["leadcreateddate_parsed"]

    # UPDATED tag: independent, only depends on updated_on validity.
    if crm_row["updated_on_valid"]:
        tag_rows.append(
            {
                "salesforce_tag": f"(SF) UPDATED - {status_label} - {updated_on_parsed}",
                "tag_type": "updated_status",
                "row_validation_status": "ok",
                "row_validation_reason": "",
            }
        )
    else:
        skips.append((status_label, "skipped_updated_on"))

    # CREATED/STATUS tag: for Lead status rows only, depends on leadcreateddate validity.
    if normalized in {"new", "decision maker - lead"}:
        if crm_row["leadcreateddate_valid"]:
            tag_rows.append(
                {
                    "salesforce_tag": f"(SF) STATUS - {status_label} - {leadcreated_parsed}",
                    "tag_type": "created_status",
                    "row_validation_status": "ok",
                    "row_validation_reason": "",
                }
            )
        else:
            skips.append((status_label, "skipped_created_date"))

    return tag_rows, skips


# ---------------------------------------------------------------------------
# Core processing
# ---------------------------------------------------------------------------

def process_cold_calling(
    cold_file: str, property_mapping: Dict[str, str]
) -> Tuple[pd.DataFrame, Dict[str, int], Dict[str, int], List[str]]:
    """
    Returns:
    - output dataframe
    - status counts
    - mapped status counts
    - unmapped normalized statuses
    """
    df = smart_read_csv(cold_file)

    missing_cols = [c for c in REQUIRED_COLD_COLUMNS if c not in df.columns]
    if missing_cols:
        raise ValueError(f"Cold Calling file is missing columns: {', '.join(missing_cols)}")

    status_norm = df["Log Type"].apply(normalize_status)
    mapped = status_norm.map(property_mapping)

    out = pd.DataFrame(
        {
            "phone": df["Phone"].apply(sanitize_phone),
            "address": df["Address"].apply(sanitize_text),
            "city": df["City"].apply(sanitize_text),
            "state": df["State"].apply(sanitize_text),
            "zip": df["Zip Code"].apply(sanitize_text),
            "status": mapped.fillna(""),
            "source_status": df["Log Type"].fillna("").astype(str),
            "normalized_status": status_norm,
            "salesforce_new_status": "",
            "_phone_key": df["Phone"].apply(sanitize_phone),
            "_address_key": df.apply(
                lambda row: make_address_key(row["Address"], row["City"], row["State"], row["Zip Code"]), axis=1
            ),
        }
    )

    # Drop rows without basic contact/address data.
    out = out[(out["phone"] != "") | (out["address"] != "")]
    out = out.reset_index(drop=True)

    counts_input = preview_counts(out["normalized_status"])
    counts_output = preview_counts(out["status"])
    unmapped = sorted(
        {s for s in out["normalized_status"].unique() if s and s not in property_mapping}
    )
    return out, counts_input, counts_output, unmapped


def process_sms_folder(
    sms_folder: str, phone_mapping: Dict[str, Tuple[str, str]]
) -> Tuple[pd.DataFrame, Dict[str, int], Dict[str, int], List[str]]:
    """Reads all CSVs in a directory (status from each filename)."""
    folder = Path(sms_folder)
    entries = [(p.name, str(p)) for p in sorted(folder.iterdir()) if p.is_file() and p.suffix.lower() == ".csv"]
    return process_sms_files(entries, phone_mapping)


def process_sms_files(
    sms_csv_entries: List[Tuple[str, str]],
    phone_mapping: Dict[str, Tuple[str, str]],
) -> Tuple[pd.DataFrame, Dict[str, int], Dict[str, int], List[str]]:
    """
    sms_csv_entries: list of (original_filename, path_on_disk).
    Status source comes from filename (without count suffix), same as folder mode.
    """
    if not sms_csv_entries:
        raise ValueError("No SMS CSV files provided.")

    all_rows: List[pd.DataFrame] = []
    for original_name, file_path in sorted(sms_csv_entries, key=lambda x: x[0].lower()):
        if not original_name.lower().endswith(".csv"):
            continue
        df = smart_read_csv(file_path)
        if df.empty:
            continue

        phone_col = "Phone" if "Phone" in df.columns else None
        addr_col = "Property address" if "Property address" in df.columns else None
        city_col = "Property city" if "Property city" in df.columns else None
        state_col = "Property state" if "Property state" in df.columns else None
        zip_col = "Property zip" if "Property zip" in df.columns else None

        if not phone_col:
            raise ValueError(f"SMS file missing Phone column: {original_name}")

        raw_source_status = strip_trailing_count_from_filename(original_name)
        normalized_status = normalize_status(raw_source_status)
        normalized_status = STATUS_ALIASES.get(normalized_status, normalized_status)

        mapped_tuple = phone_mapping.get(normalized_status)
        phone_status = mapped_tuple[0] if mapped_tuple else ""
        phone_tag = mapped_tuple[1] if mapped_tuple else ""

        part = pd.DataFrame(
            {
                "phone": df[phone_col].apply(sanitize_phone),
                "address": df[addr_col].apply(sanitize_text) if addr_col else "",
                "city": df[city_col].apply(sanitize_text) if city_col else "",
                "state": df[state_col].apply(sanitize_text) if state_col else "",
                "zip": df[zip_col].apply(sanitize_text) if zip_col else "",
                "phone_status": phone_status,
                "phone_tag": phone_tag,
                "source_status": raw_source_status,
                "normalized_status": normalized_status,
                "source_file": original_name,
                "salesforce_new_status": "",
                "_phone_key": df[phone_col].apply(sanitize_phone),
                "_address_key": df.apply(
                    lambda row: make_address_key(
                        row[addr_col] if addr_col else "",
                        row[city_col] if city_col else "",
                        row[state_col] if state_col else "",
                        row[zip_col] if zip_col else "",
                    ),
                    axis=1,
                ),
            }
        )
        part = part[part["phone"] != ""].reset_index(drop=True)
        all_rows.append(part)

    if not all_rows:
        raise ValueError("SMS uploads did not produce usable rows.")

    out = pd.concat(all_rows, ignore_index=True)
    counts_input = preview_counts(out["normalized_status"])
    counts_output = preview_counts(out["phone_status"])
    unmapped = sorted(
        {s for s in out["normalized_status"].unique() if s and s not in phone_mapping}
    )
    return out, counts_input, counts_output, unmapped


def process_crm_updates(crm_file: str) -> Tuple[pd.DataFrame, List[str]]:
    """Load CRM updates and prepare mapping fields for override application."""
    df = smart_read_csv(crm_file)
    required_cols = ["leadstatus"]
    missing = [col for col in required_cols if col not in df.columns]
    if missing:
        raise ValueError(f"CRM file is missing required columns: {', '.join(missing)}")

    # Common phone column variants if present.
    crm_phone_col = None
    for candidate in ["phone", "Phone", "Phone Number", "phone_number"]:
        if candidate in df.columns:
            crm_phone_col = candidate
            break

    # Address columns based on provided CRM extract.
    street_col = "street" if "street" in df.columns else ("Street" if "Street" in df.columns else None)
    city_col = "city" if "city" in df.columns else ("City" if "City" in df.columns else None)
    state_col = "state" if "state" in df.columns else ("State" if "State" in df.columns else None)
    zip_col = "zip" if "zip" in df.columns else ("Zip" if "Zip" in df.columns else None)
    leadcreated_col = find_column_name(df, ["leadcreateddate", "lead_created_date", "created_on"])
    updated_on_col = find_column_name(df, ["updated_on", "updatedon", "lastmodifieddate", "updatedat"])

    normalized_status = df["leadstatus"].apply(normalize_status)
    prop_status = normalized_status.map(CRM_STATUS_TO_PROPERTY_STATUS).fillna("")
    phone_map = normalized_status.map(CRM_STATUS_TO_PHONE_STATUS_TAG)
    phone_status = phone_map.apply(lambda x: x[0] if isinstance(x, tuple) else "")
    phone_tag = phone_map.apply(lambda x: x[1] if isinstance(x, tuple) else "")
    leadcreated_raw = df[leadcreated_col] if leadcreated_col else pd.Series([""] * len(df), index=df.index)
    updated_on_raw = df[updated_on_col] if updated_on_col else pd.Series([""] * len(df), index=df.index)
    leadcreated_parsed = leadcreated_raw.apply(lambda x: parse_any_date_to_ymd(x)[0])
    leadcreated_valid = leadcreated_raw.apply(lambda x: parse_any_date_to_ymd(x)[1])
    updated_on_parsed = updated_on_raw.apply(lambda x: parse_updated_on_to_ymd(x)[0])
    updated_on_valid = updated_on_raw.apply(lambda x: parse_updated_on_to_ymd(x)[1])

    out = pd.DataFrame(
        {
            "crm_source_status": df["leadstatus"].fillna("").astype(str),
            "crm_normalized_status": normalized_status,
            "crm_property_status": prop_status,
            "crm_phone_status": phone_status,
            "crm_phone_tag": phone_tag,
            "leadcreateddate_raw": leadcreated_raw.fillna("").astype(str),
            "leadcreateddate_parsed": leadcreated_parsed,
            "leadcreateddate_valid": leadcreated_valid,
            "updated_on_raw": updated_on_raw.fillna("").astype(str),
            "updated_on_parsed": updated_on_parsed,
            "updated_on_valid": updated_on_valid,
            "_phone_key": df[crm_phone_col].apply(sanitize_phone) if crm_phone_col else "",
            "_address_key": df.apply(
                lambda row: make_address_key(
                    row[street_col] if street_col else "",
                    row[city_col] if city_col else "",
                    row[state_col] if state_col else "",
                    row[zip_col] if zip_col else "",
                ),
                axis=1,
            ),
        }
    )

    unmapped = sorted(
        {
            s
            for s in out["crm_normalized_status"].unique()
            if s
            and s not in CRM_STATUS_TO_PROPERTY_STATUS
            and s not in CRM_STATUS_TO_PHONE_STATUS_TAG
        }
    )
    return out, unmapped


def process_closings_for_tags(file_path: str) -> pd.DataFrame:
    """
    Read a closings Excel (same shape as HHB attribution: Address, Date Closed, etc.).
    One row per deal with tag (CLOSED) 8020 - M/YYYY for REISift bulk tag import.
    """
    path = Path(file_path)
    if path.suffix.lower() == ".xls":
        raise ValueError(
            "Legacy .xls is not supported in the API. Save as .xlsx or use the desktop mapper with xlrd."
        )
    try:
        df = pd.read_excel(file_path, engine="openpyxl")
    except ImportError as exc:
        raise ValueError("Reading Excel requires openpyxl for .xlsx: pip install openpyxl") from exc

    phone_col = find_column_name(df, ["Phone", "phone", "Phone Number", "phone_number"])
    addr_col = find_column_name(df, ["Address", "Property address", "Street"])
    city_col = find_column_name(df, ["City", "Property city"])
    state_col = find_column_name(df, ["State", "Property state"])
    zip_col = find_column_name(df, ["Zip", "Zip Code", "Property zip", "Zip code"])
    date_col = find_column_name(df, ["Date Closed", "Closing Date", "Close Date", "date closed"])

    if not date_col:
        raise ValueError("Closings file must include Date Closed (or Closing Date / Close Date).")
    if not addr_col:
        raise ValueError("Closings file must include Address (or Property address / Street).")

    from .closing_resolution import filter_closings_by_stage

    df = filter_closings_by_stage(df)

    rows: List[Dict[str, str]] = []
    for _, row in df.iterrows():
        closed = pd.to_datetime(row[date_col], errors="coerce")
        if pd.isna(closed):
            continue
        mm = int(closed.month)
        yyyy = int(closed.year)
        tag = f"(CLOSED) 8020 - {mm}/{yyyy}"
        phone_raw = row[phone_col] if phone_col else ""
        addr_raw = row[addr_col] if addr_col else ""
        city_raw = row[city_col] if city_col else ""
        state_raw = row[state_col] if state_col else ""
        zip_raw = row[zip_col] if zip_col else ""
        rows.append(
            {
                "phone": sanitize_phone(phone_raw),
                "address": sanitize_text(addr_raw),
                "city": sanitize_text(city_raw),
                "state": sanitize_text(state_raw),
                "zip": sanitize_text(zip_raw),
                "tag": tag,
            }
        )

    return pd.DataFrame(rows)


def apply_crm_overrides(
    cold_df: pd.DataFrame, sms_df: pd.DataFrame, crm_df: pd.DataFrame
) -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, Dict[str, int]]:
    """Apply CRM as highest-priority status override with phone-first/address-fallback matching."""
    cold_out = cold_df.copy()
    sms_out = sms_df.copy()

    metrics = {
        "crm_total_rows": len(crm_df),
        "crm_matched_by_phone": 0,
        "crm_matched_by_address": 0,
        "cold_overrides_applied": 0,
        "sms_overrides_applied": 0,
        "crm_unmatched_rows": 0,
        "sf_tags_created_total": 0,
        "sf_tags_created_status": 0,
        "sf_tags_created_updated": 0,
        "sf_skipped_updated_on": 0,
        "sf_skipped_created_date": 0,
    }
    sf_tag_rows: List[Dict[str, str]] = []

    # Pre-index for matching speed.
    cold_phone_index: Dict[str, List[int]] = {}
    cold_addr_index: Dict[str, List[int]] = {}
    for idx, row in cold_out.iterrows():
        phone_key = row["_phone_key"]
        addr_key = row["_address_key"]
        if phone_key:
            cold_phone_index.setdefault(phone_key, []).append(idx)
        if addr_key and addr_key != "|||":
            cold_addr_index.setdefault(addr_key, []).append(idx)

    sms_phone_index: Dict[str, List[int]] = {}
    sms_addr_index: Dict[str, List[int]] = {}
    for idx, row in sms_out.iterrows():
        phone_key = row["_phone_key"]
        addr_key = row["_address_key"]
        if phone_key:
            sms_phone_index.setdefault(phone_key, []).append(idx)
        if addr_key and addr_key != "|||":
            sms_addr_index.setdefault(addr_key, []).append(idx)

    for _, crm_row in crm_df.iterrows():
        crm_phone = crm_row["_phone_key"]
        crm_addr = crm_row["_address_key"]

        match_mode = ""
        cold_matches: List[int] = []
        sms_matches: List[int] = []

        if crm_phone:
            cold_matches = cold_phone_index.get(crm_phone, [])
            sms_matches = sms_phone_index.get(crm_phone, [])
            if cold_matches or sms_matches:
                match_mode = "phone"

        if not match_mode and crm_addr and crm_addr != "|||":
            cold_matches = cold_addr_index.get(crm_addr, [])
            sms_matches = sms_addr_index.get(crm_addr, [])
            if cold_matches or sms_matches:
                match_mode = "address"

        if not match_mode:
            metrics["crm_unmatched_rows"] += 1
            continue

        if match_mode == "phone":
            metrics["crm_matched_by_phone"] += 1
        else:
            metrics["crm_matched_by_address"] += 1

        crm_property_status = crm_row["crm_property_status"]
        crm_phone_status = crm_row["crm_phone_status"]
        crm_phone_tag = crm_row["crm_phone_tag"]

        built_tags, tag_skips = build_salesforce_tags(crm_row)
        for tag in built_tags:
            tag_row = {
                "phone": crm_phone,
                "address": "",
                "city": "",
                "state": "",
                "zip": "",
                "salesforce_new_status": crm_row["crm_source_status"],
                "updated_on_raw": crm_row["updated_on_raw"],
                "updated_on_parsed": crm_row["updated_on_parsed"],
                "leadcreateddate_raw": crm_row["leadcreateddate_raw"],
                "leadcreateddate_parsed": crm_row["leadcreateddate_parsed"],
                "salesforce_tag": tag["salesforce_tag"],
                "tag_type": tag["tag_type"],
                "crm_match_mode": match_mode,
                "row_validation_status": tag["row_validation_status"],
                "row_validation_reason": tag["row_validation_reason"],
            }
            sf_tag_rows.append(tag_row)
            metrics["sf_tags_created_total"] += 1
            if tag["tag_type"] == "created_status":
                metrics["sf_tags_created_status"] += 1
            elif tag["tag_type"] == "updated_status":
                metrics["sf_tags_created_updated"] += 1
        for _, reason in tag_skips:
            if reason == "skipped_updated_on":
                metrics["sf_skipped_updated_on"] += 1
            elif reason == "skipped_created_date":
                metrics["sf_skipped_created_date"] += 1

        if crm_property_status:
            for idx in cold_matches:
                cold_out.at[idx, "salesforce_new_status"] = crm_row["crm_source_status"]
                if cold_out.at[idx, "status"] != crm_property_status:
                    cold_out.at[idx, "status"] = crm_property_status
                    metrics["cold_overrides_applied"] += 1

        if crm_phone_status:
            for idx in sms_matches:
                sms_out.at[idx, "salesforce_new_status"] = crm_row["crm_source_status"]
                changed = False
                if sms_out.at[idx, "phone_status"] != crm_phone_status:
                    sms_out.at[idx, "phone_status"] = crm_phone_status
                    changed = True
                if sms_out.at[idx, "phone_tag"] != crm_phone_tag:
                    sms_out.at[idx, "phone_tag"] = crm_phone_tag
                    changed = True
                if changed:
                    metrics["sms_overrides_applied"] += 1

    sf_tags_df = pd.DataFrame(sf_tag_rows)
    return cold_out, sms_out, sf_tags_df, metrics


def export_outputs(
    cold_df: pd.DataFrame,
    sms_df: pd.DataFrame,
    sf_tags_df: pd.DataFrame,
    output_folder: str,
    allow_unmapped: bool,
    closings_tags_df: Optional[pd.DataFrame] = None,
) -> List[str]:
    """Writes REISift-oriented CSV outputs and returns their paths."""
    created: List[str] = []
    out_dir = Path(output_folder)
    out_dir.mkdir(parents=True, exist_ok=True)

    cold_unmapped = cold_df[cold_df["status"] == ""]
    sms_unmapped = sms_df[sms_df["phone_status"] == ""]
    if not allow_unmapped and (not cold_unmapped.empty or not sms_unmapped.empty):
        raise ValueError(
            "Unmapped statuses exist. Enable 'Allow export with unmapped statuses' or update mappings."
        )

    # Property status updates CSV.
    cold_export = cold_df[["phone", "address", "city", "state", "zip", "status", "salesforce_new_status"]].copy()
    if not allow_unmapped:
        cold_export = cold_export[cold_export["status"] != ""]
    cold_path = out_dir / "property_status_updates.csv"
    cold_export.to_csv(cold_path, index=False)
    created.append(str(cold_path))

    # Phone status + tag updates CSV.
    sms_export = sms_df.copy()
    if not allow_unmapped:
        sms_export = sms_export[sms_export["phone_status"] != ""]
    sms_path = out_dir / "phone_status_tags_updates.csv"
    sms_export[
        [
            "phone",
            "address",
            "city",
            "state",
            "zip",
            "phone_status",
            "phone_tag",
            "salesforce_new_status",
        ]
    ].to_csv(sms_path, index=False)
    created.append(str(sms_path))

    sf_tags_path = out_dir / "salesforce_status_tags.csv"
    if sf_tags_df.empty:
        pd.DataFrame(
            columns=[
                "phone",
                "address",
                "city",
                "state",
                "zip",
                "salesforce_new_status",
                "updated_on_raw",
                "updated_on_parsed",
                "leadcreateddate_raw",
                "leadcreateddate_parsed",
                "salesforce_tag",
                "tag_type",
                "crm_match_mode",
                "row_validation_status",
                "row_validation_reason",
            ]
        ).to_csv(sf_tags_path, index=False)
    else:
        sf_tags_df.to_csv(sf_tags_path, index=False)
    created.append(str(sf_tags_path))

    closings_path = out_dir / "closings_status_tags.csv"
    if closings_tags_df is not None:
        if closings_tags_df.empty:
            pd.DataFrame(columns=["phone", "address", "city", "state", "zip", "tag"]).to_csv(
                closings_path, index=False
            )
        else:
            closings_tags_df.to_csv(closings_path, index=False)
        created.append(str(closings_path))

    return created


@dataclass
class PatchPipelineResult:
    """In-memory result of cold + SMS + CRM + optional closings pipeline."""

    cold_df: pd.DataFrame
    sms_df: pd.DataFrame
    crm_df: pd.DataFrame
    sf_tags_df: pd.DataFrame
    closings_tags_df: Optional[pd.DataFrame]
    cold_unmapped: List[str]
    sms_unmapped: List[str]
    crm_unmapped: List[str]
    crm_metrics: Dict[str, int]
    cold_input_counts: Dict[str, int]
    cold_output_counts: Dict[str, int]
    sms_input_counts: Dict[str, int]
    sms_output_counts: Dict[str, int]
    closings_rows: int


def run_patch_pipeline(
    cold_csv_path: str,
    sms_csv_entries: List[Tuple[str, str]],
    crm_csv_path: str,
    closings_xlsx_path: Optional[str] = None,
    property_mapping: Optional[Dict[str, str]] = None,
    phone_mapping: Optional[Dict[str, Tuple[str, str]]] = None,
) -> PatchPipelineResult:
    """
    Run full mapper pipeline (same as desktop GUI preview path).

    sms_csv_entries: (original_filename, absolute_path) per uploaded SMS CSV.
    """
    prop = property_mapping or dict(PROPERTY_STATUS_MAPPING)
    phone = phone_mapping or dict(PHONE_STATUS_TAG_MAPPING)

    cold_df, cold_in, cold_out, cold_un = process_cold_calling(cold_csv_path, prop)
    sms_df, sms_in, sms_out, sms_un = process_sms_files(sms_csv_entries, phone)
    crm_df, crm_un = process_crm_updates(crm_csv_path)
    cold_df, sms_df, sf_tags_df, crm_metrics = apply_crm_overrides(cold_df, sms_df, crm_df)

    closings_df: Optional[pd.DataFrame] = None
    closings_rows = 0
    if closings_xlsx_path:
        closings_df = process_closings_for_tags(closings_xlsx_path)
        closings_rows = len(closings_df)

    return PatchPipelineResult(
        cold_df=cold_df,
        sms_df=sms_df,
        crm_df=crm_df,
        sf_tags_df=sf_tags_df,
        closings_tags_df=closings_df,
        cold_unmapped=cold_un,
        sms_unmapped=sms_un,
        crm_unmapped=crm_un,
        crm_metrics=crm_metrics,
        cold_input_counts=cold_in,
        cold_output_counts=cold_out,
        sms_input_counts=sms_in,
        sms_output_counts=sms_out,
        closings_rows=closings_rows,
    )


def write_patch_exports(
    result: PatchPipelineResult,
    out_dir: str,
    allow_unmapped: bool,
) -> List[str]:
    """Write four REISift CSVs to out_dir; returns file paths."""
    return export_outputs(
        result.cold_df,
        result.sms_df,
        result.sf_tags_df,
        out_dir,
        allow_unmapped,
        closings_tags_df=result.closings_tags_df,
    )

