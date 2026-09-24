# HHB Closings Analysis — SOP

Single entry point for operators and agents. Deep ops/API detail stays in [RUNBOOK.md](../RUNBOOK.md); counting rules stay in [REPORT_METHODOLOGY.md](REPORT_METHODOLOGY.md). Ecosystem map: [ECOSYSTEM.md](ECOSYSTEM.md).

---

## Purpose

This app answers marketing and list questions from **REISift Tags/Lists** (+ Salesforce QL / optional Opps / CleanREISift sold CSV). It does **not** replace REISift. Closings is the **source of truth for analysis grammar** (tag parse, pipeline stages, Create Date = clock).

---

## Canonical marketing pipeline

```text
Prospect (8020 / Court Alerts / LI Profiles)
  → Marketed (CC / DM / SMS)
  → Lead (Salesforce / Podio)
  → Qualified Lead
  → Opportunity (includes under contract)
  → Closed
```

Constant: `CANONICAL_PIPELINE` in `backend/app/services/sold_properties.py`.

### Prospect sources (same `parse_tags` list_purchase events)

| Source | Tag / signal |
|--------|----------------|
| **8020** | `List Purchased 8020 MM/YYYY` |
| **Court Alerts** | `List Purchased Court Alerts …` / Court Alerts dated tags; or Lists name |
| **LI Profiles** | `Probates NY Nassau\|Queens\|Suffolk M-YYYY`; or Lists (LI Profiles / Probate) |

These same tags feed closings-attribution lifecycle **ACQUIRED** (`lifecycle.py`).

### Locked rules

- **Create Date** (Salesforce QL) is a **clock**, not list credit. First Prospect list owns source credit.
- **Under contract** is **Opportunity**, not its own stage.
- **Do not revive** the old REISift `in_sold_properties_full` Sold Properties product gate (removed). One sold truth: Gate 7.

---

## Gates (when to run what)

| Gate | UI name | Primary inputs | Answers | Code |
|------|---------|----------------|---------|------|
| **1** | Monthly ingestion | Selected month + calling/SMS CSVs or three Salesforce reports | Reviewed REISift import bundle | `monthly_ingestion.py`; [monthly guide](GATE1_MONTHLY_INGESTION.md) |
| **2** | Consolidated list report | REISift export + Total QL | List / combo / channel / journey | `monthly_consolidated.py` |
| **3** | Marketing ramp | REISift + QL (+ window) | Population touches + lag + embedded Gate 2 | `marketing_ramp.py` |
| **4** | Web leads | REISift filtered to web / CourtAlerts cohort + QL | Web-lead credit vs prior list history | `web_leads.py` |
| **5** | Probate lifecycle | REISift (Probates NY tags) + QL (+ Opps / Txns) | LIP vs 8020 first list → QL lag / reasons | `probate.py` |
| **6** | Court Alerts lifecycle | Court Alerts CSV + REISift + QL (+ Opps / Txns) | CA vs 8020 first list → QL lag / reasons | `court_alerts.py` |
| **7** | Investor & In-List Sold | CleanREISift `sold_properties_full.csv` (NY Nassau/Suffolk, ZIP/city exclusions) + REISift + QL (+ Opps) | Never prospected (investor) + Lost + pipeline depth | `investor_sold.py` |

API path prefixes stay `/api/court-alerts`, `/api/investor-sold`, etc. (display gate numbers only).

Legacy **Regular attribution** (contact-history CSV → closings lifecycle) remains available; see RUNBOOK.

---

## Gate 7 — Never prospected (investor) + Lost

**Universe (buybox):** NY Nassau/Suffolk only, with 72 excluded ZIPs and 84 excluded city keys consolidated from all three suppression sources in `buybox_policy.json`. Full contract: [BUYBOX.md](BUYBOX.md). A present ZIP decides membership; city fallback applies only when ZIP is missing. Malformed nonblank ZIP, missing state/county, and missing fallback city are excluded. Filtering occurs **at ingest before enrichment and KPIs**. Scores do not affect geography. With property details, validated APN/county matches are screened for supported physical-property criteria before enrichment; excluded and unresolved properties remain in a separate audit. Without details this is geography-only. LTV, ownership duration and non-seller/religious-owner exclusion remain unevaluated.

