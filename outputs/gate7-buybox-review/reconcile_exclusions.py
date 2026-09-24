"""Compile a review candidate from the user's confirmed suppression document."""
import csv
import json
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
from app.services.buybox_towns import in_buybox, normalize_town
from app.services.buybox_zips import normalize_zip

OUT = Path(__file__).parent
SOURCE = Path(r"C:\Users\USER\Downloads\reproject (1)")
doc = (ROOT / "docs/BUYBOX_8020REI.md").read_text(encoding="utf-8")
section = doc.split("## 13. Suppressed towns — source list", 1)[1].split("## Gaps", 1)[0]
zip_sources, city_sources = {}, {}
for line in section.splitlines():
    if not line.startswith("| "):
        continue
    cells = [c.strip() for c in line.strip().strip("|").split("|")]
    if len(cells) != 5 or cells[0] == "Town":
        continue
    town, zip_cell, dm, tina, rei = cells
    sources = [label for label, value in (("DM-Sept", dm), ("Tina", tina), ("8020 zip list", rei)) if value]
    if not sources:
        continue
    for name in town.split(" / "):
        city_sources.setdefault(normalize_town(name), []).append({"source_town": town, "sources": sources})
    for z in re.findall(r"\b\d{5}\b", zip_cell):
        z_sources = [label for label, value in (("DM-Sept", dm), ("Tina", tina)) if value]
        if rei and ("only" not in rei or z in re.findall(r"\b\d{5}\b", rei)):
            z_sources.append("8020 zip list")
        if z_sources:
            zip_sources.setdefault(z, []).append({"source_town": town, "sources": z_sources})
# These explicit alternate spellings already occur in the app/source data.
aliases = {"westhampton beach": "west hampton beach", "e moriches": "east moriches"}
for alias, name in aliases.items():
    if name in city_sources:
        city_sources[alias] = [{"alias_of": name}]
excluded_zips, excluded_cities = set(zip_sources), set(city_sources)
candidate = {"status": "review candidate; not applied to application", "source": "docs/BUYBOX_8020REI.md section 13",
    "rule": "NY Nassau/Suffolk only; union of all suppression sources; ZIP authoritative; city fallback only without ZIP. Preview treats unusable ZIPs as missing; malformed nonblank ZIP policy remains to be defined (none in supplied sold CSV).",
    "excluded_zips": sorted(excluded_zips), "excluded_cities": sorted(excluded_cities),
    "zip_provenance": zip_sources, "city_provenance": city_sources}
(OUT / "candidate_exclusions.json").write_text(json.dumps(candidate, indent=2), encoding="utf-8")

counts = Counter()
counties = Counter()
by_month = {}
zip_rejections = Counter()
with (SOURCE / "sold_properties_full.csv").open(encoding="utf-8-sig", newline="") as f:
    for row in csv.DictReader(f):
        counts["raw_rows"] += 1
        county = row["county"].strip().casefold()
        state = row["state"].strip().casefold()
        z = normalize_zip(row["property_zip"])
        city = normalize_town(row["property_city"])
        geo = county in ("nassau", "suffolk") and state in ("ny", "new york")
        old = in_buybox(row["property_city"], row["property_zip"])
        if old:
            counties[row["county"]] += 1
        rejection = ("excluded_zip" if z in excluded_zips else None) if z else (
            "excluded_city_without_zip" if city in excluded_cities else
            "no_zip_or_city" if not city else None)
        counts["nassau_suffolk_rows"] += geo
        accepted = geo and rejection is None
        counts["candidate_geography_accepted"] += accepted
        counts["current_accepted"] += old
        counts["current_accepted_outside_nassau_suffolk"] += old and not geo
        counts["candidate_removed_from_current"] += old and not accepted
        counts["candidate_added_to_current"] += accepted and not old
        if geo and rejection:
            counts[rejection] += 1
            zip_rejections[(z or "", row["property_city"])] += 1
        m = by_month.setdefault(row["period_date"], Counter())
        m["raw"] += 1
        m["current"] += old
        m["nassau_suffolk"] += geo
        m["candidate"] += accepted
summary = {"counts": dict(counts), "current_included_by_county": dict(counties.most_common()),
    "by_month": {k: dict(v) for k,v in sorted(by_month.items())},
    "top_candidate_exclusions": [{"zip": z, "city": c, "rows": n} for (z,c), n in zip_rejections.most_common(30)],
    "excluded_zip_count": len(excluded_zips), "excluded_city_key_count": len(excluded_cities)}
(OUT / "candidate_impact.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
print(json.dumps(summary, indent=2))
