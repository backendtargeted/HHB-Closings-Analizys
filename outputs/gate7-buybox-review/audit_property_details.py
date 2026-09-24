"""Stream details JSONL; retain compact records only for the approved sold universe."""
import csv
import json
import re
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

OUT = Path(__file__).parent
SOURCE = Path(r"D:\HHB\CleanREISift\data\sold_property_details.jsonl")
metrics = json.loads((OUT / "verified_report_metrics.json").read_text(encoding="utf-8"))
targets = {r["dataflik_id"]: r for r in metrics["rows"]}
parcels = defaultdict(set)
with Path(r"C:\Users\USER\Downloads\reproject (1)\sold_properties_full.csv").open(encoding="utf-8-sig", newline="") as f:
    for row in csv.DictReader(f):
        if row["dataflik_id"] in targets and row.get("parcel_number"):
            parcels[row["dataflik_id"]].add(re.sub(r"[^A-Z0-9]", "", row["parcel_number"].upper()))

def month(value):
    value = str(value or "").strip()
    for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%m/%d/%Y", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(value[:19] if "T" in value or " " in value else value, fmt).strftime("%Y-%m")
        except ValueError:
            pass
    if re.match(r"^\d{4}-\d{2}-\d{2}", value):
        return value[:7]
    return ""

counts = Counter()
covered = set()
valid_detail_ids = set()
matched_seller_ids = set()
seller_by_id = defaultdict(set)
identity_by_id = defaultdict(set)
property_types = Counter()
property_uses = Counter()
units = Counter()
field_ids = defaultdict(set)
latest_enriched = Counter()
first_id = re.compile(rb'^\s*\{\s*"dataflik_id"\s*:\s*"([^"\\]+)"')
output_path = OUT / "buybox_property_details.jsonl"
with SOURCE.open("rb") as source, output_path.open("w", encoding="utf-8") as dest:
    for line_number, raw in enumerate(source, 1):
        counts["source_lines"] += 1
        counts["max_line_bytes"] = max(counts["max_line_bytes"], len(raw))
        id_match = first_id.match(raw[:1024])
        if id_match and id_match.group(1).decode("utf-8") not in targets:
            counts["skipped_outside_target_ids"] += 1
            continue
        try:
            item = json.loads(raw)
        except (ValueError, UnicodeDecodeError):
            counts["invalid_json_lines"] += 1
            continue
        pid = str(item.get("dataflik_id") or "")
        if pid not in targets:
            counts["skipped_outside_target_ids"] += 1
            continue
        counts["target_lines"] += 1
        covered.add(pid)
        counts["error_lines"] += bool(item.get("error"))
        prop = item.get("property") or {}
        detail = (item.get("raw") or {}).get("detail") or {}
        address = (item.get("address_info") or {}).get("address") or {}
        history = (item.get("history") or {}).get("transactions") or []
        if prop:
            valid_detail_ids.add(pid)
        target = targets[pid]
        returned_apn = re.sub(r"[^A-Z0-9]", "", str(prop.get("apn") or "").upper())
        county_ok = str(prop.get("county") or "").strip().casefold() == target["county"].strip().casefold()
        returned_zip = str(address.get("postal_code") or "").split("-")[0]
        zip_ok = returned_zip == target["zip"].split("-")[0]
        apn_ok = returned_apn in parcels[pid] if returned_apn else False
        if prop:
            identity_by_id[pid].add((county_ok, zip_ok, apn_ok))
        counts["target_lines_county_matches"] += county_ok
        counts["target_lines_zip_matches"] += zip_ok
        counts["target_lines_parcel_matches"] += apn_ok
        matched_history = [h for h in history if month(h.get("sale_date")) == target["sold_month"]]
        sellers = {str(h.get("seller_name") or "").strip() for h in matched_history} - {""}
        if sellers:
            matched_seller_ids.add(pid)
            seller_by_id[pid].update(sellers)
        for key in ("property_type", "property_use", "years_built", "living_square_feet", "lot_sqrf", "total_market_value"):
            if prop.get(key) is not None and prop.get(key) != "":
                field_ids[key].add(pid)
        if detail.get("units_count") is not None:
            field_ids["units_count"].add(pid)
        property_types[str(prop.get("property_type") or "(missing)")] += 1
        property_uses[str(prop.get("property_use") or "(missing)")] += 1
        units[str(detail.get("units_count"))] += 1
        latest_enriched[str(item.get("enriched_utc") or "")[:10]] += 1
        # Keep useful source attributes and history; omit duplicated raw API payload/geometry/comps.
        dest.write(json.dumps({
            "source_line": line_number, "dataflik_id": pid, "transaction_id": item.get("transaction_id"),
            "sold_month": target["sold_month"], "detail_period_date": item.get("period_date"),
            "enriched_utc": item.get("enriched_utc"), "error": item.get("error"),
            "identity_checks": {"county_match": county_ok, "zip_match": zip_ok, "parcel_match": apn_ok},
            "resolved_address": item.get("resolved_address"), "property_address": address,
            "property": prop, "units_count": detail.get("units_count"),
            "history_transactions": history, "earliest_month_transactions": matched_history,
            "history_mortgages": (item.get("history") or {}).get("mortgages") or [],
        }, ensure_ascii=False) + "\n")
        if counts["target_lines"] % 1000 == 0:
            print(f"Retained {counts['target_lines']:,} target lines; scanned {line_number:,}", flush=True)

summary = {"source_bytes": SOURCE.stat().st_size, "target_properties": len(targets),
    "counts": dict(counts), "covered_target_properties": len(covered),
    "target_properties_missing_details": len(set(targets) - covered),
    "properties_with_nonempty_detail": len(valid_detail_ids),
    "properties_with_all_identity_checks_matching": sum(any(all(v) for v in checks) for checks in identity_by_id.values()),
    "properties_with_earliest_month_seller_name": len(matched_seller_ids),
    "properties_with_single_distinct_earliest_month_seller": sum(len(v) == 1 for v in seller_by_id.values()),
    "properties_with_seller_and_all_identity_checks": sum(pid in seller_by_id and any(all(v) for v in checks) for pid,checks in identity_by_id.items()),
    "available_fields_property_counts": {k:len(v) for k,v in field_ids.items()},
    "property_type_counts_per_detail_line": dict(property_types.most_common()),
    "property_use_counts_per_detail_line": dict(property_uses.most_common()),
    "unit_counts_per_detail_line": dict(units.most_common()),
    "enrichment_dates": dict(latest_enriched), "filtered_bytes": output_path.stat().st_size}
(OUT / "property_details_audit.json").write_text(json.dumps(summary,indent=2),encoding="utf-8")
print(json.dumps(summary,indent=2),flush=True)
