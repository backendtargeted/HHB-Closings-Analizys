"""Validate the small buybox-only detail subset against earliest sold observations."""
import csv
import json
import re
from collections import Counter, defaultdict
from decimal import Decimal, InvalidOperation
from pathlib import Path

OUT = Path(__file__).parent
metrics = json.loads((OUT / "verified_report_metrics.json").read_text())
targets = {r["dataflik_id"]: r for r in metrics["rows"]}
sold = defaultdict(list)
def name_key(v):
    return re.sub(r"[^A-Z0-9]", "", str(v or "").upper())
def price_key(v):
    try:
        return Decimal(re.sub(r"[$,\s]", "", str(v)))
    except InvalidOperation:
        return None
with Path(r"C:\Users\USER\Downloads\reproject (1)\sold_properties_full.csv").open(encoding="utf-8-sig", newline="") as f:
    for r in csv.DictReader(f):
        pid = r["dataflik_id"]
        if pid in targets and r["period_date"][:7] == targets[pid]["sold_month"]:
            sold[pid].append(r)

parcel_verified = set()
history_month = set()
exact_event = defaultdict(set)
valid_types = {}
field_counts = defaultdict(set)
status = Counter()
zip_available = 0
street_available = 0
example_evidence = []
with (OUT / "buybox_property_details.jsonl").open(encoding="utf-8") as f:
    for line in f:
        item = json.loads(line)
        pid = item["dataflik_id"]
        zip_available += bool(item["property_address"].get("postal_code"))
        street_available += bool(item["property_address"].get("street"))
        checks = item["identity_checks"]
        if not checks["county_match"] or not checks["parcel_match"]:
            continue
        parcel_verified.add(pid)
        prop = item["property"]
        valid_types[pid] = (prop.get("property_type"), item.get("units_count"))
        for key in ("property_type", "years_built", "building_square_feet", "living_square_feet", "lot_sqrf", "total_market_value"):
            if prop.get(key) is not None and prop.get(key) != "":
                field_counts[key].add(pid)
        for h in item["earliest_month_transactions"]:
            if not h.get("seller_name"):
                continue
            history_month.add(pid)
            for s in sold[pid]:
                if (name_key(h.get("buyer_name")) and name_key(h.get("buyer_name")) == name_key(s["buyer_full_name"])
                    and price_key(h.get("sale_price")) is not None and price_key(h.get("sale_price")) == price_key(s["sale_amount"])):
                    exact_event[pid].add((h.get("sale_date"),name_key(h["seller_name"]),name_key(h["buyer_name"]),str(price_key(h["sale_price"]))))
        if len(example_evidence)<3:
            example_evidence.append({"dataflik_id":pid,"earliest_month_history_count":len(item["earliest_month_transactions"]),"matching_event_count":len(exact_event.get(pid,[]))})

type_counts = Counter()
for pid,(t,u) in valid_types.items():
    if t == "single_family_residence":
        category = "SFH"
    elif t in ("multi_family_residential", "multi_family_commercial") and u is not None and 2 <= u <= 9:
        category = "2-9 units"
    elif t in ("condo","land_residential") or (u is not None and u > 9):
        category = "outside_documented_property_types"
    else:
        category = "property_type_or_units_unresolved"
    type_counts[category] += 1
summary={"target_properties":len(targets),"county_and_parcel_verified_properties":len(parcel_verified),
    "verified_property_with_earliest_month_seller":len(history_month),
    "verified_property_with_month_buyer_price_matching_seller":sum(bool(v) for v in exact_event.values()),
    "verified_property_with_unique_month_buyer_price_matching_seller_event":sum(len(v)==1 for v in exact_event.values()),
    "verified_property_with_multiple_matching_seller_events":sum(len(v)>1 for v in exact_event.values()),
    "detail_lines_with_returned_address_zip":zip_available,"detail_lines_with_returned_address_street":street_available,
    "property_type_screen_among_identity_verified":dict(type_counts),
    "available_fields_among_identity_verified":{k:len(v) for k,v in field_counts.items()},
    "notes":["Parcel equality uses uppercase alphanumeric form plus matching county.","Event match requires earliest sold month plus normalized buyer name and exact amount; source does not expose a matching deed ID.","Property attributes are September 2026 snapshots, not proven as-of-sale values.","No ownership categories inferred or re-enabled."]}
(OUT / "validated_details_summary.json").write_text(json.dumps(summary,indent=2),encoding="utf-8")
print(json.dumps(summary,indent=2))
