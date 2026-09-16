# Contact Attribution Report — Methodology

This document describes **how closings / contact attribution reports are computed** in this application: inputs, tag parsing, matching, counting rules, lifecycle, and exports. For operator workflows (REISift import order, Docker ports, API), see [RUNBOOK.md](../RUNBOOK.md).

**Canonical implementation:** `backend/app/services/analysis.py`, `backend/app/services/lifecycle.py`, `backend/app/services/marketing_mapper.py`.

**Salesforce Create Date (all gates):** Create Date is when marketing called or texted that LIP / 8020 / CourtAlerts list and pushed the lead into the CRM. It is a **clock**, not a source. The list provider is the credit (first list on the row wins). Campaign / Lead Source is how they worked it — extra, not a replacement for the list. Never compare Create Date to list month to relabel credit as “Already in Salesforce,” “After LIP,” or “After 8020.”

Allowed clock uses: Gate 1 does not credit from Create Date. Gate 2 / legacy QL — Create Date **window** = which QLs fall in the month. Gate 3 — same window, plus `days_list_to_create_date` **lag**. Gate 4 — Create Date is the web-lead / CourtAlerts cohort **anchor**; prior list tags are history, not a rewrite of that credit. Gate 5 — lag from first-list month to CRM push. Gate 6 — Prospect lag from first list month to QL Create Date (on or before external sold month). Gate 7 — same lag rules as Gate 5 (Court Alerts vs 8020 first list → Create Date).

---

## 1. Purpose and data flow

The report answers: **For each closed deal, what marketing touches happened before close, through which channels, and what lifecycle stages were reached?**

```mermaid
flowchart LR
  subgraph ingest [Marketing ingest optional]
    Cold[Cold SMS CRM closings]
    Mapper[marketing_mapper]
    Zip[Four REISift CSVs]
    Cold --> Mapper --> Zip
  end
  Zip --> REISift[REISift import]
  REISift --> Export[Contact export CSV with Tags]
  Export --> Analyze[perform_analysis]
  Analyze --> Deals[Closed deals list]
  Analyze --> Match[Match to CSV rows]
  Match --> Report[Per-deal KPIs + lifecycle]
  Report --> Out[UI Excel CSV JSON]
```

**Important:** Analysis reads the **REISift export CSV** (especially the **`Tags`** column). It does **not** read the Past patches zip directly. Tags from bulk import must appear on the export row after REISift processing.

---

## 2. Analysis modes

| Mode | Closed deals source | Match strategy |
|------|---------------------|----------------|
| **CSV-only (default)** | Derived from each row’s **`Tags`** (`derive_closed_deals_from_csv`) | Same row via **`csv_index`** — no fuzzy address match |
| **Legacy workbook** | Rows from uploaded closings **Excel** | **`match_deals_to_csv`** — normalized address + city (+ fallbacks) |

Optional API parameter **`as_of`** (`YYYY-MM-DD`): keep only deals with **`Date Closed` ≤ as_of** (calendar day). Supported on `POST /api/analyze`; not exposed in the current UI.

---

## 3. Minimum contact-history CSV

| Column | Required | Role |
|--------|----------|------|
| **`Tags`** | Yes | Comma-separated history: 8020 contacts, list/skip, `(SF)` CRM, `(CLOSED)` markers |
| **`Property address`** + **`Property city`** | Effectively yes | Combined into display/match address; if street empty, falls back to **`Address`** |
| **`Lead Source`** (variants) | No | Defaults to `"Contact History Tags"` when deriving deals |

**Row model:** One export row = one property’s full tag blob. Do not split history across rows.

