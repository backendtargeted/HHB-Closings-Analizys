"""Monthly, source-dated Salesforce milestones without backdating status snapshots."""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
import re
from typing import Any

import pandas as pd

from .closing_resolution import is_closing_report_stage
from .marketing_mapper import build_salesforce_tags, find_column_name, make_address_key, sanitize_phone, smart_read_csv, read_csv_header
from .probate import QL_ADDR, OPP_ADDR, TXN_ADDR
from .reisift_tag_builder import SF_TAG_EXPORT_COLUMNS


@dataclass
class MonthlySalesforceResult:
    tags: pd.DataFrame
    review: pd.DataFrame
    events: pd.DataFrame
    summary: dict[str, Any]


REVIEW_COLUMNS = ["source", "source_file", "source_row_id", "address", "reason", "date_source"]
EVENT_COLUMNS = ["source", "source_file", "source_row_id", "address_key", "property_address",
                 "property_city", "property_state", "property_zip", "phone", "event_kind",
                 "event_subtype", "stage", "event_date", "date_source", "date_precision",
                 "date_confidence", "is_tag_eligible"]
TAG_COLUMNS = list(SF_TAG_EXPORT_COLUMNS) + ["source", "source_row_id", "event_date", "date_source", "tag"]


def _text(value: Any) -> str:
    if value is None or pd.isna(value):
        return ""
    return " ".join(str(value).split())


def _date(value: Any) -> tuple[str, str]:
    """Preserve the source calendar day, including timestamps with an offset."""
    text = _text(value)
    if not text or text.lower() in {"nan", "nat", "none", "null", "-"}:
        return "", "missing"
    try:
        if isinstance(value, (float, int)) and not isinstance(value, bool):
            if not 1 <= value < 100000:
                return "", "invalid"
            parsed = datetime(1899, 12, 30) + timedelta(days=float(value))
        else:
            # Strings consisting only of numbers are not inferred to be timestamps.
            if re.fullmatch(r"\d+(?:\.\d+)?", text):
                return "", "invalid"
            parsed = pd.to_datetime(value, errors="coerce")
        if pd.isna(parsed) or not 1900 <= parsed.year <= 2200:
            return "", "invalid"
        return parsed.date().isoformat(), "valid"
    except (ValueError, TypeError, OverflowError):
        return "", "invalid"


def _zip(value: Any) -> str:
    text = _text(value)
    if re.fullmatch(r"\d+\.0", text):
        text = text[:-2]
    if re.fullmatch(r"\d{1,5}", text):
        return text.zfill(5)
    if re.fullmatch(r"\d{5}-\d{4}", text):
        return text[:5]
    return text


def _load(path: str) -> pd.DataFrame:
    suffix = Path(path).suffix.lower()
    if suffix == ".xlsx":
        frame = pd.read_excel(path, engine="openpyxl", dtype=object)
    elif suffix == ".csv":
        frame = smart_read_csv(path, dtype=str, usecols=read_csv_header(path))
    else:
        raise ValueError("Salesforce reports must be .xlsx or .csv")
    frame.columns = [str(column).strip() for column in frame.columns]
    return frame


