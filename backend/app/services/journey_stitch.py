"""
Stitch unified closings / opportunities / status_snapshots into journey_events.

Append-only at ingest; closings dedupe for mapper tags is separate (dedupe_closings_for_mapper).
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

from .closing_resolution import is_closing_report_stage
from .journey_confidence import attach_confidence, summarize_confidence
from .marketing_mapper import make_address_key, normalize_status, sanitize_phone, sanitize_text
from .unified_precedence import (
    PrecedencePolicy,
    load_precedence_policy,
    resolve_duplicate_rows,
    source_system_rank,
)

JOURNEY_EVENT_COLUMNS = [
    "address_key",
    "event_kind",
    "event_subtype",
    "event_date",
    "date_precision",
    "date_confidence",
    "date_source",
    "stage",
    "lead_source",
    "disposition_text",
    "source_system",
    "source_file",
    "source_row_id",
    "phone",
    "property_address",
    "property_city",
    "property_state",
    "property_zip",
    "is_tag_eligible",
]

LEAD_CREATION_STAGES = frozenset({"new", "decision maker - lead"})


def is_closed_lost_stage(stage_value: Any) -> bool:
    if stage_value is None or (isinstance(stage_value, float) and pd.isna(stage_value)):
        return False
    norm = normalize_status(str(stage_value).strip())
    if not norm:
        return False
    return norm == "closed lost" or norm.startswith("closed lost") or "closed lost" in norm


def _valid_close_flag(row: pd.Series) -> bool:
    if "has_valid_close_date" in row.index:
        return str(row.get("has_valid_close_date", "")).lower() in ("true", "1", "yes")
    return bool(str(row.get("date_closed", "") or row.get("close_date", "")).strip())


def _pick_date(row: pd.Series, *cols: str) -> Tuple[str, str]:
    for col in cols:
        if col in row.index:
            val = str(row.get(col, "") or "").strip()
            if val and val.lower() != "nan":
                return val, col
    return "", ""


def _build_lead_source_map(snapshots: pd.DataFrame) -> Dict[str, str]:
    out: Dict[str, str] = {}
    if snapshots.empty:
        return out
    seller = snapshots
    if "entity_type" in snapshots.columns:
        seller = snapshots[snapshots["entity_type"].astype(str) == "seller_lead"]
    for _, row in seller.iterrows():
        key = str(row.get("address_key", "") or "").strip()
        src = sanitize_text(row.get("lead_source", ""))
        if key and src:
            out[key] = src
    return out


def _resolve_lead_source(
    address_key: str,
    row: pd.Series,
    seller_map: Dict[str, str],
) -> str:
    if address_key and address_key in seller_map:
        return seller_map[address_key]
    src = sanitize_text(row.get("lead_source", ""))
    return src if src else "Unknown"


def _base_event(row: pd.Series, address_key: str, lead_source: str) -> Dict[str, Any]:
    return {
        "address_key": address_key,
        "stage": sanitize_text(row.get("stage", "")),
        "lead_source": lead_source,
        "disposition_text": "",
        "source_system": sanitize_text(row.get("source_system", "")),
        "source_file": sanitize_text(row.get("source_file", "")),
        "source_row_id": int(row.get("source_row_id", 0) or 0),
        "phone": sanitize_phone(row.get("phone", "")),
        "property_address": sanitize_text(row.get("property_address", "")),
        "property_city": sanitize_text(row.get("property_city", "")),
        "property_state": sanitize_text(row.get("property_state", "")),
        "property_zip": sanitize_text(row.get("property_zip", "")),
        "is_tag_eligible": False,
    }


def _events_from_closing(row: pd.Series, address_key: str, lead_source: str) -> List[Dict[str, Any]]:
    if not address_key:
        return []
    stage = row.get("stage", "")
    date_val, date_src = _pick_date(row, "date_closed")
    if not date_val:
        return []
    base = _base_event(row, address_key, lead_source)
    if is_closed_lost_stage(stage):
        ev = {
            **base,
            "event_kind": "closed_lost",
            "event_subtype": "terminal_lost",
            "event_date": date_val,
            "date_source": date_src,
            "disposition_text": sanitize_text(stage),
            "is_tag_eligible": False,
        }
        return [attach_confidence(ev)]
    if not _valid_close_flag(row) or not is_closing_report_stage(stage):
        return []
    ev = {
        **base,
        "event_kind": "closing",
        "event_subtype": "closed_won",
        "event_date": date_val,
        "date_source": date_src,
        "is_tag_eligible": True,
    }
    return [attach_confidence(ev)]


def _events_from_opportunity(row: pd.Series, address_key: str, lead_source: str) -> List[Dict[str, Any]]:
    if not address_key:
        return []
    events: List[Dict[str, Any]] = []
    stage = sanitize_text(row.get("stage", ""))
    norm = normalize_status(stage)
    created, created_src = _pick_date(row, "created_date")
    close_d, close_src = _pick_date(row, "close_date")

    if created and norm in LEAD_CREATION_STAGES:
        base = _base_event(row, address_key, lead_source)
        ev = {
            **base,
            "event_kind": "opportunity",
            "event_subtype": "crm_lead_created",
            "event_date": created,
            "date_source": created_src,
            "is_tag_eligible": True,
        }
        events.append(attach_confidence(ev))

    update_date, update_src = (close_d, close_src) if close_d else (created, created_src)
    if stage and update_date:
        base = _base_event(row, address_key, lead_source)
        ev = {
            **base,
            "event_kind": "opportunity",
            "event_subtype": "sf_updated",
            "event_date": update_date,
            "date_source": update_src,
            "is_tag_eligible": True,
        }
        events.append(attach_confidence(ev))

    if is_closed_lost_stage(stage) and (close_d or created):
        base = _base_event(row, address_key, lead_source)
        ev = {
            **base,
            "event_kind": "closed_lost",
            "event_subtype": "terminal_lost",
            "event_date": close_d or created,
            "date_source": close_src or created_src,
            "disposition_text": stage,
            "is_tag_eligible": False,
        }
        events.append(attach_confidence(ev))

    return events


def _events_from_snapshot(row: pd.Series, address_key: str, lead_source: str) -> List[Dict[str, Any]]:
    if not address_key:
        return []
    events: List[Dict[str, Any]] = []
    stage = sanitize_text(row.get("stage", ""))
    norm = normalize_status(stage)
    created, created_src = _pick_date(row, "created_date")
    close_d, close_src = _pick_date(row, "close_date")

    if created and norm in LEAD_CREATION_STAGES:
        base = _base_event(row, address_key, lead_source)
        ev = {
            **base,
            "event_kind": "status_snapshot",
            "event_subtype": "crm_lead_created",
            "event_date": created,
            "date_source": created_src,
            "is_tag_eligible": True,
        }
        events.append(attach_confidence(ev))

    update_date, update_src = (close_d, close_src) if close_d else (created, created_src)
    if stage and update_date:
        base = _base_event(row, address_key, lead_source)
        ev = {
            **base,
            "event_kind": "status_snapshot",
            "event_subtype": "sf_updated",
            "event_date": update_date,
            "date_source": update_src,
            "is_tag_eligible": True,
        }
        events.append(attach_confidence(ev))

    if is_closed_lost_stage(stage) and (close_d or created):
        base = _base_event(row, address_key, lead_source)
        ev = {
            **base,
            "event_kind": "closed_lost",
            "event_subtype": "terminal_lost",
            "event_date": close_d or created,
            "date_source": close_src or created_src,
            "disposition_text": stage,
            "is_tag_eligible": False,
        }
        events.append(attach_confidence(ev))

    return events


def stitch_journey(
    unified_dir: Path,
    policy: Optional[PrecedencePolicy] = None,
) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    """Load unified CSVs and emit journey_events DataFrame + stats dict."""
    pol = policy or load_precedence_policy()
    unified_dir = Path(unified_dir)
    closings = pd.read_csv(unified_dir / "closings.csv", low_memory=False)
    opps = pd.read_csv(unified_dir / "opportunities.csv", low_memory=False)
    snapshots = pd.read_csv(unified_dir / "status_snapshots.csv", low_memory=False)

    seller_map = _build_lead_source_map(snapshots)
    events: List[Dict[str, Any]] = []
    unjoinable = 0

    for df, emitter in (
        (closings, _events_from_closing),
        (opps, _events_from_opportunity),
        (snapshots, _events_from_snapshot),
    ):
        if df.empty:
            continue
        for _, row in df.iterrows():
            key = str(row.get("address_key", "") or "").strip()
            if not key or key == "|||":
                unjoinable += 1
                continue
            ls = _resolve_lead_source(key, row, seller_map)
            events.extend(emitter(row, key, ls))

    events_df = pd.DataFrame(events, columns=JOURNEY_EVENT_COLUMNS) if events else pd.DataFrame(
        columns=JOURNEY_EVENT_COLUMNS
    )

    address_keys = set(events_df["address_key"].unique()) if len(events_df) else set()
    closed_lost_keys = set()
    if len(events_df):
        lost = events_df[events_df["event_kind"] == "closed_lost"]
        closed_lost_keys = set(lost["address_key"].unique())

    stats = {
        "address_keys_total": len(address_keys),
        "address_keys_with_closing": int(
            len(events_df.loc[events_df["event_kind"] == "closing", "address_key"].unique())
            if len(events_df)
            else 0
        ),
        "events_total": len(events_df),
        "closed_lost_keys": len(closed_lost_keys),
        "unjoinable_rows_skipped": unjoinable,
        "confidence_summary": summarize_confidence(events),
        "precedence_policy_id": pol.policy_id,
    }
    return events_df, stats


def _parse_event_date(value: str) -> Optional[datetime]:
    text = str(value or "").strip()
    if not text:
        return None
    for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%m/%d/%Y"):
        try:
            return datetime.strptime(text[:19], fmt)
        except ValueError:
            continue
    try:
        return pd.to_datetime(text, errors="coerce").to_pydatetime()
    except (ValueError, TypeError):
        return None


def dedupe_closings_for_mapper(
    closings_df: pd.DataFrame,
    policy: Optional[PrecedencePolicy] = None,
) -> pd.DataFrame:
    """
    One closing per address_key for REISift (CLOSED) tags: earliest close, tie-break by source rank.
    Excludes Closed Lost and rows without valid close dates.
    """
    pol = policy or load_precedence_policy()
    if closings_df.empty:
        return pd.DataFrame(
            columns=[
                "Property address",
                "Property city",
                "State",
                "Zip Code",
                "Date Closed",
                "Phone",
                "Stage",
            ]
        )

    df = closings_df.copy()
    if "has_valid_close_date" in df.columns:
        mask = df["has_valid_close_date"].astype(str).str.lower().isin(["true", "1", "yes"])
        df = df[mask]
    else:
        df = df[df["date_closed"].astype(str).str.len() > 0]

    if "stage" in df.columns:
        df = df[~df["stage"].apply(is_closed_lost_stage)]

    rows: List[Dict[str, Any]] = []
    for _, row in df.iterrows():
        key = str(row.get("address_key", "") or "").strip()
        if not key:
            continue
        rows.append(row.to_dict())

    by_key: Dict[str, List[Dict[str, Any]]] = {}
    for row in rows:
        key = str(row.get("address_key", ""))
        by_key.setdefault(key, []).append(row)

    picked: List[Dict[str, Any]] = []
    deduped_removed = 0
    for key, group in by_key.items():
        if len(group) > 1:
            deduped_removed += len(group) - 1

        def sort_key(r: Dict[str, Any]) -> tuple:
            dt = _parse_event_date(str(r.get("date_closed", "")))
            ts = dt.timestamp() if dt else float("inf")
            rank = source_system_rank(str(r.get("source_system", "")), pol)
            return (ts, rank)

        group_sorted = sorted(group, key=sort_key)
        canonical = resolve_duplicate_rows(group_sorted, pol)[0]
        picked.append(canonical)

    out_rows = []
    for row in picked:
        closed = _parse_event_date(str(row.get("date_closed", "")))
        if closed is None:
            continue
        out_rows.append(
            {
                "Property address": sanitize_text(row.get("property_address", "")),
                "Property city": sanitize_text(row.get("property_city", "")),
                "State": sanitize_text(row.get("property_state", "")),
                "Zip Code": sanitize_text(row.get("property_zip", "")),
                "Date Closed": closed,
                "Phone": sanitize_phone(row.get("phone", "")),
                "Stage": sanitize_text(row.get("stage", "")),
            }
        )

    return pd.DataFrame(out_rows)


def write_mapper_closings_xlsx(closings_df: pd.DataFrame, dst_xlsx: Path) -> Tuple[int, int]:
    """Write deduped mapper-ready closings xlsx; returns (raw_eligible_count, written_rows)."""
    pol = load_precedence_policy()
    eligible = closings_df.copy()
    if "has_valid_close_date" in eligible.columns:
        eligible = eligible[
            eligible["has_valid_close_date"].astype(str).str.lower().isin(["true", "1", "yes"])
        ]
    raw_count = len(eligible)
    deduped = dedupe_closings_for_mapper(closings_df, pol)
    dst_xlsx = Path(dst_xlsx)
    dst_xlsx.parent.mkdir(parents=True, exist_ok=True)
    deduped.to_excel(dst_xlsx, index=False)
    return raw_count, len(deduped)
