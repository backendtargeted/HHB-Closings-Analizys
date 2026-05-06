# HHB Closings + Marketing — Operations Runbook

End-to-end process: normalize marketing data → **REISift** → export contacts → **Contact Attribution Analysis** (this repo). Includes **backdated** closings, historical CRM tags, and (API-only) **period snapshots** (`as_of`).

---

## Stack overview

```text
marketing_ingestion_mapper.py  →  REISift import CSVs  →  REISift (system of record)
                                                              ↓
                                                    Contacts export (CSV + Tags)
                                                              ↓
HHB web app / API: Closed deals Excel + contacts CSV  →  reports + exports
```

- **Mapper (standalone GUI):** `Python_Tools/7_Utilities/marketing_ingestion_mapper.py` — same logic as the in-app generator below (keep in sync until consolidated).
- **Mapper (this repo):** `backend/app/services/marketing_mapper.py` — used by **Past patches** in the web UI: cold-calling CSV, many SMS CSVs, CRM extract, closings `.xlsx` → the four REISift-shaped CSVs.
- **REISift**: holds property/phone + **Tags** (comma-separated history).
- **This app**: matches closings Excel to CSV by address/city; parses **Tags** for 8020 contact lines, list purchase, skip trace, and **closing** markers (see cheat sheet).

---

## Standard monthly process

1. **Gather inputs**
   - Cold-calling export (required columns: `Phone`, `Address`, `City`, `State`, `Zip Code`, `Log Type`).
   - SMS bucket: folder of CSVs (status often encoded in **filename** per mapper rules).
   - Optional CRM updates CSV (`leadstatus`, `updated_on` / `leadcreateddate` when available).

2. **Generate REISift import CSVs** — pick one:
   - **In-app (recommended):** Docker UI `http://localhost:3300` → **Past patches** → upload cold CSV + SMS folder (multi-file) + CRM CSV + closings `.xlsx` → **Run preview** → **Download REISift import bundle** (zip of four CSVs). `.xls` closings are not supported in Docker (use `.xlsx` or the standalone mapper).
   - **Standalone GUI:** `python marketing_ingestion_mapper.py` — preview mapping coverage; fix unmapped statuses or enable “allow unmapped” after review. Export folder receives the same four files when closings path is set.

3. **Import into REISift** (per REISift’s bulk-update docs for each file type). Spot-check a few rows before full run.

4. **Export from REISift** a contacts/properties CSV that includes at least:
   - `Property address`, `Property city`, **`Tags`**
   - Any columns your matching logic expects (see `backend/app/services/analysis.py`).

5. **Run closings analysis**
   - **Docker:** UI `http://localhost:3300`, API `http://localhost:8000` (see Gotchas).
   - **Local:** `README.md` — Flask on 8000, Vite on 3000.
   - Upload **closed deals Excel** + **contacts CSV**. Optional **`as_of`** filter is still supported on **`POST /api/analyze`** (not shown in the current UI).

6. **Archive**
   - Download Excel/CSV/JSON export from the UI.
   - Optionally compare two job IDs via `/api/compare`.

---

## Backdated playbook A — Past patches: full mapper → REISift CSV bundle

**When:** You need a one-time ingest of cold calling + SMS + CRM + closings into REISift-shaped files (same outputs as the standalone marketing mapper).

**Outputs (zip or single download from the app):**

- `property_status_updates.csv`
- `phone_status_tags_updates.csv`
- `salesforce_status_tags.csv`
- `closings_status_tags.csv` — closing-month markers in the form **`(CLOSED) 8020 - MM/YYYY`** (examples: `03/2025`, `3-2025`). These do **not** increment CC/SMS/DM counts; attribution still uses `(8020) CC|SMS|DM - …` **before** each deal’s `Date Closed`.

**Steps**

1. Open the web UI → **Past patches** (Docker: `http://localhost:3300`).
2. Upload **Cold Calling CSV**, **SMS CSVs** (folder picker or multi-file drop), **CRM updates CSV**, **Closings `.xlsx`**.
3. **Run preview** — review metrics and unmapped statuses; adjust source files or use **Allow unmapped** on export if acceptable.
4. **Download REISift import bundle** (or individual CSVs). Confirm column shapes against REISift’s bulk-import docs.
5. Import into REISift; re-export contacts; run **Regular updates** analysis in this app.

---

## Backdated playbook B — Old CRM → Historical Salesforce-style tags

**When:** You have a CRM extract with historical `updated_on` / lead created dates.

**Steps**

