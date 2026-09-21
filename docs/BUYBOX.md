# Gate 7 buybox (marketed towns) — locked contract

This document is the **operator contract** for Gate 7 Investor & In-List Sold geography.
The report is used to judge **list / data-provider coverage inside markets HHB actually markets**.
Treat KPIs as **buybox-scoped**, not statewide NY performance.

**Code source of truth for membership:** `backend/app/services/buybox_towns.py`  
**Filter point:** sold CSV ingest in `backend/app/services/investor_sold.py` (before row build / enrich / KPIs).

---

## Why this exists

Gate 7 answers: *Among sales in towns we market, did we (or our lists) cover the property before an investor closed?*

If the universe included Buffalo / Albany / upstate / random NY cities we do not market, "never prospected" and pipeline-empty rates would look catastrophic for the wrong reason — those sales were **never in scope**. The buybox keeps the report honest when evaluating a provider.

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
- Membership = normalized city ∈ `BUYBOX_TOWNS` (214 distinct normalized keys from 216 label spellings).
- Typo / alias spellings from the scrape are **kept as allowlist entries** so real marketed sales are not excluded for spelling (see below).

### Duplicate label norms (same city, two spellings in source list)

- `east northport` ← `East Northport`, `East Northport,`
- `huntington` ← `Huntington`, `Huntington,`

### Intentional scrape aliases / typos kept on the allowlist

These are **not** separate markets — they exist so dirty `property_city` values still match:

- `Blue Poin` (alias of Blue Point)
- `FRANKLIN SQUAR` (alias of Franklin Square)
- `GardenCity` (alias of Garden City)
- `Hicksvill` (alias of Hicksville)
- `Hauppaüge` (alias of Hauppauge)
- `Patchog` (alias of Patchogue)
- `Seiden` (alias of Selden)
- `StIslip` (alias of Islip family (scrape spelling))
- `E Farmingdale` (alias of East Farmingdale)
- `E Moriches` (alias of East Moriches)
- `E Northport` (alias of East Northport)
- `N babylon` (alias of North Babylon)
- `W babylon` (alias of West Babylon)
- `Mt Sinai` (alias of Mount Sinai)
- `St James` (alias of Saint James)
- `Bayshore` (alias of Bay Shore)
- `Setauket- East Setauket` (alias of Setauket / East Setauket)

---

## How to read Gate 7 KPIs (provider evaluation)

| KPI | Meaning **inside buybox only** | Do **not** read as |
|-----|--------------------------------|--------------------|
| **Never prospected (investor)** | Investor sale in a marketed town, not HHB-closed, no 8020 / Court Alerts / LI Profiles Prospect list | "Provider missed all of NY" |
| **Lost to investor** | We had presence (scrape In My Records **or** REISift/CRM) + investor + not closed | Failures outside marketed towns |
| **Pipeline depth / No list history** | Furthest stage among **buybox** sales | Statewide emptiness |
| **In Our List** segment | Scrape `in_my_records` among buybox sales | Same as "has Prospect tags" |

When presenting to stakeholders: always say **"among marketed-town sales"** (or cite buybox town count + excluded scrape rows from the header).

---

## Updating the buybox

1. Edit `_BUYBOX_TOWN_LABELS` in `backend/app/services/buybox_towns.py` (add scrape spellings you see in the wild).
2. Add/adjust unit tests in `backend/tests/test_buybox_towns.py`.
3. Re-run `python backend/scripts/gen_buybox_doc.py` to refresh this appendix, or update it manually.
4. Update SOP / methodology one-liners only if the *meaning* of the universe changes.
5. Re-run Gate 7; confirm header excluded-count moves as expected.

Do **not** change the CleanREISift scraper to shrink geography unless product explicitly wants a smaller scrape — Closings owns the analysis universe.

---

## Appendix — allowlist cities (214 normalized)

Canonical display spellings (one per normalized key). Full alias spellings live in code.

