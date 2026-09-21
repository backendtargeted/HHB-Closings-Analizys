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
| **1** | Monthly ingestion (Past patches) | Cold CSV, SMS CSVs, CRM, closings XLSX | REISift import bundle | `marketing_mapper.py` |
| **2** | Consolidated list report | REISift export + Total QL | List / combo / channel / journey | `monthly_consolidated.py` |
| **3** | Marketing ramp | REISift + QL (+ window) | Population touches + lag + embedded Gate 2 | `marketing_ramp.py` |
| **4** | Web leads | REISift filtered to web / CourtAlerts cohort + QL | Web-lead credit vs prior list history | `web_leads.py` |
| **5** | Probate lifecycle | REISift (Probates NY tags) + QL (+ Opps / Txns) | LIP vs 8020 first list → QL lag / reasons | `probate.py` |
| **6** | Court Alerts lifecycle | Court Alerts CSV + REISift + QL (+ Opps / Txns) | CA vs 8020 first list → QL lag / reasons | `court_alerts.py` |
| **7** | Investor & In-List Sold | CleanREISift `sold_properties_full.csv` (buybox cities) + REISift + QL (+ Opps) | Never prospected (investor) + Lost + pipeline depth | `investor_sold.py` |

API path prefixes stay `/api/court-alerts`, `/api/investor-sold`, etc. (display gate numbers only).

Legacy **Regular attribution** (contact-history CSV → closings lifecycle) remains available; see RUNBOOK.

---

## Gate 7 — Never prospected (investor) + Lost

**Universe:** marketed-town buybox only (`backend/app/services/buybox_towns.py`). Sold scrape rows outside those cities are dropped at ingest; KPIs never see them.

**Primary KPI — Never prospected (investor)** = investor sale **and** not HHB-closed **and** no Prospect list from 8020 / Court Alerts / LI Profiles. Denominator = investor sales. Coverage / data-quality check (not a second loss gate).

**Lost** (unchanged) = we had it **and** investor bought it **and** we did not HHB-close it.

**We had it** = scrape `in_my_records` **or** REISift/CRM presence (list tags, marketed, Podio/SF lead, QL, opp, UC, Closed).

**Loss %** = lost ÷ properties we had (not “In Our List” as a peer KPI).

**Grain:** unique property × sold month (`dataflik_id` + month).

**Data caveat:** CleanREISift In My Records scrape must return non-zero totals for every sold month before trusting Lost KPIs. Produce CSV via `D:\HHB\CleanREISift` (`scrape_sold_properties.py` / enrich). See [ECOSYSTEM.md](ECOSYSTEM.md).

---

## Monthly cadence (checklist)

1. **Gather** cold / SMS / CRM (and closings if backfilling).
2. **Gate 1** — generate REISift import bundle → import into REISift → spot-check.
3. **Export** contacts with `Tags`, `Lists`, `Created`, address columns.
4. **Export** Salesforce Total Qualified Leads (and Opps / Transactions if needed).
5. Run **Gate 2** (and/or **Gate 3**) for list + channel performance.
6. Run **Gate 5** / **Gate 6** when answering probate or Court Alerts first-list questions.
7. **CleanREISift** — refresh `sold_properties_full.csv` (verify In My Records totals) → **Gate 7**.
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