**Inputs:** Recommended ZIP bundle with the canonical names documented in [BUYBOX.md](BUYBOX.md#upload-bundle), including `sold_property_details.jsonl`. Individual uploads remain available: Sold CSV + REISift + QL (required), property details optional. Opportunities optional. **Salesforce Transaction Pipeline** optional (Closed Date → Closed; Date Contract Signed / accepted offer → Opportunity).

**Headline pipeline cards + depth table:** cumulative “reached at least” (Prospect ≥ Marketed ≥ …), with every percentage divided by eligible unique properties. **Lost by furthest stage** stays exclusive. Marketing touches imply Prospect on the ladder.

**Primary KPI — Never prospected (investor)** = investor sale **and** not HHB-closed **and** no Prospect list from 8020 / Court Alerts / LI Profiles **on or before that property's anchored sold month end**. Prospect history before the report's first sold month still receives credit; later list events do not. Denominator = investor properties **inside buybox**. Qualify findings as “among eligible Nassau/Suffolk properties.”

**Lost** (unchanged) = we had it **and** investor bought it **and** we did not HHB-close it (also buybox-scoped).

**We had it** = scrape `in_my_records` **or** REISift/CRM presence (list tags, marketed, Podio/SF lead, QL, opp, UC, Closed).

**Loss %** = lost ÷ properties we had (not “In Our List” as a peer KPI).

**Grain:** one property across the report, anchored to its earliest observed sold month. Count all distinct transaction IDs, but do not import later-month flags or buyers into that earlier snapshot. Display distinct buyers within the earliest month together; no precise within-month sale order is assumed.

**Data caveat:** CleanREISift In My Records scrape must return non-zero totals for every sold month before trusting Lost KPIs. Confirmed still `0` for Mar–Jul 2026 as of 2026-09-21 (root cause: the scraper's "In My Records" tab query itself returns `total=0` from the API for those months — not an auth/scraper bug, see BUYBOX.md). This does **not** blind Gate 7 to prospect-list purchases in that window — whether we bought a property as a Prospect (8020 / Court Alerts / LI Profiles) comes from REISift `Tags`, a separate source from `in_my_records`. Produce CSV via `D:\HHB\CleanREISift` (`scrape_sold_properties.py` / enrich). See [ECOSYSTEM.md](ECOSYSTEM.md).

---

## Monthly cadence (checklist)

1. **Gather** cold / SMS / CRM (and closings if backfilling).
2. **Gate 1** — generate REISift import bundle → import into REISift → spot-check.
3. **Export** contacts with `Tags`, `Lists`, `Created`, address columns.
4. **Export** Salesforce Total Qualified Leads (and Opps / Transaction Pipeline if needed for Gate 5–7).
5. Run **Gate 2** (and/or **Gate 3**) for list + channel performance.
6. Run **Gate 5** / **Gate 6** when answering probate or Court Alerts first-list questions.
7. **CleanREISift** — refresh `sold_properties_full.csv` (verify In My Records totals) → **Gate 7** (NY Nassau/Suffolk with ZIP-first exclusions — [BUYBOX.md](BUYBOX.md)).
8. **Archive** XLSX / share links; saved reports live under `{REPORTS_DIR}/…`.

Docker UI default: `http://localhost:3300`.

---

## Closings attribution lifecycle (Gates 1–3 depth)

Separate ladder for **closed-deal** tag history (not Gate 7 furthest stage):

`ACQUIRED (Prospect list) → RESEARCHED → FIRST_CONTACTED → ENGAGED → CONVERTED → CLOSED`

ACQUIRED uses the same Prospect list tag families as above. Converted ≈ under contract / contract signed; settlement Closed is separate.

---

## Where to read next

| Doc | Use for |
|-----|---------|
| [ECOSYSTEM.md](ECOSYSTEM.md) | Closings ↔ CleanREISift ↔ hhb-data-sidecar |
| [RUNBOOK.md](../RUNBOOK.md) | Operator steps, API, uploads, tag cheat sheet |
| [REPORT_METHODOLOGY.md](REPORT_METHODOLOGY.md) | Parse / match / count / clock rules |
| [README-DEV.md](../README-DEV.md) | Local / Docker dev |
| [README.md](../README.md) | App overview |
