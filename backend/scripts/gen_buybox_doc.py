"""Generate docs/BUYBOX.md from buybox_towns.py."""
from __future__ import annotations

import sys
from collections import defaultdict
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
ROOT = BACKEND.parent
sys.path.insert(0, str(BACKEND))

from app.services.buybox_towns import BUYBOX_TOWN_COUNT, _BUYBOX_TOWN_LABELS, normalize_town

OUT = ROOT / "docs" / "BUYBOX.md"

labels = list(_BUYBOX_TOWN_LABELS)
by_norm: dict[str, list[str]] = defaultdict(list)
for t in labels:
    by_norm[normalize_town(t)].append(t)


def display(vals: list[str]) -> str:
    for x in vals:
        if not x.endswith(","):
            return x
    return vals[0]


canonical = sorted((display(v) for v in by_norm.values()), key=str.casefold)
alias_lines = []
for key, vals in sorted(by_norm.items()):
    if len(vals) > 1:
        joined = ", ".join(f"`{x}`" for x in vals)
        alias_lines.append(f"- `{key}` ← {joined}")

typo_examples = [
    ("Blue Poin", "Blue Point"),
    ("FRANKLIN SQUAR", "Franklin Square"),
    ("GardenCity", "Garden City"),
    ("Hicksvill", "Hicksville"),
    ("Hauppaüge", "Hauppauge"),
    ("Patchog", "Patchogue"),
    ("Seiden", "Selden"),
    ("StIslip", "Islip family (scrape spelling)"),
    ("E Farmingdale", "East Farmingdale"),
    ("E Moriches", "East Moriches"),
    ("E Northport", "East Northport"),
    ("N babylon", "North Babylon"),
    ("W babylon", "West Babylon"),
    ("Mt Sinai", "Mount Sinai"),
    ("St James", "Saint James"),
    ("Bayshore", "Bay Shore"),
    ("Setauket- East Setauket", "Setauket / East Setauket"),
]

towns_md = "\n".join(f"- {t}" for t in canonical)
alias_block = "\n".join(alias_lines) if alias_lines else "_None._"
typo_block = "\n".join(f"- `{a}` (alias of {b})" for a, b in typo_examples)