See [RUNBOOK.md — Minimum Contact History CSV](../RUNBOOK.md#minimum-contact-history-csv-for-analysis) for safe trimming rules.

---

## 4. Tag parsing (`parse_tags`)

The **`Tags`** string is split on commas. Each token is matched against known patterns. Unrecognized tokens are ignored.

### 4.1 Recognized patterns

| Tag pattern | Parsed `type` | Date precision | Counted in CC/SMS/DM? |
|-------------|---------------|----------------|------------------------|
| `(8020) CC - MM/YYYY` or `MM-YYYY` | `contact` (channel CC) | Month → 1st of month | Yes, if before close |
| `(8020) SMS - …` | `contact` (SMS) | Month | Yes, if before close |
| `(8020) DM - …` | `contact` (DM) | Month | Yes, if before close |
| `List Purchased 8020 MM/YYYY` | `list_purchase` | Month | No |
| `Skip Traced … MM/YYYY` (optional Versium) | `skip_trace` | Month | No |
| `(CLOSED) 8020 - MM/YYYY` | `closing` | Month | No |
| `(SF) UPDATED - {status} - YYYY-MM-DD` | `sf_updated` | Day | No |
| `(SF) STATUS - {status} - YYYY-MM-DD` | `sf_status` | Day | No |

Implementation: `parse_tags` in `backend/app/services/analysis.py`.

### 4.2 Duplicate tag deduplication

After parsing, **`_dedupe_parsed_tag_events`** collapses tokens that describe the **same logical event**:

- **Dedupe key:** `(type, date, channel, label)`
- **Typical case:** Same tag imported twice to REISift (e.g. duplicate `(8020) CC - 1/2025`) → **one** event for counts and lifecycle.

This applies to **all** parsed types including `(CLOSED)` and `(SF)` lines.

Tests: `backend/tests/test_parse_tags_dedupe.py`.

### 4.3 What deduplication does *not* do

- **Different months** for the same channel (e.g. CC in Jan and CC in Feb) → **two** contacts.
- **Two CSV rows** for the same physical property → **two deals** in the report (no cross-row dedupe).
- **Path display:** `compute_ordered_path` only merges **consecutive identical** path tokens (e.g. `CC -> CC` becomes one `CC`), not all repeated CC events separated by other channels.

---

## 5. Deriving closed deals (CSV-only)

For each CSV row with non-empty **`Tags`**:

1. Parse and dedupe tags.
2. **Contract vs closed (default):**
   - **`Date Under Contract`** = earliest **`sf_updated` / `sf_status`** whose normalized label is in **`CONVERTED_LABELS`** (`converted`, `under contract`, … — Salesforce “converted” means under contract, not settlement closed).
   - **`Date Closed`** = earliest among **`closing`** events (`(CLOSED) 8020 - …`) only. SF converted/under contract **does not** qualify a row as closed.
3. If no **`closing`** event → row is not a closed deal (unless legacy mode; see below).
4. Row must have a non-empty combined address after address fallback logic.
5. Apply **`as_of`** cutoff if provided (compared to **`Date Closed`**).

**Workbook + tags:** When a legacy closings workbook is uploaded, **`Date Closed`** = **earliest** of workbook **`Date Closed`** and any **`(CLOSED)`** tag on the matched CSV row.

**Legacy mode:** Set environment variable **`USE_LEGACY_MIN_CLOSE_DATE=1`** to restore the old rule where SF converted dates could define **`Date Closed`** via `min(SF converted, CLOSED)`.

**Closings workbook Stage filter:** Rows with **`Stage`** are kept only when the stage is a closing type (**Closed**, **Executed**, **Funded**, **Closed Won**, etc.). **Closed Lost** and pipeline stages (Follow-up, etc.) are excluded. If no **`Stage`** column exists, all rows with a parseable close date are kept.

Month-granular **`(CLOSED)`** tags use the first day of that month internally for comparison.

---

## 6. Matching deals to contact rows

### 6.1 CSV-only path

Derived deals carry **`csv_index`**. Matching attaches the **same row’s** `Tags` for analysis — no address fuzzy match.

### 6.2 Legacy workbook path

`match_deals_to_csv` normalizes addresses (lowercase, abbreviation standardization, punctuation stripped) and tries, in order:

1. Exact normalized street + city  
2. City disambiguation when multiple CSV rows share a street  
3. Partial street match  
4. Street number + city  

Unmatched deals appear in results with **Match Found = false** and zero contact counts.

---

## 7. Per-deal metrics (`analyze_contacts`)

For each matched deal:

| Metric | Definition |
|--------|------------|
| **CC / SMS / DM Count** | Parsed **`contact`** events with date **strictly before** `Date Closed` |
| **Total Contacts** | Sum of CC + SMS + DM (not list/skip/SF/CLOSED) |
| **First / Last Contact Date** | Min/max among pre-close contact events |
| **Days to Close** | Close date minus first contact (approximate when tags are month-only) |
| **Contact Timeline** | Ordered channel list before close |
| **Closed Marker Date** | First **`closing`** event before close, if any |
| **List Purchased / Skip Traced Date** | First list/skip before close |

Lifecycle fields (funnel, path, SF trail, lifecycle events JSON) are computed from the same parsed events — see §8.

---

## 8. Lead lifecycle

Events are built with **`build_events`**, sorted by datetime then type rank (SF day events before month-granularity tags on the same day).

**Before-close rule:** Funnel, path, SF trail, and exported **Lifecycle Events** use only events with date **strictly before** the deal’s **`Date Closed`**.

### 8.1 Funnel stages

| Stage | Signal (first before close) |
|-------|----------------------------|
| **ACQUIRED** | `List Purchased 8020 …` |
| **RESEARCHED** | `Skip Traced …` |
| **FIRST_CONTACTED** | First `(8020) CC|SMS|DM …` |
| **ENGAGED** | `(SF) …` with label in **ENGAGED_LABELS** |
| **CONVERTED** | `(SF) …` with label in **CONVERTED_LABELS** |
| **CLOSED** | Always true for analyzed deals; date = deal close |

**Highest stage** ranks ACQUIRED → … → CONVERTED only; **CLOSED** is excluded from “highest” because every analyzed deal is closed.

### 8.2 Path sequence

Human-readable token chain (e.g. `LIST -> SKIP -> CC -> SF:follow_up -> CLOSED`). Consecutive duplicate tokens are collapsed once.

### 8.3 SF status trail

Chronological list of `(SF) UPDATED` / `(SF) STATUS` events before close (label + date + kind). Duplicate identical SF events are removed at parse dedupe step.

---

## 9. Summary / aggregate statistics

- **Match rate:** Share of closed deals with a matched CSV row.
- **Channel totals:** Sum of CC/SMS/DM counts **across deals** (each deal counted once per its row).
- **Lifecycle aggregates:** Per-stage reach rates over matched deals (`aggregate_lifecycle_stats`).

---

## 10. Past patches → REISift → analysis

**Past patches** (`marketing_mapper.run_patch_pipeline`) produces four CSVs:

| File | Purpose |
|------|---------|
| `property_status_updates.csv` | Property-level REISift status |
| `phone_status_tags_updates.csv` | Phone status + tags |
| `salesforce_status_tags.csv` | Rows that become **`(SF) UPDATED` / `(SF) STATUS`** tags in REISift |
| `closings_status_tags.csv` | **`(CLOSED) 8020 - M/YYYY`** month markers |

After REISift import and re-export, those strings live in **`Tags`** and feed §4–§8.

**CRM caveat:** `updated_on` must match the mapper’s Salesforce-style parser or UPDATED rows may be skipped (check preview metrics).

---

## 11. One-time Podio / offline ingest scripts

Not part of the web UI; for historical backfills:

| Script | Role |
|--------|------|
| `scripts/one_time_samples_reisift_zip.py` | Sample `Data_ingestion_samples` → REISift zip (Podio Closings adapted) |
| `scripts/one_time_podio_closings_opps_tags_bundle.py` | Podio Closings + Tina **New Opportunities** (Closed/Executed) merged closings tags + sidecar |
| `scripts/new_ingest_validate_and_bundle.py` | Validates slim `Report-*.xlsx` vs full address exports |
| `scripts/probe_contact_cadence_from_csv.py` | Offline gap stats between parsed events (experimental) |

Outputs land under `_ingest_out/<timestamp>/` with `ingest_metrics.json` and `README.txt`.

---

## 12. Experimental: cadence from history

**Module:** `backend/app/services/cadence_from_history.py`

Uses the same **`parse_tags`** + **`build_events`** pipeline to compute **inter-event day gaps** for offline experiments (e.g. informing future “Golden Loop” wait periods). **Not** used in production UI reports.

- **`summarize_tag_cadence(tags)`** — full timeline gaps  
- **`summarize_cadence_before_close(tags, closed_date)`** — gaps before close only  

**Limitation:** `(8020)` tags are **month-granular**; gaps are coarse unless `(SF)` day tags are present.

---

## 13. Exports

| Format | Contents |
|--------|----------|
| **Excel** | Results sheet + **Lifecycle Events** (one row per pre-close parsed event when available) |
| **CSV / JSON** | Flat result rows including lifecycle columns when run on current code |

Saved JSON from older runs may omit lifecycle fields; re-run analysis to populate.

---

## 14. Related documents

- [RUNBOOK.md](../RUNBOOK.md) — operations, playbooks, API, tag cheat sheet  
- [README.md](../README.md) — app overview and local/Docker setup  
- In-app **How the analysis works** — summary for analysts in the UI  

---

## 15. Code index

| Topic | Location |
|-------|----------|
| Tag parse + dedupe | `backend/app/services/analysis.py` — `parse_tags`, `_dedupe_parsed_tag_events` |
| Derive closings | `analysis.py` — `derive_closed_deals_from_csv` |
| Close vs contract rules | `closing_resolution.py` — `resolve_milestones_from_parsed`, `filter_closings_by_stage` |
| Workbook match | `analysis.py` — `match_deals_to_csv` |
| Contact KPIs | `analysis.py` — `analyze_contacts`, `perform_analysis` |
| Lifecycle | `backend/app/services/lifecycle.py` |
| REISift CSV export | `backend/app/services/marketing_mapper.py` — `export_outputs` |
| Cadence probes | `backend/app/services/cadence_from_history.py` |
| Dedupe tests | `backend/tests/test_parse_tags_dedupe.py` |
| Monthly consolidated (Gate 2) | `backend/app/services/monthly_consolidated.py` |
| Marketing ramp (Gate 3) | `backend/app/services/marketing_ramp.py` |
| Web leads (Gate 4) | `backend/app/services/web_leads.py` |
| Gate 5 probate | `backend/app/services/probate.py` |
| Open pipeline / stuck-at-stage | `lifecycle.py` — `compute_stage_funnel_open`, `aggregate_stuck_at_stage` |
| Tag-derived lead source | `monthly_consolidated.py` — `derive_tag_lead_source` |
| Sold properties (Gate 6) | `backend/app/services/sold_properties.py` |
| Court Alerts (Gate 7) | `backend/app/services/court_alerts.py` |
| Investor & In-List Sold (Gate 8) | `backend/app/services/investor_sold.py` |

---

## 16. Gate 2 consolidated report additions

**Create Date:** QL **window** only (which qualified leads fall in the month / full-file span). List tags and first list remain the source credit. Create Date is not a competing source.

**Tag-derived lead source:** For each REISift cohort row, parse `Tags` chronologically. First `(8020) CC/SMS/DM` contact wins; if none, `LIST` when a `List Purchased 8020` tag exists; otherwise `NONE`. This is separate from Salesforce `Lead Source` on the qualified-leads export.

**Open pipeline (non-closing rows):** Cohort rows without `(CLOSED) 8020` tags are evaluated with the same lifecycle stage model, using events on or before the row `Created` date (or cohort period end). Highest stage reached is aggregated into **stuck-at-stage** counts (e.g. ENGAGED but not CONVERTED). `PodioSellerLeads` (exact token) counts as ENGAGED presence (pre-Salesforce CRM lead). Closing-cohort lifecycle and Top Paths remain closing-only.

**List combinations:** Only **stackable distress lists** participate (excludes source/import and hygiene lists: 8020 Source List, PODIO, Appraiva, DNC, Dead Deals, Closings App, MLSLI, TBD, Buyers (Investorbase), etc.). A combination requires **≥2** stackable lists on the same row. Minimum row count = **median** of multi-list combo sizes in the cohort (floor 5). Results are grouped under the combo's **primary list** (highest closings within that stack).

---

## 17. Gate 3 marketing ramp (unified monthly report)

**Create Date:** Window for which QLs are in the population, and `days_list_to_create_date` **lag** from list to CRM push. List provider is still the credit. Do not treat Create Date as a source.

**Population:** Union of qualified leads (Create Date in window) and closings (Date Closed in window, Closed Lost excluded), deduplicated by normalized address. Closing-only rows use **No Clear Source** for Salesforce channel attribution.

**REISift enrichment:** Full export indexed by address; `has_reisift_match` false when no row matches.

**Total touch counts:** Summary metric `total_touch_counts` sums every `(8020) CC`, `(8020) SMS`, and `(8020) DM` tag on each population row's matched REISift tags. This is distinct from `touch_counts`, which counts population rows by **first-touch** channel only.

**Parallel consolidated report:** Gate 3 analyze also runs Gate 2 (`monthly_consolidated.analyze`) on the same REISift + QL files. Consolidated cohort remains the **full REISift export** (not filtered to the ramp date window). Results are embedded in the Gate 3 API response and persisted with the marketing ramp report.

**Export:** Unified XLSX reuses Gate 2 workbook sheets and appends a **Marketing Ramp** sheet with per-address journey columns.

---

## 18. Gate 4 web leads / CourtAlerts

**Create Date:** Cohort **anchor** (when that web or CourtAlerts lead was pushed into Salesforce). Prior LIP / 8020 / other list tags on the REISift row are **history**, not a rewrite of web-lead credit. Create Date is not compared to list month to steal or reassign source.

Canonical implementation: `backend/app/services/web_leads.py`.

---

## 19. Gate 5 probate lifecycle

**Question:** On Long Island Profiles (probate) properties, who delivered the record first (LIP vs 8020), how many months until Salesforce Prospect, what % of the LIP list became Prospects, and what Primary/Secondary Reason for Selling is stated on the Transactions pipeline.

**Universe:** REISift rows with at least one of the **38 locked** tags `Probates NY (Nassau|Queens|Suffolk) M-YYYY` (hyphen, optional leading zero). Nassau starts Apr 2025 (not Feb/Mar 2025). Queens starts Feb 2026. **Nassau 3-2026** and **Queens 3-2026** stay in the locked set even when those drops have no rows. Other gaps are real. 8020-only rows are excluded. First LIP month = earliest **locked** tag on the row. County is taken from that tag.

**8020 list purchase:** `List Purchased 8020 MM/YYYY`, or `List Purchased MM/YYYY` when a standalone `(8020)` token is on the same row. `(8020) CC|SMS|DM` contact tags are not list-purchase dates.

**First source** (month granularity): LIP Probates only, LIP Probates first, 8020 first, same month. **That first list is the QL credit** when the row matches a Qualified Lead **on or after** the first-list month.

**Prospect:** Salesforce Total Qualified Leads row matched by street+city+state+zip, then street+city+zip / street+zip, then phone. Among matches, take the **earliest Create Date on or after the first-list month**. A QL whose only Create Date is earlier is **not** a conversion from this list (diagnostic: In CRM before first list). **Campaign** is how they worked a counted Prospect. Opportunities are a later funnel count. Reasons are **not** read from QL or Opportunities.

**Lag:** calendar months from the **first-list month** to that Prospect Create Date. Counted Prospects have lag ≥ 0. Lag buckets are split by first-list source: LIP Probates (LIP only + LIP first), 8020 first, and Same month.

**Reason to sell:** Transactions pipeline **Primary Reason for Selling** and **Secondary Reason for Selling** after address match. Blank is a bucket. Unmatched transactions have no reason.

Canonical implementation: `backend/app/services/probate.py`.

---

## 20. Gate 6 sold properties (pipeline depth before external sale)

**Question:** Among properties already in REISift that later appear in a sold-properties file (`in_sold_properties_full` sale month), how hard did we market them, and how far did they get in the HHB funnel before that external sale?

**Inputs:** REISift export with `in_sold_properties_full` (required) + Salesforce Total Qualified Leads (required) + Opportunities (optional).

**Cohort:** Rows with a non-empty, parseable `in_sold_properties_full` value (aliases: `Sold Month`, `in_sold_properties`). Accepted month forms: `M/YYYY`, `MM/YYYY`, `YYYY-MM`, month names. Unparseable non-empty values are excluded and counted in warnings.

**External sale anchor:** Sold month is **not** an HHB closing. Events and CRM matches are evaluated **on or before the end of the sold month**.

**Pipeline stages (highest reached):** On list → Marketed (`(8020)` CC/SMS/DM) → Prospect (QL match on/after first list month, SF engaged status tag, or REISift `PodioSellerLeads` presence — pre-Salesforce CRM lead tag, not a Create Date clock) → Opportunity (optional Opportunities file, same ingest as Gate 5) → Under contract (SF converted) → Closed with HHB (`(CLOSED) 8020`). Why they sold elsewhere is out of scope.

**Create Date:** Prospect **lag** only (`months_list_to_prospect`). List purchase tags remain source credit.

**Export:** Summary, Journey, Never Marketed, Pipeline Funnel, By Sold Month, Lifecycle Funnel sheets.

**Never marketed:** No `(8020) CC/SMS/DM` tags on/before sold month. Often federal Do Not Call, other DNC, or suppression imports (property bought into REISift but intentionally not reached). Spot-check Tags/Lists for DNC or suppression labels.

Canonical implementation: `backend/app/services/sold_properties.py`.

---

## 21. Gate 7 Court Alerts lifecycle

**Question:** On Court Alerts (foreclosure / court) properties, who delivered the record first (Court Alerts vs 8020), how many months until Salesforce Prospect, what % of the Court Alerts list became Prospects, and what Primary/Secondary Reason for Selling is stated on the Transactions pipeline.

**Universe:** Rows from the Court Alerts CSV/XLSX (pgweb export) with a parseable **address** and **created_on**. List month = first of the month of `created_on`. County comes from `county_name` (optional “County” suffix stripped). This file **is** the universe — not a REISift tag filter.

**REISift join:** Full export indexed by address; Tags are merged when multiple REISift rows share an address. Used for 8020 list-purchase dates and phones. Unmatched Court Alerts rows still count (Court Alerts only).

**8020 list purchase:** Same as Gate 5 — `List Purchased 8020 MM/YYYY`, or `List Purchased MM/YYYY` when a standalone `(8020)` token is on the same row.

**First source** (month granularity): Court Alerts only, Court Alerts first, 8020 first, same month. **That first list is the QL credit** when the row matches a Qualified Lead **on or after** the first-list month.

**Prospect / lag / reasons:** Same rules as Gate 5 probate (Create Date on or after first-list month; lag buckets split by Court Alerts / 8020 / Same month; reasons from Transactions only).

**Export:** Summary, Court Alerts Rows, First Source, Campaign, County, List Month, Lag Buckets, CRM Before First List, Txn reason sheets.

Canonical implementation: `backend/app/services/court_alerts.py`.

## 22. Gate 8 Investor & In-List Sold

**Question:** Of scraped external NY sales (`sold_properties_full.csv`), how many are investor buyers, already in our REISift records (`in_my_records`), both, or neither — and (optionally) how far in-list matches got in the HHB funnel.

**Universe:** CleanREISift sold scrape rows with `investor` and `in_my_records` TRUE/FALSE flags. Address keys rebuilt with `make_address_key` from property address parts (do not trust the scrape `address_key` string for joins).

**Segments:** Investor (`investor`), In Our List (`in_my_records`), Both, Neither. Rollups by sold month (`period_date` / `period_label`) and county.

**Optional enrichment:** REISift + QL (+ Opps) joined by address — marketing touches and pipeline depth on or before the sold month (same clocks as Gate 6).

**Export:** Summary, By Month, By County, Investor, In Our List, Both, All Rows.

Canonical implementation: `backend/app/services/investor_sold.py`.

