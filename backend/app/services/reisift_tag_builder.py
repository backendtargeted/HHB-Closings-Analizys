"""
REISift tag synthesis from unified journey (no cold/SMS match gate for SF tags).
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

from .marketing_mapper import build_salesforce_tags, sanitize_text
from .unified_precedence import PrecedencePolicy, load_precedence_policy, row_sort_key_for_precedence

SF_TAG_EXPORT_COLUMNS = [
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
    "address_key",
    "source_file",
]


def format_closed_lost_tag(stage: str, loss_date: str, policy: Optional[PrecedencePolicy] = None) -> str:
    pol = policy or load_precedence_policy()
    mode = pol.closed_lost_token_mode
    label = sanitize_text(stage) or "Closed Lost"
    date = str(loss_date or "").strip()[:10]
    if mode == "option_c":
        return ""
    if mode == "option_b":
        slug = normalize_slug(label)
        return f"(SF) LOST - {slug} - {date}" if date else ""
    # option_a (default): matches existing (SF) UPDATED grammar
    return f"(SF) UPDATED - {label} - {date}" if date else ""


def normalize_slug(text: str) -> str:
    import re

    s = re.sub(r"[^\w\s-]", "", text.lower())
    return re.sub(r"\s+", "_", s.strip()) or "closed_lost"


def build_closed_lost_tags(
    events_df: pd.DataFrame,
    policy: Optional[PrecedencePolicy] = None,
) -> Tuple[pd.DataFrame, Dict[str, int]]:
    """Emit Closed Lost SF-style tags from closed_lost journey events."""
    pol = policy or load_precedence_policy()
    metrics = {"closed_lost_tag_rows": 0}
    if events_df.empty:
        return pd.DataFrame(columns=SF_TAG_EXPORT_COLUMNS), metrics

    lost = events_df[events_df["event_kind"] == "closed_lost"]
    if lost.empty:
        return pd.DataFrame(columns=SF_TAG_EXPORT_COLUMNS), metrics

    tag_rows: List[Dict[str, str]] = []
    seen: set[tuple[str, str]] = set()

    for _, ev in lost.iterrows():
        tag = format_closed_lost_tag(
            str(ev.get("disposition_text", "") or ev.get("stage", "")),
            str(ev.get("event_date", "")),
            pol,
        )
        if not tag:
            continue
        addr_key = str(ev.get("address_key", ""))
        dedupe_key = (addr_key, tag)
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        tag_rows.append(
            {
                "phone": str(ev.get("phone", "")),
                "address": str(ev.get("property_address", "")),
                "city": str(ev.get("property_city", "")),
                "state": str(ev.get("property_state", "")),
                "zip": str(ev.get("property_zip", "")),
                "salesforce_new_status": sanitize_text(ev.get("disposition_text", "") or ev.get("stage", "")),
                "updated_on_raw": str(ev.get("event_date", "")),
                "updated_on_parsed": str(ev.get("event_date", ""))[:10],
                "leadcreateddate_raw": "",
                "leadcreateddate_parsed": "",
                "salesforce_tag": tag,
                "tag_type": "closed_lost",
                "crm_match_mode": "journey_direct",
                "row_validation_status": "ok",
                "row_validation_reason": "",
                "address_key": addr_key,
                "source_file": str(ev.get("source_file", "")),
            }
        )
        metrics["closed_lost_tag_rows"] += 1

    return pd.DataFrame(tag_rows), metrics


def build_sf_tags_from_crm_rows(
    crm_df: pd.DataFrame,
    policy: Optional[PrecedencePolicy] = None,
) -> Tuple[pd.DataFrame, Dict[str, int]]:
    """
    Build salesforce_status_tags.csv rows directly from synthetic CRM rows.
    Does not require cold/SMS matching.
    """
    pol = policy or load_precedence_policy()
    metrics = {
        "sf_tags_created_total": 0,
        "sf_tags_created_status": 0,
        "sf_tags_created_updated": 0,
        "sf_skipped_updated_on": 0,
        "sf_skipped_created_date": 0,
    }
    if crm_df.empty:
        return pd.DataFrame(columns=SF_TAG_EXPORT_COLUMNS), metrics

    ordered = sorted(
        [row for _, row in crm_df.iterrows()],
        key=lambda r: row_sort_key_for_precedence(r.to_dict(), pol),
    )

    tag_rows: List[Dict[str, str]] = []
    seen_tags: set[tuple[str, str]] = set()

    for crm_row in ordered:
        row_dict = crm_row.to_dict() if hasattr(crm_row, "to_dict") else dict(crm_row)
        built_tags, tag_skips = build_salesforce_tags(pd.Series(row_dict))
        addr_key = str(row_dict.get("address_key", "") or row_dict.get("_address_key", ""))
        for tag in built_tags:
            token = tag["salesforce_tag"]
            dedupe_key = (addr_key, token)
            if dedupe_key in seen_tags:
                continue
            seen_tags.add(dedupe_key)
            tag_rows.append(
                {
                    "phone": str(row_dict.get("phone", "") or row_dict.get("_phone_key", "")),
                    "address": str(row_dict.get("street", "")),
                    "city": str(row_dict.get("city", "")),
                    "state": str(row_dict.get("state", "")),
                    "zip": str(row_dict.get("zip", "")),
                    "salesforce_new_status": str(row_dict.get("crm_source_status", "")),
                    "updated_on_raw": str(row_dict.get("updated_on_raw", "")),
                    "updated_on_parsed": str(row_dict.get("updated_on_parsed", "")),
                    "leadcreateddate_raw": str(row_dict.get("leadcreateddate_raw", "")),
                    "leadcreateddate_parsed": str(row_dict.get("leadcreateddate_parsed", "")),
                    "salesforce_tag": token,
                    "tag_type": tag["tag_type"],
                    "crm_match_mode": "journey_direct",
                    "row_validation_status": tag["row_validation_status"],
                    "row_validation_reason": tag["row_validation_reason"],
                    "address_key": addr_key,
                    "source_file": str(row_dict.get("source_file", "")),
                }
            )
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

    return pd.DataFrame(tag_rows), metrics


def merge_sf_tag_frames(frames: List[pd.DataFrame]) -> pd.DataFrame:
    parts = [f for f in frames if f is not None and not f.empty]
    if not parts:
        return pd.DataFrame(columns=SF_TAG_EXPORT_COLUMNS)
    combined = pd.concat(parts, ignore_index=True)
    if combined.empty:
        return combined
    combined = combined.drop_duplicates(subset=["address_key", "salesforce_tag"], keep="first")
    return combined
