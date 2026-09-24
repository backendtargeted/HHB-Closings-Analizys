"""Gate 1 monthly imports: independent campaign activity and dated CRM milestones."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pandas as pd


def validate_report_month(value: str) -> str:
    if not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", value or "") or value[:4] == "0000":
        raise ValueError("report_month must be a valid YYYY-MM month")
    return value


def run_monthly_ingestion(report_month, *, cold_path=None, sms_entries=None,
                          qualified_leads=None, opportunities=None, transactions=None):
    """Return export frames and a JSON preview without overwriting historical statuses."""
    from .monthly_marketing import run_monthly_marketing
    from .monthly_salesforce import build_monthly_salesforce

    validate_report_month(report_month)
    sms_entries = sms_entries or []
    sf_paths = (qualified_leads, opportunities, transactions)
    if not cold_path and not sms_entries and not any(sf_paths):
        raise ValueError("Upload at least one calling, SMS, or Salesforce report")

    frames = {}
    sources, warnings, reviews = [], [], []
    tag_counts = {}
    metrics = {
        "cold_unmapped": [], "sms_unmapped": [], "crm_unmapped": [],
        "cold_input_counts": {}, "cold_output_counts": {},
        "sms_input_counts": {}, "sms_output_counts": {}, "closings_rows": 0,
    }
    samples = {name: [] for name in ("cold_calling", "sms", "salesforce_tags", "closings_tags", "marketing_tags", "review_rows")}

    def sample(frame):
        return frame.head(8).astype(object).where(frame.head(8).notna(), None).to_dict("records")

    if cold_path or sms_entries:
        marketing = run_monthly_marketing(cold_path, sms_entries, report_month)
        frames["property_status_updates.csv"] = marketing.property_df.loc[marketing.property_df["status"].ne("")].drop(columns=["phone_status", "phone_tag"]).copy()
        frames["phone_status_tags_updates.csv"] = marketing.phone_df.loc[marketing.phone_df["phone_status"].ne("")].drop(columns=["status"]).copy()
        samples["cold_calling"] = sample(frames["property_status_updates.csv"])
        samples["sms"] = sample(frames["phone_status_tags_updates.csv"])
        metrics.update({key: marketing.stats[key] for key in ("property_updates", "phone_updates", "unmapped_by_target")})
        frames["marketing_activity_tags.csv"] = marketing.marketing_tags_df
        reviews.append(marketing.review_df)
        sources.extend(marketing.stats["sources"])
        warnings.extend(marketing.stats["warnings"])
        tag_counts.update(marketing.stats["tag_counts"])
        for name in ("cold_unmapped", "sms_unmapped", "cold_input_counts", "cold_output_counts", "sms_input_counts", "sms_output_counts"):
            metrics[name] = getattr(marketing, name)
        samples["marketing_tags"] = sample(marketing.marketing_tags_df)
    if any(sf_paths):
        sf = build_monthly_salesforce(report_month, ql_path=qualified_leads,
                                     opportunities_path=opportunities, transactions_path=transactions)
        frames["salesforce_status_tags.csv"] = sf.tags
        frames["salesforce_events.csv"] = sf.events
        sources.extend(sf.summary["sources"])
        warnings.extend(sf.summary["warnings"])
        tag_counts.update(sf.summary["tag_counts"])
        reviews.append(sf.review)
        samples["salesforce_tags"] = sample(sf.tags)
        metrics["sf_tags_created_total"] = len(sf.tags)
    review = pd.concat(reviews, ignore_index=True).fillna("") if reviews else pd.DataFrame(columns=["reason"])
    frames["ingestion_review.csv"] = review
    if "review_reason" in review:
        review["reason"] = review.get("reason", pd.Series("", index=review.index)).replace("", pd.NA).fillna(review["review_reason"])
    samples["review_rows"] = sample(review)
    payload = {
        "metrics": metrics, "samples": samples,
        "monthly": {"report_month": report_month, "sources": sources, "available_exports": list(frames),
                    "warnings": list(dict.fromkeys(warnings)), "tag_counts": tag_counts},
    }
    return frames, payload


def write_monthly_exports(frames, payload, out_dir):
    """Persist exports once so the same reviewed run survives a server restart."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    for name, frame in frames.items():
        frame.to_csv(out_dir / name, index=False)
    (out_dir / "ingestion_summary.json").write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    (out_dir / "README.txt").write_text(
        f"Gate 1 monthly ingestion: {payload['monthly']['report_month']}\n\n"
        "Review ingestion_summary.json and ingestion_review.csv before importing.\n"
        "Import marketing_activity_tags.csv as PROPERTY tags using its tag column.\n"
        "Import salesforce_status_tags.csv as PROPERTY tags using salesforce_tag.\n"
        "Calling and SMS each produce both property and phone updates when supported.\n"
        "Map phone_tag as comma-separated custom phone tags; a blank value means no additional tag, never clear existing tags.\n"
        "Property and phone status CSVs contain only resolved mappings; historic snapshots can change current REISift statuses.\n"
        "salesforce_events.csv, ingestion_review.csv and summary files are audit evidence, not imports.\n"
        "Real event dates determine inclusion. Undated campaign rows use the selected month, never an invented day.\n"
        "Monthly campaigns do not identify a list provider. No Salesforce snapshot overwrites campaign evidence.\n",
        encoding="utf-8",
    )
