"""
Synthesize CRM-shaped rows from journey_events for build_salesforce_tags.
"""

from __future__ import annotations

from typing import Any, Dict, List

import pandas as pd

from .marketing_mapper import (
    CRM_STATUS_TO_PHONE_STATUS_TAG,
    CRM_STATUS_TO_PROPERTY_STATUS,
    make_address_key,
    normalize_status,
    parse_any_date_to_ymd,
    parse_updated_on_to_ymd,
    sanitize_phone,
    sanitize_text,
)

CRM_ROW_COLUMNS = [
    "crm_source_status",
    "crm_normalized_status",
    "crm_property_status",
    "crm_phone_status",
    "crm_phone_tag",
    "leadcreateddate_raw",
    "leadcreateddate_parsed",
    "leadcreateddate_valid",
    "updated_on_raw",
    "updated_on_parsed",
    "updated_on_valid",
    "_phone_key",
    "_address_key",
    "street",
    "city",
    "state",
    "zip",
    "phone",
    "address_key",
    "source_file",
    "source_system",
    "event_subtype",
]


def _crm_row_from_parts(
    *,
    stage: str,
    leadcreated_raw: str,
    updated_raw: str,
    phone: str,
    street: str,
    city: str,
    state: str,
    zip_code: str,
    address_key: str,
    source_file: str,
    source_system: str,
    event_subtype: str,
) -> Dict[str, Any]:
    normalized = normalize_status(stage)
    prop_status = CRM_STATUS_TO_PROPERTY_STATUS.get(normalized, "")
    phone_map = CRM_STATUS_TO_PHONE_STATUS_TAG.get(normalized)
    phone_status = phone_map[0] if isinstance(phone_map, tuple) else ""
    phone_tag = phone_map[1] if isinstance(phone_map, tuple) else ""

    lead_parsed, lead_valid = parse_any_date_to_ymd(leadcreated_raw)
    upd_parsed, upd_valid = parse_updated_on_to_ymd(updated_raw)
    if not upd_valid and updated_raw:
        upd_parsed, upd_valid = parse_any_date_to_ymd(updated_raw)

    return {
        "crm_source_status": stage,
        "crm_normalized_status": normalized,
        "crm_property_status": prop_status,
        "crm_phone_status": phone_status,
        "crm_phone_tag": phone_tag,
        "leadcreateddate_raw": leadcreated_raw,
        "leadcreateddate_parsed": lead_parsed,
        "leadcreateddate_valid": lead_valid,
        "updated_on_raw": updated_raw,
        "updated_on_parsed": upd_parsed,
        "updated_on_valid": upd_valid,
        "_phone_key": sanitize_phone(phone),
        "_address_key": address_key or make_address_key(street, city, state, zip_code),
        "street": street,
        "city": city,
        "state": state,
        "zip": zip_code,
        "phone": sanitize_phone(phone),
        "address_key": address_key,
        "source_file": source_file,
        "source_system": source_system,
        "event_subtype": event_subtype,
    }


def synthesize_crm_rows(events_df: pd.DataFrame) -> pd.DataFrame:
    """Build one CRM row per tag-eligible CRM journey event."""
    if events_df.empty:
        return pd.DataFrame(columns=CRM_ROW_COLUMNS)

    rows: List[Dict[str, Any]] = []
    for _, ev in events_df.iterrows():
        if not ev.get("is_tag_eligible"):
            continue
        kind = str(ev.get("event_kind", ""))
        if kind in ("closing", "closed_lost"):
            continue
        subtype = str(ev.get("event_subtype", ""))
        stage = sanitize_text(ev.get("stage", ""))
        if not stage:
            continue
        event_date = str(ev.get("event_date", "") or "")
        leadcreated = event_date if subtype == "crm_lead_created" else ""
        updated = event_date if subtype == "sf_updated" else ""
        if subtype == "crm_lead_created":
            updated = ""
        elif subtype == "sf_updated":
            leadcreated = ""

        rows.append(
            _crm_row_from_parts(
                stage=stage,
                leadcreated_raw=leadcreated,
                updated_raw=updated,
                phone=str(ev.get("phone", "")),
                street=str(ev.get("property_address", "")),
                city=str(ev.get("property_city", "")),
                state=str(ev.get("property_state", "")),
                zip_code=str(ev.get("property_zip", "")),
                address_key=str(ev.get("address_key", "")),
                source_file=str(ev.get("source_file", "")),
                source_system=str(ev.get("source_system", "")),
                event_subtype=subtype,
            )
        )

    if not rows:
        return pd.DataFrame(columns=CRM_ROW_COLUMNS)
    return pd.DataFrame(rows)


def crm_rows_to_series_df(crm_df: pd.DataFrame) -> pd.DataFrame:
    """Ensure columns exist for build_salesforce_tags iteration."""
    if crm_df.empty:
        return crm_df
    return crm_df