doc = f"""# Gate 7 buybox (marketed towns) — locked contract

This document is the **operator contract** for Gate 7 Investor & In-List Sold geography.
The report is used to judge **list / data-provider coverage inside markets HHB actually markets**.
Treat KPIs as **buybox-scoped**, not statewide NY performance.

**Code source of truth for membership:** `backend/app/services/buybox_towns.py`  
**Filter point:** sold CSV ingest in `backend/app/services/investor_sold.py` (before row build / enrich / KPIs).

---

## Why this exists

Gate 7 answers: *Among sales in towns we market, did we (or our lists) cover the property before an investor closed?*

If the universe included Buffalo / Albany / upstate / random NY cities we do not market, \"never prospected\" and pipeline-empty rates would look catastrophic for the wrong reason — those sales were **never in scope**. The buybox keeps the report honest when evaluating a provider.

---

## What HHB buybox means here

Operational buybox (marketing geography) is the **allowlist of cities/towns we market to**, maintained in code.

Related product context (not all enforceable from the sold scrape):

| Buybox idea | In Gate 7 today? | Why |
|-------------|------------------|-----|
| Marketed **towns / cities** (this allowlist) | **Yes — hard filter** | Sold CSV has `property_city` |
| NY state sales | Implicit in scrape | Scrape is NY-oriented; we do not add a second state gate |
| Nassau / Suffolk county only | **No** | Allowlist also includes Queens / Brooklyn / nearby cities we market (e.g. Astoria, Jamaica, Flushing, Brooklyn) |
| Property type SFH / 2–9 units | **No** | Sold CSV has **no** property-type column |
| Buybox score / action-plan bands | **No** | Not on sold CSV |
| Recommended max list / channel caps | **No** | Not on sold CSV |

**Rule:** Filter with **every sold-report field that maps cleanly to buybox**. Today that is **`property_city`** (normalized). Do not invent county-only or property-type filters that the sold file cannot support — that would silently drop marketed towns or pretend precision we do not have.

---

## How filtering works

1. CleanREISift may still scrape statewide `sold_properties_full.csv`.
2. Gate 7 `analyze()` reads each sold row and keeps it **only if** `in_buybox(property_city)`.
3. Non-matching cities (and blank city) are **dropped at ingest** — they never become `InvestorSoldRow`s, never enrich, never enter Never prospected / Lost / pipeline.
4. Transparency only (not a KPI): `sold_rows_scanned`, `sold_rows_excluded_buybox`, `sold_rows_ingested`, `buybox_town_count` on the report header / Summary sheet / methodology note.

### City matching

- `normalize_town`: strip → strip trailing `,;.` → collapse whitespace → `casefold`.
- Membership = normalized city ∈ `BUYBOX_TOWNS` ({BUYBOX_TOWN_COUNT} distinct normalized keys from {len(labels)} label spellings).
- Typo / alias spellings from the scrape are **kept as allowlist entries** so real marketed sales are not excluded for spelling (see below).

### Duplicate label norms (same city, two spellings in source list)

{alias_block}

### Intentional scrape aliases / typos kept on the allowlist

These are **not** separate markets — they exist so dirty `property_city` values still match:

{typo_block}

---

## How to read Gate 7 KPIs (provider evaluation)

| KPI | Meaning **inside buybox only** | Do **not** read as |
|-----|--------------------------------|--------------------|
| **Never prospected (investor)** | Investor sale in a marketed town, not HHB-closed, no 8020 / Court Alerts / LI Profiles Prospect list on or before that property's sold month end; pre-report history still counts | \"Provider missed all of NY\" |
| **Lost to investor** | We had presence (scrape In My Records **or** REISift/CRM) + investor + not closed | Failures outside marketed towns |
| **Pipeline depth / No list history** | Furthest stage among **buybox** sales | Statewide emptiness |
| **In Our List** segment | Scrape `in_my_records` among buybox sales | Same as \"has Prospect tags\" |

When presenting to stakeholders: always say **\"among marketed-town sales\"** (or cite buybox town count + excluded scrape rows from the header).

Headline Marketed → Closed cards are cumulative **“reached at least”** counts. Each card's percentage is divided by all buybox property × sold-month rows, so Closed is included in Opportunity and every earlier pipeline stage even when a separate lower-stage source file did not match.

---

## Updating the buybox

1. Edit `_BUYBOX_TOWN_LABELS` in `backend/app/services/buybox_towns.py` (add scrape spellings you see in the wild).
2. Add/adjust unit tests in `backend/tests/test_buybox_towns.py`.
3. Re-run `python backend/scripts/gen_buybox_doc.py` to refresh this appendix, or update it manually.
4. Update SOP / methodology one-liners only if the *meaning* of the universe changes.
5. Re-run Gate 7; confirm header excluded-count moves as expected.

Do **not** change the CleanREISift scraper to shrink geography unless product explicitly wants a smaller scrape — Closings owns the analysis universe.

---

## Appendix — allowlist cities ({BUYBOX_TOWN_COUNT} normalized)

Canonical display spellings (one per normalized key). Full alias spellings live in code.

{towns_md}

---

## Related

- [SOP.md](SOP.md) — Gate 7 operator summary
- [REPORT_METHODOLOGY.md](REPORT_METHODOLOGY.md) §21 — Gate 7 methodology
- [ECOSYSTEM.md](ECOSYSTEM.md) — CleanREISift sold CSV → Closings
"""

OUT.write_text(doc, encoding="utf-8")
print(f"wrote {OUT} bytes={OUT.stat().st_size} towns={len(canonical)}")