1. Feed the CRM CSV into the mapper’s **CRM Updates** picker.
2. Export includes `salesforce_status_tags.csv` with rows like:
   - `(SF) UPDATED - {status} - YYYY-MM-DD` (date from CRM `updated_on` when parse succeeds)
   - `(SF) STATUS - …` for eligible lead rows (from lead created date)
3. Import that file into REISift per their tag-import workflow.
4. Re-export contacts; run closings analysis.

**Caveat:** If `updated_on` format does not match the mapper’s strict parser, the UPDATED tag row may be skipped — check mapper preview / validation columns.

---

## Backdated playbook C — Period snapshot (`as_of`) — API only

The **Past patches** screen no longer drives “as-of” analysis; use **`POST /api/analyze`** with optional **`as_of`** (`YYYY-MM-DD`) if you need only deals with **`Date Closed` ≤ as_of** (e.g. quarter-end). Persisted paths: `{REPORTS_DIR}/snapshots/{YYYY-MM-DD}/{job_id}.json` vs normal `{REPORTS_DIR}/{job_id}.json`. Delete old `snapshots/` when no longer needed.

---

## Tag vocabulary cheat sheet

| Tag pattern | Meaning in parser |
|-------------|-------------------|
| `(8020) CC - MM/YYYY` | Cold call touch (month granularity) |
| `(8020) SMS - MM/YYYY` | SMS touch |
| `(8020) DM - MM/YYYY` | DM touch |
| `List Purchased 8020 MM/YYYY` | Parsed; not counted in CC/SMS/DM pre-close totals |
| `Skip Traced … MM/YYYY` | Parsed; optional “Versium”; not counted in CC/SMS/DM totals |
| `(CLOSED) 8020 - MM/YYYY` | Closing-month marker; not counted as CC/SMS/DM |
| `(SF) UPDATED - …` / other free text | **Not** parsed by this app’s `parse_tags` — still stored in REISift for humans / exports |

**Separator:** `MM/YYYY` or `MM-YYYY` for 8020 and CLOSED lines.

---

## Gotchas (docs vs reality)

| Topic | Detail |
|-------|--------|
| **Docker UI port** | Compose maps **3300 → 80** (nginx). Not 3000. |
| **Stale UI in Docker** | The **frontend** image bakes in `dist/` at **build** time (no host bind mount). After changing React code, rebuild: `docker compose build frontend && docker compose up -d frontend` (add `--no-cache` if the browser still shows old JS). |
| **CORS / API URL in Docker** | Compose build sets `VITE_API_URL=/api` so the browser calls **same-origin** `http://localhost:3300/api/...` and nginx proxies to the backend. Without that, the bundle defaulted to `http://localhost:8000/api` and often showed **Network Error** from `:3300`. |
| **OpenAPI `/docs`** | This stack is **Flask**, not FastAPI — **`/docs` is 404**. |
| **Stale repo docs** | `README-DEV.md` / some deployment notes may mention uvicorn/FastAPI or port 3000 for Docker — trust **docker-compose.yml** + this runbook. |
| **`useWebSocket.ts`** | Present in frontend but **unused**; progress uses **HTTP polling**. |
| **Tag day precision** | All parsed tag dates normalize to **first of month**; comparison to `Date Closed` uses full close timestamp from Excel. |

---

## Quick reference — API

| Endpoint | Purpose |
|----------|---------|
| `POST /api/upload` | Multipart: `excel_file`, `csv_file` |
| `POST /api/analyze` | JSON: `excel_path`, `csv_path`, optional `as_of` (`YYYY-MM-DD`) |
| `GET /api/analysis/<job_id>/status` | Poll while running |
| `GET /api/analysis/<job_id>` | Full results |
| `GET /api/analysis/<job_id>/export?format=excel\|csv\|json` | Download |
| `GET /api/analyses` | List saved jobs |
| `DELETE /api/analysis/<job_id>` | Remove job + JSON (any location under `REPORTS_DIR`) |
| `POST /api/patches/upload` | Multipart: `cold_csv`, `crm_csv`, `closings_xlsx`, repeated `sms_files` — returns `job_id`, `metrics`, `samples` |
| `GET /api/patches/<job_id>/export?file=all\|property\|phone\|sf\|closings&allow_unmapped=true\|false` | Zip or single CSV |
| `DELETE /api/patches/<job_id>` | Remove patch job working dir |

---

## Environment

| Variable | Role |
|----------|------|
| `REPORTS_DIR` | Persisted JSON (default `/app/reports` in Docker) |
| `VITE_API_URL` | Frontend API base at build time (dev default `http://localhost:8000/api`) |
