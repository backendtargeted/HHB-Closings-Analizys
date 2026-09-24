"""Read-only source audit. Does not modify report inputs or application code."""
import csv
import json
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
from app.services.buybox_towns import BUYBOX_TOWNS, in_buybox, normalize_town
from app.services.buybox_zips import BUYBOX_ZIPS, normalize_zip

SOURCE = Path(r"C:\Users\USER\Downloads\reproject (1)")
OUT = Path(__file__).parent
csv.field_size_limit(20_000_000)

def decisions(city, zip_raw):
    z = normalize_zip(zip_raw)
    town = normalize_town(city) in BUYBOX_TOWNS
    zip_match = z in BUYBOX_ZIPS
    current = in_buybox(city, zip_raw)
    proposed = zip_match if z else town
    category = (
        "zip_allowed" if zip_match else
        "present_zip_outside_list_city_allowed" if z and town else
        "present_zip_outside_list_city_not_allowed" if z else
        "missing_zip_city_allowed" if town else "missing_zip_city_not_allowed"
    )
    return z, current, proposed, category

def profile_csv(name, city_col, zip_col, sold=False):
    counts = Counter()
    changes = Counter()
    changed_investor = Counter()
    months = {}
    grains_current, grains_proposed, grains_all = set(), set(), set()
    examples = []
    with (SOURCE / name).open(encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for n, row in enumerate(reader, 1):
            city, zip_raw = row.get(city_col, ""), row.get(zip_col, "")
            z, current, proposed, category = decisions(city, zip_raw)
            counts["rows"] += 1
            counts[category] += 1
            counts["current_included"] += current
            counts["zip_first_included"] += proposed
            counts["blank_zip"] += not bool(zip_raw.strip())
            counts["nonblank_unusable_zip"] += bool(zip_raw.strip()) and z is None
            if current and not proposed:
                changes[(z or "", city)] += 1
                if row.get("investor", "").lower() in ("true", "1", "yes"):
                    changed_investor[(z or "", city)] += 1
                if len(examples) < 8:
                    examples.append({"source_row": n + 1, "city": city, "zip": zip_raw})
            if sold:
                month = row.get("period_date", "") or row.get("period_label", "")
                bucket = months.setdefault(month, Counter())
                bucket["raw"] += 1
                bucket["current"] += current
                bucket["zip_first"] += proposed
                identity = row.get("dataflik_id") or row.get("address_key")
                grain = (identity, month)
                grains_all.add(grain)
                if current:
                    grains_current.add(grain)
                if proposed:
                    grains_proposed.add(grain)
            if n % 200000 == 0:
                print(f"Scanned {name}: {n:,} rows", flush=True)
    result = {"file": name, "counts": dict(counts), "changed_zip_city": [
        {"zip": z, "city": city, "rows": count, "investor_rows": changed_investor[(z, city)]}
        for (z, city), count in changes.most_common()
    ], "examples": examples}
    if sold:
        result["by_month"] = {m: dict(c) for m, c in sorted(months.items())}
        result["property_month_counts_by_source_id"] = {"raw": len(grains_all), "current": len(grains_current), "zip_first": len(grains_proposed)}
    (OUT / (name.removesuffix(".csv") + "_audit.json")).write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in result.items() if k != "changed_zip_city"}, indent=2), flush=True)
    print("Top ZIP/city changes:", json.dumps(result["changed_zip_city"][:20], indent=2), flush=True)

print(json.dumps({"allowlist_zip_count": len(BUYBOX_ZIPS), "town_count": len(BUYBOX_TOWNS)}), flush=True)
profile_csv("sold_properties_full.csv", "property_city", "property_zip", sold=True)
profile_csv("reisift_export.csv", "Property city", "Property zip5")