- Albertson
- Alden Manor
- Amity Harbor
- Amityville
- Astoria
- Babylon
- Baldwin
- Bay Shore
- Bayport
- Bayshore
- Bayside
- Bayville
- Beechhurst
- Belle Harbor
- Bellerose
- Bellerose Terrace
- Bellerose Village
- Bellmore
- Bellport
- Bethpage
- Blue Poin
- Blue Point
- Bohemia
- Breezy Point
- Brentwood
- Brightwaters
- Broad Channel
- Brookhaven
- Brooklyn
- Brookville
- Calverton
- Cambria Heights
- Carle Place
- Center Moriches
- Centereach
- Centerport
- Central Islip
- Cold Spring Harbor
- Commack
- Copiague
- Coram
- Corona
- Deer Park
- Dix Hills
- E Farmingdale
- E Moriches
- E Northport
- East Elmhurst
- East Islip
- East Marion
- East Massapequa
- East Meadow
- East Moriches
- East Northport
- East Patchogue
- East Rockaway
- East Setauket
- East Williston
- Eastport
- Elmhurst
- Elmont
- Elwood
- Far Rockaway
- Farmingdale
- Farmingville
- Flanders
- Floral Park
- Flushing
- Fort Salonga
- FRANKLIN SQUAR
- Franklin Square
- Freeport
- Garden City
- Garden City Park
- Garden City South
- GardenCity
- Glen Cove
- Glen Oaks
- Great River
- Greenlawn
- Greenvale
- Hauppauge
- Hauppaüge
- Hempstead
- Hicksvill
- Hicksville
- Holbrook
- Hollis
- Holtsville
- Howard Beach
- Huntington
- Huntington Bay
- Huntington Station
- Inwood
- Island Park
- Islandia
- Islip
- Islip Terrace
- Jamaica
- Jericho
- Kew Gardens
- Kings Park
- Lake Grove
- Lake Ronkonkoma
- Latham
- Levittown
- Lido Beach
- Lindenhurst
- Little Neck
- Lloyd Harbor
- Long Beach
- Lynbrook
- Malba
- Malverne
- Manhasset
- Manhasset Hills
- Manorville
- Maspeth
- Massapequa
- Massapequa Park
- Mastic
- Mastic Beach
- Matinecock
- Medford
- Melville
- Merrick
- Middle Island
- Middle Village
- Miller Place
- Mineola
- Moriches
- Mount Sinai
- Mt Sinai
- N babylon
- Nesconset
- New Hyde Park
- North Amityville
- North Babylon
- North Baldwin
- North Bellmore
- North Lynbrook
- North Massapequa
- North Merrick
- North New Hyde Park
- North Patchogue
- North Sea
- North Valley Stream
- Northport
- Oakdale
- Oakland Gardens
- Ocean Bay Park
- Ocean Beach
- Oceanside
- Old Bethpage
- Old Westbury
- Oyster Bay
- Ozone Park
- Patchog
- Patchogue
- Plainview
- Port Jefferson
- Port Jefferson Station
- Port Washington
- Queens Village
- Richmond Hill
- Ridge
- Ridgewood
- Riverhead
- Rockville Centre
- Rocky Point
- Ronkonkoma
- Roosevelt
- Rosedale
- Saint Albans
- Saint James
- Sayville
- Seaford
- Seiden
- Selden
- Setauket
- Setauket- East Setauket
- Shirley
- Smithtown
- Sound Beach
- South Farmingdale
- South Floral Park
- South Hempstead
- South Huntington
- South Ozone Park
- South Richmond Hill
- South Setauket
- Southold
- Springfield Gardens
- St James
- Stewart Manor
- StIslip
- Stony Brook
- Sunnyside
- Syosset
- Uniondale
- Valley Stream
- W babylon
- Wading River
- Wantagh
- West Babylon
- West Hempstead
- West Islip
- West Sayville
- Westbury
- Westhampton Beach
- Wheatley Heights
- Woodside
- Wyandanch
- Yaphank

---

## Related

- [SOP.md](SOP.md) — Gate 7 operator summary
- [REPORT_METHODOLOGY.md](REPORT_METHODOLOGY.md) §21 — Gate 7 methodology
- [ECOSYSTEM.md](ECOSYSTEM.md) — CleanREISift sold CSV → Closings
