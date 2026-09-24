# Gate 7 buybox (marketed towns) — locked contract

This document is the **operator contract** for Gate 7 Investor & In-List Sold geography.
The report is used to judge **list / data-provider coverage inside markets HHB actually markets**.
Treat KPIs as **buybox-scoped**, not statewide NY performance.

**Code source of truth for membership:** `backend/app/services/buybox_towns.py` (town list) and `backend/app/services/buybox_zips.py` (zip list, added 2026-09-23) — either match is enough  
**Filter point:** sold CSV ingest in `backend/app/services/investor_sold.py` (before row build / enrich / KPIs).

---

## Why this exists

Gate 7 answers: *Among sales in towns we market, did we (or our lists) cover the property before an investor closed?*

If the universe included Buffalo / Albany / upstate / random NY cities we do not market, "never prospected" and pipeline-empty rates would look catastrophic for the wrong reason — those sales were **never in scope**. The buybox keeps the report honest when evaluating a provider.

---

## What HHB buybox means here

**Locked definition (2026-09-21, geography mechanism updated 2026-09-23):** "Buybox" is exactly two things — (1) marketed geography below (two flat allowlists, a zip list and a town list, maintained in code — a sold row is in-buybox if it matches *either*) and (2) **REISift's own Buybox report** (its native scoring UI — the screenshot with Market properties, Buybox score, Action-plan 30/60/90 days, Recommended max list, Total reach, Client deals by county). Nothing else is "buybox" logic. In particular: `investor_score` on the sold CSV is **not** part of the buybox — see the note below the table. Also not part of it: 8020REI's own product Buybox tool's compound "Buybox score" column (property type / owner type / LTV / value / etc. weighted score) — see "Zip matching" below for why that score isn't used at all, not even to build the zip list.

Related product context (not all enforceable from the sold scrape):

| Buybox idea | In Gate 7 today? | Why |
|-------------|------------------|-----|
| Marketed **zip codes** | **Yes — hard filter** | Sold CSV has `property_zip`; flat list derived from `docs/BUYBOX_8020REI.md` §4, see below |
| Marketed **towns / cities** | **Yes — hard filter** | Sold CSV has `property_city` |
| NY state sales | Implicit in scrape | Scrape is NY-oriented; we do not add a second state gate |
| Nassau / Suffolk county only | **No** | Allowlist also includes Queens / Brooklyn / nearby cities we market (e.g. Astoria, Jamaica, Flushing, Brooklyn) — outside 8020REI's zip data entirely, so these only ever match via the town list |
| Property type SFH / 2–9 units | **No** | Sold CSV has **no** property-type column |
| REISift's own Buybox report (score, action-plan 30/60/90 days, recommended max list, total reach, client deals by county) | **No** | Lives entirely in REISift's own Buybox feature, a separate report. Not on `sold_properties_full.csv`, not exportable into Gate 7 without a new export |
| 8020REI's own Buybox "score" column (docs/BUYBOX_8020REI.md §4) | **No — not used at all** | Compound score across 9 weighted dimensions, not a geography fact; see "Zip matching" below |

**Rule:** Filter with **every sold-report field that maps cleanly to buybox**. Today that is **`property_zip`** and **`property_city`**, both normalized, both flat allowlists, either match is enough. Do not invent county-only or property-type filters that the sold file cannot support — that would silently drop marketed towns or pretend precision we do not have.

**Not buybox — do not conflate:** `investor_score` is on the sold CSV (98.8% filled, range 2–100) and is carried on every Gate 7 row/export, but it is unrelated to buybox. Traced to source (`D:\HHB\CleanREISift\scrape_sold_properties.py`): it is a raw pass-through of Dataflik's own per-**sale** field (`item.get("investor_score")`), used alongside address-tab matching to help classify whether a completed transaction was an investor purchase — a post-sale classification confidence about a third party's sale, not a property/owner fit score of ours. It happens to share a 0–100 scale with REISift's Buybox score, which is a coincidence, not a relationship. No buybox logic should reference it.