def build_monthly_salesforce(
    month: str, *, ql_path: str | None = None, opportunities_path: str | None = None, transactions_path: str | None = None,
) -> MonthlySalesforceResult:
    """Return independently importable tags, dated events, review rows and row stats.

    The report month selects source event dates; it never replaces those dates.
    Current status/Path is not dated from record creation. Path only validates an
    explicitly supplied transaction Closed Date, excluding dead/pending deals.
    """
    if not re.fullmatch(r"\d{4}-(?:0[1-9]|1[0-2])", month):
        raise ValueError("month must be YYYY-MM")
    if not any((ql_path, opportunities_path, transactions_path)):
        raise ValueError("Upload at least one Salesforce report")
    sources = [("qualified_leads", ql_path, QL_ADDR),
               ("opportunities", opportunities_path, OPP_ADDR),
               ("transactions", transactions_path, TXN_ADDR)]
    events, tag_rows, review, source_stats = [], [], [], []
    seen_events, seen_tags = set(), set()
    warnings = [
        "Qualified Leads Create Date establishes lead creation only, not a qualification milestone. New tags describe creation, not the current Lead Status.",
        "Current Lead Status and Opportunity Stage are not assigned to Created Date. Opportunity Close Date and scheduled dates are not used as actual closure or loss dates.",
        "Closing tags use the existing monthly (CLOSED) 8020 grammar; exact Closed Date is retained in event_date metadata. The token does not establish marketing attribution.",
    ]
    for source, path, address_spec in sources:
        if not path:
            continue
        frame = _load(path)
        role_column = {"qualified_leads": "Lead Status", "opportunities": "Stage", "transactions": "Path"}[source]
        if role_column not in frame:
            raise ValueError(f"{source}: wrong report role or missing required {role_column} column")
        columns = {key: find_column_name(frame, aliases) for key, aliases in address_spec.items()}
        if not columns["street"]:
            raise ValueError(f"{source}: missing property street column")
        if source == "qualified_leads":
            date_columns = [name for name in ("Create Date", "Created Date/Time", "Created Date") if name in frame]
        elif source == "opportunities":
            date_columns = [name for name in ("Created Date",) if name in frame]
        else:
            date_columns = [name for name in ("Date Contract Signed", "Date Contract Signed (MLS)", "Closed Date") if name in frame]
        if not date_columns:
            raise ValueError(f"{source}: no supported milestone date columns")
        phone_columns = [] if source == "opportunities" else [name for name in ("Phone", "Mobile", "Mobile Phone (via Person Account)") if name in frame]
        stats = {"source": source, "input_rows": len(frame), "included_rows": 0,
                 "outside_month_rows": 0, "missing_date_rows": 0,
                 "invalid_date_rows": 0, "duplicate_rows": 0, "unusable_identity_rows": 0,
                 "unverified_closing_rows": 0}
        for source_row_id, row in enumerate(frame.to_dict("records"), start=2):
            address = {key: _text(row.get(column)) if column else "" for key, column in columns.items()}
            address["zip"] = _zip(row.get(columns["zip"])) if columns["zip"] else ""
            phone = next((sanitize_phone(row.get(column)) for column in phone_columns
                          if len(sanitize_phone(row.get(column))) == 10), "")
            base = {"source": source, "source_file": Path(path).name, "source_row_id": source_row_id,
                    "address": address["street"]}
            if not address["street"] and not phone:
                stats["unusable_identity_rows"] += 1
                review.append({**base, "reason": "missing_property_address_and_phone", "date_source": ""})
                continue
            key = make_address_key(address["street"], address["city"], address["state"], address["zip"])
            identity = key if address["street"] else f"phone:{phone}"
            candidates = []
            date_states = []
            unverified_close = False
            if source in {"qualified_leads", "opportunities"}:
                # Coalesce aliases, not milestones. Never choose an older date just
                # because the authoritative one falls outside the selected month.
                for column in date_columns:
                    date, state = _date(row.get(column))
                    date_states.append(state)
                    if state == "valid":
                        candidates.append((date, column, "lead_created" if source == "qualified_leads" else "opportunity_created", "New" if source == "qualified_leads" else "Opportunity"))
                        break
                    if state == "invalid":
                        review.append({**base, "reason": "invalid_authoritative_creation_date", "date_source": column})
                        break
            else:
                for column in date_columns:
                    date, state = _date(row.get(column))
                    date_states.append(state)
                    if state != "valid":
                        continue
                    if column == "Closed Date" and not is_closing_report_stage(row.get("Path")):
                        unverified_close = True
                        review.append({**base, "reason": "closed_date_without_closed_path", "date_source": column})
                        continue
                    candidates.append((date, column, "closing" if column == "Closed Date" else "under_contract", "Closed" if column == "Closed Date" else "Under Contract"))
            included = duplicate = outside = False
            for date, column, kind, stage in candidates:
                if date[:7] != month:
                    outside = True
                    continue
                event_key = (identity, kind, date)
                if event_key in seen_events:
                    duplicate = True
                    continue
                seen_events.add(event_key)
                included = True
                event = {**base, "address_key": key if address["street"] else "",
                         "property_address": address["street"], "property_city": address["city"],
                         "property_state": address["state"], "property_zip": address["zip"], "phone": phone,
                         "event_kind": kind, "event_subtype": kind, "stage": stage, "event_date": date,
                         "date_source": column, "date_precision": "day", "date_confidence": "high", "is_tag_eligible": True}
                events.append(event)
                if kind == "closing":
                    token = f"(CLOSED) 8020 - {int(date[5:7])}/{date[:4]}"
                    tag_type = "closed"
                else:
                    created = kind == "lead_created"
                    built, _ = build_salesforce_tags(pd.Series({
                        "crm_source_status": stage, "crm_normalized_status": stage.lower(),
                        "updated_on_parsed": "" if created else date, "updated_on_valid": not created,
                        "leadcreateddate_parsed": date if created else "", "leadcreateddate_valid": created,
                    }))
                    token, tag_type = built[0]["salesforce_tag"], built[0]["tag_type"]
                tag_key = (identity, token)
                if tag_key in seen_tags:
                    continue
                seen_tags.add(tag_key)
                tag_rows.append({"phone": phone, "address": address["street"], "city": address["city"],
                    "state": address["state"], "zip": address["zip"], "salesforce_new_status": stage,
                    "updated_on_raw": _text(row.get(column)) if kind != "lead_created" else "",
                    "updated_on_parsed": date if kind != "lead_created" else "",
                    "leadcreateddate_raw": _text(row.get(column)) if kind == "lead_created" else "",
                    "leadcreateddate_parsed": date if kind == "lead_created" else "",
                    "salesforce_tag": token, "tag": token, "tag_type": tag_type,
                    "crm_match_mode": "source_dated_milestone", "row_validation_status": "ok",
                    "row_validation_reason": "", "address_key": event["address_key"],
                    "source": source, "source_file": Path(path).name, "source_row_id": source_row_id,
                    "event_date": date, "date_source": column})
            if included:
                outcome = "included_rows"
            elif duplicate:
                outcome = "duplicate_rows"
            elif outside:
                outcome = "outside_month_rows"
            elif unverified_close:
                outcome = "unverified_closing_rows"
            elif "invalid" in date_states:
                outcome = "invalid_date_rows"
            else:
                outcome = "missing_date_rows"
            stats[outcome] += 1
            if outcome != "included_rows":
                review.append({**base, "reason": outcome.removesuffix("_rows"), "date_source": "; ".join(date_columns)})
        source_stats.append(stats)
    tag_frame = pd.DataFrame(tag_rows, columns=TAG_COLUMNS)
    summary = {"month": month, "sources": source_stats, "warnings": warnings,
               "tag_counts": dict(Counter(row["tag_type"] for row in tag_rows)),
               "event_counts": dict(Counter(event["event_kind"] for event in events)),
               "tags_total": len(tag_rows), "events_total": len(events), "review_rows": len(review)}
    return MonthlySalesforceResult(tag_frame, pd.DataFrame(review, columns=REVIEW_COLUMNS),
                                   pd.DataFrame(events, columns=EVENT_COLUMNS), summary)
