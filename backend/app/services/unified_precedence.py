"""
Source precedence for unified ingest (O1/O2 policy hooks).

Implements config/precedence_policy.yaml. Does not invent business rules beyond config.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_POLICY_PATH = REPO_ROOT / "config" / "precedence_policy.json"

_REPORT_DATE_RE = re.compile(
    r"Report-(\d{4})-(\d{2})-(\d{2})",
    re.IGNORECASE,
)
_TINA_DATE_RE = re.compile(
    r"(\d{4})-(\d{2})-(\d{2})-(\d{2})-(\d{2})-(\d{2})",
)


@dataclass(frozen=True)
class PrecedencePolicy:
    policy_id: str
    tina_wins_fields: frozenset[str]
    tina_source_systems: frozenset[str]
    older_export_wins_systems: frozenset[str]
    source_system_close_rank: Dict[str, int]
    closed_lost_token_mode: str


def load_precedence_policy(path: Optional[Path] = None) -> PrecedencePolicy:
    policy_path = path or DEFAULT_POLICY_PATH
    raw: Dict[str, Any] = {}
    if policy_path.is_file():
        raw = json.loads(policy_path.read_text(encoding="utf-8")) or {}
    elif (REPO_ROOT / "config" / "precedence_policy.yaml").is_file():
        # Legacy YAML path if present (optional PyYAML).
        try:
            import yaml  # type: ignore

            raw = yaml.safe_load(
                (REPO_ROOT / "config" / "precedence_policy.yaml").read_text(encoding="utf-8")
            ) or {}
        except ImportError:
            raw = {}
    rank_raw = raw.get("source_system_close_rank") or {}
    return PrecedencePolicy(
        policy_id=str(raw.get("policy_id", "config_default_v1")),
        tina_wins_fields=frozenset(str(x) for x in (raw.get("tina_wins_fields") or [])),
        tina_source_systems=frozenset(str(x) for x in (raw.get("tina_source_systems") or [])),
        older_export_wins_systems=frozenset(str(x) for x in (raw.get("older_export_wins_systems") or [])),
        source_system_close_rank={str(k): int(v) for k, v in rank_raw.items()},
        closed_lost_token_mode=str(raw.get("closed_lost_token_mode", "option_a")),
    )


def parse_source_file_date(source_file: str) -> Optional[datetime]:
    """Extract export timestamp from filename (Report-* or Tina-* patterns)."""
    name = source_file or ""
    m = _REPORT_DATE_RE.search(name)
    if m:
        try:
            return datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            return None
    m = _TINA_DATE_RE.search(name)
    if m:
        try:
            return datetime(
                int(m.group(1)),
                int(m.group(2)),
                int(m.group(3)),
                int(m.group(4)),
                int(m.group(5)),
                int(m.group(6)),
            )
        except ValueError:
            return None
    return None


def source_system_rank(source_system: str, policy: PrecedencePolicy) -> int:
    return policy.source_system_close_rank.get(source_system or "", 99)


def is_tina_row(row: Dict[str, Any], policy: PrecedencePolicy) -> bool:
    return str(row.get("source_system", "")) in policy.tina_source_systems


def row_sort_key_for_precedence(row: Dict[str, Any], policy: PrecedencePolicy) -> tuple:
    """
    Lower sort key = higher precedence when picking canonical row.
    Tina first; then older filename date for report systems; then close rank.
    """
    src = str(row.get("source_system", ""))
    file_dt = parse_source_file_date(str(row.get("source_file", "")))
    file_ord = file_dt.timestamp() if file_dt else 0.0
    if is_tina_row(row, policy):
        tina_pri = 0
    else:
        tina_pri = 1
    if src in policy.older_export_wins_systems:
        # Older export wins → lower timestamp sorts first
        file_ord_key = file_ord
    else:
        file_ord_key = -file_ord
    return (tina_pri, file_ord_key, source_system_rank(src, policy))


def resolve_duplicate_rows(
    rows: Sequence[Dict[str, Any]],
    policy: Optional[PrecedencePolicy] = None,
) -> List[Dict[str, Any]]:
    """
    Given rows for one address_key (or logical group), return rows ordered by precedence.
    First row is canonical for field merge; all rows retained for audit unless caller filters.
    """
    if not rows:
        return []
    pol = policy or load_precedence_policy()
    return sorted(list(rows), key=lambda r: row_sort_key_for_precedence(r, pol))


def merge_field_from_rows(
    rows: Sequence[Dict[str, Any]],
    field: str,
    policy: Optional[PrecedencePolicy] = None,
) -> Any:
    """Field-scoped merge: Tina wins configured fields; else first non-empty by precedence order."""
    pol = policy or load_precedence_policy()
    ordered = resolve_duplicate_rows(rows, pol)
    if field in pol.tina_wins_fields:
        for row in ordered:
            if is_tina_row(row, pol):
                val = row.get(field)
                if val not in (None, ""):
                    return val
    for row in ordered:
        val = row.get(field)
        if val not in (None, ""):
            return val
    return ""
