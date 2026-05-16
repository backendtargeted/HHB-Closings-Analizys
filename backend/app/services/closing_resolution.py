"""
Close vs under-contract milestone resolution.

Business rules (leadership):
- SF "converted" / "under contract" = under contract only — never Date Closed alone.
- Date Closed from (CLOSED) tags and/or closings workbook; earliest wins when multiple close sources disagree.
- Closings workbook Stage: exclude Closed Lost; include other closing stages (Closed, Executed, Funded, Closed Won, …).
- Legacy mode (USE_LEGACY_MIN_CLOSE_DATE): restore min(SF converted, CLOSED) for Date Closed.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime
from typing import Any, List, Optional

import pandas as pd

from .lifecycle import CONVERTED_LABELS
from .marketing_mapper import find_column_name, normalize_status

STAGE_COLUMN_CANDIDATES = ["Stage", "stage", "Deal Stage", "Status", "Opportunity Stage"]


def use_legacy_min_close_date() -> bool:
    raw = (os.environ.get("USE_LEGACY_MIN_CLOSE_DATE") or "").strip().lower()
    return raw in ("1", "true", "yes", "on")


def is_closing_report_stage(stage_value: Any) -> bool:
    """
    True when a workbook Stage value represents an actual closing (not pipeline / lost).
    Closed Lost is excluded; other closed-type stages are included.
    """
    if stage_value is None or (isinstance(stage_value, float) and pd.isna(stage_value)):
        return False
    norm = normalize_status(str(stage_value).strip())
    if not norm:
        return False
    if norm == "closed lost" or norm.startswith("closed lost"):
        return False
    if "closed lost" in norm:
        return False
    if norm in ("closed", "executed", "funded", "closed won"):
        return True
    if "closed" in norm and "lost" not in norm:
        return True
    return False


def find_stage_column(df: pd.DataFrame) -> Optional[str]:
    return find_column_name(df, STAGE_COLUMN_CANDIDATES)


def filter_closings_by_stage(df: pd.DataFrame) -> pd.DataFrame:
    """When Stage column exists, keep only closing-type rows."""
    stage_col = find_stage_column(df)
    if not stage_col:
        return df
    mask = df[stage_col].apply(is_closing_report_stage)
    return df.loc[mask].copy().reset_index(drop=True)


@dataclass
class ResolvedMilestones:
    date_closed: Optional[datetime]
    date_under_contract: Optional[datetime]
    close_source: Optional[str]
    contract_source: Optional[str]
    has_closed_tag: bool
    has_contract_sf_tag: bool


def _parse_iso_dt(value: str) -> Optional[datetime]:
    try:
        return datetime.fromisoformat(str(value))
    except ValueError:
        return None


def resolve_milestones_from_parsed(
    parsed: List[dict],
    *,
    legacy_mode: bool = False,
    workbook_close: Optional[datetime] = None,
) -> ResolvedMilestones:
    """
    Derive Date Closed and Date Under Contract from parsed tag events.
    Optional workbook_close participates in earliest-close rule when present.
    """
    closing_dates: List[datetime] = []
    contract_dates: List[datetime] = []

    for p in parsed:
        ptype = str(p.get("type", ""))
        dt = _parse_iso_dt(str(p.get("date", "")))
        if dt is None:
            continue
        if ptype == "closing":
            closing_dates.append(dt)
        elif ptype in ("sf_updated", "sf_status"):
            label = normalize_status(str(p.get("label", "")))
            if label in CONVERTED_LABELS:
                contract_dates.append(dt)

    has_closed_tag = bool(closing_dates)
    has_contract_sf_tag = bool(contract_dates)
    date_under_contract = min(contract_dates) if contract_dates else None
    contract_source = "sf_under_contract" if date_under_contract else None

    close_candidates: List[datetime] = []
    close_source: Optional[str] = None

    if legacy_mode:
        close_candidates = list(closing_dates) + list(contract_dates)
        if workbook_close is not None:
            close_candidates.append(workbook_close)
        if close_candidates:
            date_closed = min(close_candidates)
            close_source = "legacy_min"
        else:
            date_closed = None
    else:
        close_candidates = list(closing_dates)
        if workbook_close is not None:
            close_candidates.append(workbook_close)
        if close_candidates:
            date_closed = min(close_candidates)
            if workbook_close is not None and closing_dates:
                close_source = "earliest_workbook_and_tag"
            elif workbook_close is not None:
                close_source = "closings_workbook"
            else:
                close_source = "closed_tag"
        else:
            date_closed = None

    return ResolvedMilestones(
        date_closed=date_closed,
        date_under_contract=date_under_contract,
        close_source=close_source,
        contract_source=contract_source,
        has_closed_tag=has_closed_tag,
        has_contract_sf_tag=has_contract_sf_tag,
    )