---

## How filtering works

1. CleanREISift may still scrape statewide `sold_properties_full.csv`.
2. Gate 7 `analyze()` reads each sold row and keeps it **only if** `in_buybox(property_city, property_zip)`.
3. Non-matching rows are **dropped at ingest** — they never become `InvestorSoldRow`s, never enrich, never enter Never prospected / Lost / pipeline.
4. Transparency only (not a KPI): `sold_rows_scanned`, `sold_rows_excluded_buybox`, `sold_rows_ingested`, `buybox_town_count` on the report header / Summary sheet / methodology note.

### Zip matching

Added 2026-09-23. Code: `backend/app/services/buybox_zips.py`. `BUYBOX_ZIPS` is a flat, hardcoded tuple of zip codes, the same idea as the town list below — no classification logic, no exclusion lists, no overrides. `in_buybox(city, zip_code)` returns `True` if *either* the zip is on `BUYBOX_ZIPS` *or* the city is on `BUYBOX_TOWNS` — a plain OR of two flat lists.

`BUYBOX_ZIPS` was built once, by hand, from `docs/BUYBOX_8020REI.md` §4 (a raw scrape of 8020REI's own product buybox tool for Nassau & Suffolk, zip → city list): a zip was added to the list if at least one of its listed cities was already on the town allowlist. That's it — no attempt to derive an *excluded*-zip signal, and 8020REI's own "Buybox score" column (a compound score across 9 weighted dimensions — property type, owner type, LTV, value, etc., §3 of the source doc) was not used for anything; it isn't a geography fact. This means the zip list is intentionally permissive: a zip qualifies if it contains a marketed town, even if the same 8020REI row also lists an unrelated non-marketed town sharing that zip. That imprecision is accepted in exchange for keeping the mechanism simple and auditable as two flat lists.

### City matching

- `normalize_town`: strip → strip trailing `,;.` → collapse whitespace → `casefold`.
- Membership = normalized city ∈ `BUYBOX_TOWNS` (210 distinct normalized keys from 212 label spellings).
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
| **Never prospected (investor)** | Investor sale in a marketed town, not HHB-closed, no 8020 / Court Alerts / LI Profiles Prospect list on or before that property's sold month end; pre-report history still counts | "Provider missed all of NY" |
| **Lost to investor** | We had presence (scrape In My Records **or** REISift/CRM) + investor + not closed | Failures outside marketed towns |
| **Pipeline depth / No list history** | Furthest stage among **buybox** sales | Statewide emptiness |
| **In Our List** segment | Scrape `in_my_records` among buybox sales | Same as "has Prospect tags" |

When presenting to stakeholders: always say **"among marketed-town sales"** (or cite buybox town count + excluded scrape rows from the header).

Headline Marketed → Closed cards are cumulative **“reached at least”** counts. Each card's percentage is divided by all buybox property × sold-month rows, so Closed is included in Opportunity and every earlier pipeline stage even when a separate lower-stage source file did not match.

---

## Confirmed against production data (2026-09-21)

**Stale after 2026-09-23:** the figures below predate the zip allowlist and town-allowlist reconciliation described in the next section. The zip list recovers some previously-excluded rows (unlisted city spellings like "Massapequa Pk", or any city sharing a zip with a marketed town) and the town-list cleanup removes a few others — the 24.1% in-buybox figure will shift and needs re-measurement against a current scrape before being quoted again.

Measured against the live `D:\HHB\CleanREISift\data\sold_properties_full.csv` (72,918 scanned rows, period Feb–Jul 2026):

- **17,561 of 72,918 rows (24.1%) are inside the buybox**; the other 75.9% are dropped at ingest — overwhelmingly non-marketed NY metros (top excluded cities: New York, Rochester, Buffalo, Staten Island, Bronx, Syracuse, Schenectady, Albany, Binghamton, Niagara Falls). This confirms the filter is doing its job: excluded volume is upstate/NYC-outer-borough, not marketed Long Island / Queens towns.
- **48 of the 214 buybox town labels had zero rows** in this particular 6-month window (e.g. Bayshore, Elwood, Mt Sinai, North Merrick, Patchog). That can be normal for a low-volume town in a short window — it is **not** on its own evidence of a scrape gap — but it's worth a periodic glance if a town goes quiet for several months running.
- **`in_my_records` is `TRUE` for 0 of 5,606 in-buybox rows across Mar/Apr/May/Jun/Jul 2026** — only Feb 2026 (414 rows) has any. This is the exact "Data caveat" already called out below and in SOP.md / REPORT_METHODOLOGY.md §21 — it is **still live**, not historical, as of this file. Root cause traced in `D:\HHB\CleanREISift\logs\sold_properties_full.log`: for each of those 5 months the scraper's **In My Records** tab query itself reports `total=0` straight from the API (`In My Records... reported total=0`), while the **Investor** tab query against the exact same month succeeds normally (2,800–3,100 matches every month) — so this isn't an auth/scraper failure, it's that specific REISift/Dataflik view returning nothing for anything before Feb 2026. Lost / had-presence KPIs for Mar–Jul 2026 are currently getting zero contribution from the scrape's own In My Records flag; whatever "we had it" signal exists for those months comes entirely from REISift/CRM presence (Tags, marketing, leads, QL, opps, contract, closed), not from this flag. Needs investigation on the REISift/Dataflik side (why does "In My Records" back-testing stop returning data before Feb 2026?), then a re-scrape, before treating those months' Lost numbers as complete.
- **This gap does not mean Gate 7 has no way to know whether we already had a sold property as a prospect.** Whether HHB *purchased* a property as a prospect (8020 / Court Alerts / LI Profiles list purchase) is tracked from a completely separate, independent source — the REISift export's own `Tags` (`List Purchased 8020 …`, `Probates NY …`, Court Alerts list tags) — not from the scrape's `in_my_records` flag at all. That source has its own row per property and its own list-purchase month, so it still says "we bought this one" for Mar–Jul 2026 sold properties even while `in_my_records` is blank for those months. This is exactly what powers `list_purchase_date` / `prospect_list_source` and the **Never prospected (investor)** primary KPI. It was severely under-matching before the REISift zip-column fix in `monthly_consolidated.py` (0.12% REISift match rate on the current file); after the fix it matches 21.6% of buybox rows.

## Buybox reconciliation against 8020REI (2026-09-23)

The user captured `docs/BUYBOX_8020REI.md` (a raw scrape of 8020REI's own product buybox tool for Nassau & Suffolk) as an independent ground truth to audit the town allowlist against, and to add a second flat zip allowlist (see "Zip matching" above). Findings and actions:

**Removed from `_BUYBOX_TOWN_LABELS`** (8 labels — confirmed suppressed/non-marketed, or a shared-zip risk):
- `East Marion`, `East Moriches`, `E Moriches`, `Eastport`, `Lloyd Harbor`, `Southold` — each corroborated by at least one of §13's three independent sources (DM-Sept, Tina, the "8020 zip list").
- `Westhampton Beach` — a spelling variant of suppressed "West Hampton Beach" (zip 11978).
- `Brookville` — not itself suppressed, but its zip-11545 neighbors "Old Brookville"/"Upper Brookville" are; removed out of caution given the shared-zip naming-collision risk.

**Added to `_BUYBOX_TOWN_LABELS`** (4 labels — nonzero 8020REI buybox score, not suppressed, previously missing): `Captree Island` (zip 11702), `Port Washington North` (11050), `Davis Park` (11772), `Oyster Bay Cove` (11791).

**Reviewed, no action taken:**
- `Latham` — an Albany-area town with zero connection to Nassau/Suffolk/Queens/Brooklyn, and absent from 8020REI's Nassau+Suffolk zip table entirely. Looks stale/erroneous, but left in place pending further investigation — flagged here as an open question.
- `James` — a weakly-sourced §13 entry (only one of three sources, no zip-list confirmation) whose own zip (11780) has a nonzero 8020REI score, contradicting the suppression claim. Not present in code today (only `Saint James`/`St James` are) so no removal was needed — noted here as a reviewed-and-dismissed false lead so it isn't re-flagged later.

**New capability**: a flat zip allowlist (`backend/app/services/buybox_zips.py`) — see "Zip matching" above for the mechanism.

## Salesforce Transaction Pipeline overlay (optional Gate 7 input)

Full clock/candidate rules: [REPORT_METHODOLOGY.md §21](REPORT_METHODOLOGY.md#21-gate-7-investor--in-list-sold). Two production-data limitations worth knowing when reading Gate 7 with this file attached:

- **No city column.** The real Transaction Pipeline export has `Address (Street)`, `Address (State/Province)`, `Address (ZIP/Postal Code)` but **no** `Address (City)` / `City` column at all (city only appears baked into a free-text `Transactions: Transaction Name` field, which is not parsed). Matching therefore falls back to **street + zip only** — measured at ~1% key-collision rate (5 of 526 rows) on a real sample. Low risk, not zero; an address matched this way could in principle belong to a same-named street in a different town sharing a zip.
- **Match window is bounded**, not open-ended: on/after the property's first Prospect-list month when known, else on/after `sold month − 24 months`, and always on/before the sold month end (`TXN_NO_LIST_LOOKBACK_MONTHS` in `investor_sold.py`). This stops an unrelated, much older Transaction Pipeline record at the same street address from being credited to a current external sale — real addresses resell over the years.

---

## Updating the buybox

1. Edit `_BUYBOX_TOWN_LABELS` in `backend/app/services/buybox_towns.py` (add scrape spellings you see in the wild).
2. To update zip-level geography, edit `backend/app/services/buybox_zips.py` directly (no scrape/regen script exists yet — it's hand-maintained from `docs/BUYBOX_8020REI.md`).
3. Add/adjust unit tests in `backend/tests/test_buybox_towns.py`.
4. Re-run `python backend/scripts/gen_buybox_doc.py` to refresh this appendix, or update it manually — **note:** this script's template is currently stale relative to this file's hand-added sections (Locked definition, Confirmed against production data, Salesforce Transaction Pipeline overlay, this reconciliation section); running it today would delete them, so update the appendix by hand until that's reconciled.
5. Update SOP / methodology one-liners only if the *meaning* of the universe changes.
6. Re-run Gate 7; confirm header excluded-count moves as expected.

Do **not** change the CleanREISift scraper to shrink geography unless product explicitly wants a smaller scrape — Closings owns the analysis universe.

---

## Appendix — allowlist cities (210 normalized)

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
- Calverton
- Cambria Heights
- Captree Island
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
- Davis Park
- Deer Park
- Dix Hills
- E Farmingdale
- E Northport
- East Elmhurst
- East Islip
- East Massapequa
- East Meadow
- East Northport
- East Patchogue
- East Rockaway
- East Setauket
- East Williston
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
- Oyster Bay Cove
- Ozone Park
- Patchog
- Patchogue
- Plainview
- Port Jefferson
- Port Jefferson Station
- Port Washington
- Port Washington North
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
- Wheatley Heights
- Woodside
- Wyandanch
- Yaphank

---

## Related

- [SOP.md](SOP.md) — Gate 7 operator summary
- [REPORT_METHODOLOGY.md](REPORT_METHODOLOGY.md) §21 — Gate 7 methodology
- [ECOSYSTEM.md](ECOSYSTEM.md) — CleanREISift sold CSV → Closings
