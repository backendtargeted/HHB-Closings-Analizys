"""Monthly CC/SMS evidence with explicit date provenance and no CRM overrides.

Call log dates are event dates. Undated SMS labels are a selected-month snapshot,
not evidence that a message was sent on a particular day. Neither proves provider.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
import re
from typing import Any

import pandas as pd

from .marketing_mapper import (
    sanitize_text,
    sanitize_phone, make_address_key, smart_read_csv, read_csv_header, strip_trailing_count_from_filename,
)
from .marketing_tag_policy import PROPERTY_MAPPING, PHONE_MAPPING, resolve_labels, validate_mappings

DATE_COLUMNS = ("Log Time (Date)", "Log Date", "Activity Date", "Sent At", "Sent Date", "Message Date", "Timestamp", "Date")
BASE_COLUMNS = ["phone", "address", "city", "state", "zip", "source_status", "normalized_status",
                "source_file", "source_row", "salesforce_new_status", "_phone_key", "_address_key",
                "event_date", "event_month", "date_source", "date_precision", "date_raw", "source_time",
                "row_validation_status", "row_validation_reason", "channel",
                "property_validation_reason", "phone_validation_reason",
                "unmapped_property_labels", "unmapped_phone_labels"]


@dataclass
class MonthlyMarketingResult:
    property_df: pd.DataFrame
    phone_df: pd.DataFrame
    cold_df: pd.DataFrame
    sms_df: pd.DataFrame
    marketing_tags_df: pd.DataFrame
    review_df: pd.DataFrame
    stats: dict[str, Any]
    cold_unmapped: list[str]
    sms_unmapped: list[str]
    cold_input_counts: dict[str, int]
    cold_output_counts: dict[str, int]
    sms_input_counts: dict[str, int]
    sms_output_counts: dict[str, int]


def validate_reporting_month(value: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[0-9]{4}-(0[1-9]|1[0-2])", value):
        raise ValueError("reporting_month must be YYYY-MM")
    try:
        datetime.strptime(value, "%Y-%m")
    except ValueError as exc:
        raise ValueError("reporting_month must be a valid YYYY-MM") from exc
    return value


def resolve_event_date(raw: object, reporting_month: str, column: str = "") -> dict[str, str]:
    """Missing date has month precision only; malformed dates never get fallback."""
    selected = validate_reporting_month(reporting_month)
    text = sanitize_text(raw)
    base = {"date_raw": text, "date_source": column, "event_date": "", "event_month": "", "date_precision": ""}
    if not text:
        return {**base, "event_month": selected, "date_source": "selected_month_fallback", "date_precision": "month", "date_status": "missing"}
    parsed = None
    for fmt in ("%m/%d/%Y", "%m/%d/%Y %H:%M:%S", "%m/%d/%Y %I:%M:%S %p", "%Y-%m-%d"):
        try:
            parsed = datetime.strptime(text, fmt)
            break
        except ValueError:
            continue
    if parsed is None and re.match(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}[T ]", text):
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            pass
    if parsed is None:
        return {**base, "date_status": "invalid"}
    month = parsed.strftime("%Y-%m")
    return {**base, "event_date": parsed.strftime("%Y-%m-%d"), "event_month": month,
            "date_source": column or "source_event_date", "date_precision": "day",
            "date_status": "valid" if month == selected else "outside_month"}


def _column(columns, *names):
    lookup = {str(c).strip().casefold(): c for c in columns}
    return next((lookup[n.casefold()] for n in names if n.casefold() in lookup), None)


def _status(value: str) -> str:
    # Deliberately no legacy NYI->Lead alias or cross-channel status rewriting.
    normalized = re.sub(r"\s+", " ", value.strip()).casefold().replace("–", "-")
    normalized = re.sub(r"\s*-\s*", " - ", normalized)
    return {"do not call": "dnc", "call back": "callback", "new lead": "new", "lead": "new",
            "listed": "listed property"}.get(normalized, normalized)


def _status_snapshots(frame: pd.DataFrame, channel: str, reviews: list) -> pd.DataFrame:
    """A single resolved update per target; file order never decides status."""
    if frame.empty:
        return frame
    status_columns = ["status"] if channel == "CC" else ["phone_status"]
    targets = frame.apply(lambda row: row["_address_key"] if channel == "CC" and row["address"]
                          else f"phone:{row['phone']}", axis=1)
    repeated = targets.duplicated(keep=False)
    singles = frame.loc[~repeated]
    selected = []
    for _, group in frame.loc[repeated].groupby(targets.loc[repeated], sort=False):
        candidates = group
        # An undated snapshot cannot be chronologically compared to dated events.
        if group["event_date"].ne("").all():
            candidates = group.loc[group["event_date"].eq(group["event_date"].max())]
            if len(candidates) > 1:
                def clock_seconds(value):
                    for fmt in ("%H:%M:%S", "%H:%M", "%I:%M:%S %p", "%I:%M %p"):
                        try:
                            clock = datetime.strptime(value, fmt)
                            return clock.hour * 3600 + clock.minute * 60 + clock.second
                        except ValueError:
                            pass
                    return None
                clocks = candidates["source_time"].map(clock_seconds)
                if clocks.notna().all():
                    candidates = candidates.loc[clocks.eq(clocks.max())]
        row = candidates.iloc[0].copy()
        dispositions = candidates[status_columns].drop_duplicates()
        if len(dispositions) != 1:
            row[status_columns] = ""
            if channel != "CC":
                row["phone_tag"] = ""
            row["row_validation_status"] = "review"
            row["row_validation_reason"] = "conflicting_status_events"
            row["property_validation_reason" if channel == "CC" else "phone_validation_reason"] = "conflicting_status_events"
            for _, conflict in candidates.iterrows():
                reviews.append({**conflict.to_dict(), "review_target": "property" if channel == "CC" else "phone", "review_reason": "conflicting_status_events"})
        elif channel != "CC":
            row["phone_tag"] = ",".join(sorted({tag for tags in candidates["phone_tag"] for tag in tags.split(",") if tag}))
        # Ordinary subsequent activity does not withdraw an explicit opt-out.
        if channel == "CC" and group["status"].eq("dnc").any():
            row["status"] = "dnc"
        if channel != "CC" and group["phone_status"].str.contains("DNC", regex=False).any():
            base = row["phone_status"].replace(" DNC", "")
            row["phone_status"] = f"{base} DNC" if base in {"Correct", "Wrong"} else "DNC"
            row["phone_tag"] = ",".join(sorted({tag for tag in row["phone_tag"].split(",") if tag} | {"DNC"}))
        selected.append(row)
    resolved = pd.DataFrame(selected, columns=frame.columns)
    return pd.concat([singles, resolved]).sort_index(kind="stable").reset_index(drop=True)


def run_monthly_marketing(
    cold_csv_path: str | None, sms_csv_entries: list[tuple[str, str]], reporting_month: str,
    property_mapping: dict[str, str] | None = None,
    phone_mapping: dict[str, tuple[str, str]] | None = None,
) -> MonthlyMarketingResult:
    month = validate_reporting_month(reporting_month)
    if not cold_csv_path and not sms_csv_entries:
        raise ValueError("At least one cold calling or SMS input is required")
    property_mapping = PROPERTY_MAPPING if property_mapping is None else property_mapping
    phone_mapping = PHONE_MAPPING if phone_mapping is None else phone_mapping
    validate_mappings(property_mapping, phone_mapping)
    cold_rows, sms_rows, tag_rows, reviews, summaries, warnings = [], [], [], [], [], []
    unmapped = {"CC": set(), "SMS": set()}
    seen = set()
    entries = ([("CC", Path(cold_csv_path).name, cold_csv_path)] if cold_csv_path else [])
    entries += [("SMS", name, path) for name, path in sms_csv_entries]
    for channel, filename, path in entries:
        columns = [c.lstrip("\ufeff") for c in read_csv_header(path)]
        frame = smart_read_csv(path, dtype=str, usecols=columns)
        fields = {
            "phone": _column(frame.columns, "Phone", "Phone 1"),
            "address": _column(frame.columns, "Address", "Property address"),
            "city": _column(frame.columns, "City", "Property city"),
            "state": _column(frame.columns, "State", "Property state"),
            "zip": _column(frame.columns, "Zip Code", "Property zip", "Zip"),
        }
        status_col = _column(frame.columns, *(('Log Type',) if channel == "CC" else ('Labels', 'Label', 'Status')))
        if not fields["phone"]:
            raise ValueError(f"{filename}: Phone or Phone 1 column is required")
        if channel == "CC" and not status_col:
            raise ValueError(f"{filename}: Log Type column is required")
        date_col = _column(frame.columns, *DATE_COLUMNS)
        time_col = _column(frame.columns, "Log Time (Time)")
        summary = dict(source=filename, channel=channel, input_rows=len(frame), included_rows=0,
                       outside_month_rows=0, missing_date_rows=0, invalid_date_rows=0, duplicate_rows=0,
                       unusable_identity_rows=0)
        for index, source in frame.iterrows():
            row = {key: sanitize_text(source[col]) if col else "" for key, col in fields.items()}
            row["phone"] = sanitize_phone(row["phone"])
            row.update(source_file=filename, source_row=int(index) + 2, salesforce_new_status="", channel=channel)
            row["_phone_key"] = row["phone"]
            row["_address_key"] = make_address_key(row["address"], row["city"], row["state"], row["zip"])
            raw_status = sanitize_text(source[status_col]) if status_col else strip_trailing_count_from_filename(filename)
            labels = sorted({_status(s) for s in raw_status.split("|") if s.strip()})
            row.update(source_status=raw_status, normalized_status="|".join(labels))
            timing = resolve_event_date(source[date_col] if date_col else "", month, str(date_col or ""))
            date_status = timing.pop("date_status")
            row.update(timing, source_time=sanitize_text(source[time_col]) if time_col else "")
            if date_status in {"missing", "invalid", "outside_month"}:
                summary[{"missing": "missing_date_rows", "invalid": "invalid_date_rows", "outside_month": "outside_month_rows"}[date_status]] += 1
            if date_status in {"invalid", "outside_month"}:
                reviews.append({**row, "channel": channel, "review_reason": date_status + "_date"})
                continue
            identity = (channel, row["phone"], row["_address_key"], row["normalized_status"],
                        row["event_date"], row["event_month"], row["source_time"])
            if identity in seen:
                summary["duplicate_rows"] += 1
                continue
            seen.add(identity)
            if not row["phone"] and not row["address"]:
                summary["unusable_identity_rows"] += 1
                reviews.append({**row, "channel": channel, "review_reason": "missing_contact_identity"})
                continue
            resolution = resolve_labels(labels, property_mapping, phone_mapping)
            row.update(resolution)
            unmapped[channel].update(label for label in labels if label not in property_mapping or label not in phone_mapping)
            reason = ";".join(filter(None, [resolution["property_validation_reason"], resolution["phone_validation_reason"]]))
            row.update(row_validation_status="review" if reason else "ok", row_validation_reason=reason)
            if channel == "CC":
                cold_rows.append(row)
            else:
                sms_rows.append(row)
            summary["included_rows"] += 1
            for target in ("property", "phone"):
                if resolution[f"{target}_validation_reason"]:
                    reviews.append({**row, "review_target": target, "review_reason": resolution[f"{target}_validation_reason"]})
            if channel == "SMS" and ("agent untouched yet" in labels or not labels or
                                     all(label in {"undefined", "no label", "duplicate"} for label in labels)):
                reviews.append({**row, "channel": channel, "review_reason": "no_sms_activity_evidence"})
                continue
            # This tag describes the selected monthly source evidence, never a CRM stage
            # or a provider. Missing dates remain explicitly month-only in this export.
            tag = f"(MARKETING) {channel} - {int(month[5:])}/{month[:4]}"
            tag_rows.append({**row, "channel": channel, "tag": tag, "marketing_tag": tag,
                             "evidence_type": "call_log" if channel == "CC" else "sms_labels_snapshot"})
        if summary["missing_date_rows"]:
            warnings.append(f"{filename}: {summary['missing_date_rows']} rows have no event date; selected month is an explicit month-only fallback, not a verified send/call date.")
        if summary["invalid_date_rows"]:
            warnings.append(f"{filename}: {summary['invalid_date_rows']} invalid event dates excluded for review.")
        summaries.append(summary)
    columns = BASE_COLUMNS + ["status", "phone_status", "phone_tag"]
    cold = pd.DataFrame(cold_rows, columns=columns)
    sms = pd.DataFrame(sms_rows, columns=columns)
    combined = pd.concat([cold, sms], ignore_index=True)
    properties = _status_snapshots(combined, "CC", reviews)
    phones = _status_snapshots(combined.loc[combined["phone"].ne("")], "SMS", reviews)
    tags = pd.DataFrame(tag_rows, columns=BASE_COLUMNS + ["tag", "marketing_tag", "evidence_type"])
    if not tags.empty:
        tags = tags.drop_duplicates(subset=["_address_key", "phone", "tag", "date_source", "event_date"]).reset_index(drop=True)
    cold = properties.loc[properties["channel"].eq("CC")]
    sms = phones.loc[phones["channel"].eq("SMS")]
    counts = lambda rows, key: dict(Counter(row[key] for row in rows))
    return MonthlyMarketingResult(properties, phones, cold, sms, tags, pd.DataFrame(reviews, columns=BASE_COLUMNS + ["review_target", "review_reason"]),
        {"reporting_month": month, "sources": summaries, "warnings": warnings, "tag_counts": dict(Counter(tags["tag"])),
         "property_updates": int(properties["status"].ne("").sum()),
         "phone_updates": int(phones["phone_status"].ne("").sum()),
         "unmapped_by_target": {target: sorted({label for row in cold_rows + sms_rows for label in row[f"unmapped_{target}_labels"].split("|") if label}) for target in ("property", "phone")}},
        sorted(unmapped["CC"]), sorted(unmapped["SMS"]), counts(cold_rows, "normalized_status"),
        dict(Counter(cold["status"])), counts(sms_rows, "normalized_status"), dict(Counter(sms["phone_status"])))
