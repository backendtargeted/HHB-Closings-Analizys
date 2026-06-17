# HHB Closings + Marketing — Operations Runbook

End-to-end process: normalize marketing data → **REISift** → export contacts → **Contact Attribution Analysis** (this repo). Includes **backdated** closings, historical CRM tags, **monthly consolidated** list/distress reporting, and (API-only) **period snapshots** (`as_of`).

---

## Stack overview

```text
marketing_ingestion_mapper.py  →  REISift import CSVs  →  REISift (system of record)
                                                              ↓
                                                    Contacts export (CSV + Tags)
                                                              ↓
HHB web app / API: contact-history CSV (source of truth) + optional legacy closings workbook  →  reports + exports
                                                              ↓
Salesforce Total Qualified Leads export  →  Monthly consolidated (list + channel + journey)
```

- **Mapper (standalone GUI):** `Python_Tools/7_Utilities/marketing_ingestion_mapper.py` — same logic as the in-app generator below (keep in sync until consolidated).
- **Mapper (this repo):** `backend/app/services/marketing_mapper.py` — used by **Past patches** in the web UI: cold-calling CSV, many SMS CSVs, CRM extract, closings `.xlsx` → the four REISift-shaped CSVs.
- **REISift**: holds property/phone + **Tags** (comma-separated history) and **Lists** (comma-separated distress / list membership on the contacts export).
- **This app**: runs CSV-first analysis from **Tags** (and optionally uses legacy closings workbook input); parses 8020 contact lines, list purchase, skip trace, **(SF) CRM** tags, and **closing** markers; derives **lead lifecycle** (funnel, paths, first-touch) for the UI and exports (see cheat sheet + `backend/app/services/lifecycle.py`).
- **Consolidated list report** (`backend/app/services/monthly_consolidated.py`): ranks REISift **Lists** across the **full uploaded export** by CRM signals, qualified leads, and closings; embeds qualified-lead channel mix and closing-cohort lifecycle in one XLSX. (API path remains `/api/monthly-consolidated`.)

**Report methodology (deep dive):** [docs/REPORT_METHODOLOGY.md](docs/REPORT_METHODOLOGY.md) — tag parsing, dedupe rules, matching, counting, lifecycle, exports, and experimental cadence probes.

---

## Standard monthly process

1. **Gather inputs**
   - Cold-calling export (required columns: `Phone`, `Address`, `City`, `State`, `Zip Code`, `Log Type`).
   - SMS bucket: folder of CSVs (status often encoded in **filename** per mapper rules).
   - Optional CRM updates CSV (`leadstatus`, `updated_on` / `leadcreateddate` when available).

2. **Generate REISift import CSVs** — pick one:
   - **In-app (recommended):** Docker UI `http://localhost:3300` → **Past patches** → upload cold CSV + SMS folder (multi-file) + CRM CSV + closings workbook `.xlsx` → **Run preview** → **Download REISift import bundle** (zip of four CSVs). `.xls` closings are not supported in Docker (use `.xlsx` or the standalone mapper).
   - **Standalone GUI:** `python marketing_ingestion_mapper.py` — preview mapping coverage; fix unmapped statuses or enable “allow unmapped” after review. Export folder receives the same four files when closings path is set.

3. **Import into REISift** (per REISift’s bulk-update docs for each file type). Spot-check a few rows before full run.

4. **Export from REISift** a contacts/properties CSV that includes at least:
   - `Property address`, `Property city`, **`Tags`**, **`Created`**
   - **`Lists`** (required for **Monthly consolidated**; comma-separated distress / list tokens per property)
   - Any columns your matching logic expects (see `backend/app/services/analysis.py`).

5. **Run reports** (pick what you need each month):
   - **Consolidated list report (recommended for list + channel + journey):** UI → **Consolidated list report** → upload full REISift export + Salesforce **Total Qualified Leads** export → **Run consolidated report** → download XLSX. No month picker. See [Consolidated list report](#consolidated-list-report) below.
   - **Regular attribution:** UI → **Regular updates** → upload contacts CSV. Closed deals are derived from tags; optional legacy closings workbook upload remains supported. Optional **`as_of`** filter is still supported on **`POST /api/analyze`** (not shown in the current UI).
   - **Qualified leads only:** UI → **Qualified leads** → SF export + Create Date window (same QL rules embedded in monthly consolidated).

6. **Archive**
   - Download Excel/CSV/JSON export from the UI. Regular attribution Excel includes a **Lifecycle Events** sheet (one row per parsed tag event before close, when events exist).
   - Monthly consolidated XLSX includes Summary, List Performance, List Combinations, Qualified Channels, Lifecycle (+ Top Paths when closings exist in cohort).
   - Optionally compare two attribution job IDs via `/api/compare`.

**Saved reports:** JSON snapshots written before lifecycle fields were added will **not** include funnel/path columns; re-run analysis to populate them. Monthly consolidated reports persist under `{REPORTS_DIR}/monthly_consolidated/{job_id}.json` and appear in the sidebar with type **Monthly consolidated**.

---

## Minimum Contact History CSV for analysis

CSV-only analysis (`POST /api/analyze` with `csv_path` only) builds closed deals from **tags** on each row (`derive_closed_deals_from_csv` in `backend/app/services/analysis.py`), then matches by row index. Upload validation only checks that the file parses as CSV (`validate_csv_file`); it does **not** validate column names until analysis runs.

### Columns (strict minimum to produce deals)

| Column | Required? | Notes |
|--------|------------|--------|
| **`Tags`** | Yes | All contact, `(SF)`, list/skip, and `(CLOSED) 8020 - …` signals are read from this comma-separated field. |
| **Address** | Yes (per deal row) | Built as `Property address` + space + `Property city`. If `Property address` is empty, the code falls back to **`Address`** only. Without a non-empty combined address after that logic, the row cannot become a derived closed deal. |
| **`Lead Source`** / `Lead source` / `LeadSource` | No | Defaults to `"Contact History Tags"` when missing. |
| **`Property city`** | No | Improves the displayed address when `Property address` is set. |

**Legacy path:** If you upload an optional closings workbook, matching uses **`Property address`** and **`Property city`** on the CSV (`match_deals_to_csv`). Keep those columns if you use workbook matching.

### Rows (trimming safely)

- **One row = one tag blob:** All history for a property must stay on the **same** row’s `Tags` field. Do not split tags across removed rows.
- **Safe size reduction:** Drop rows where `Tags` is empty.
- **Aggressive filter (only if one export row holds the full history per closed deal):** Keep rows that contain a recognized close signal, e.g. `(CLOSED) 8020 - MM/YYYY` (or `M/YYYY`), and/or `(SF) UPDATED` / `(SF) STATUS` with a label that normalizes into converted labels in `backend/app/services/lifecycle.py`. If you remove the only row that carries a deal’s tags, that deal disappears from results.

**Practical minimum export:** Headers at least `Tags`, `Property address`, `Property city` (or rely on `Address` when street is empty), optionally `Lead Source`; then apply the row filters above.

**Consolidated list report minimum:** **`Lists`**, **`Tags`**, and address columns for qualified-lead matching. **`Created`** is optional (shown in Summary as min–max span when present); it is **not** used to filter rows in the default UI flow.

---

## Consolidated list report

**When:** Review which REISift distress **lists** correlate with CRM activity, qualified leads, and closings — plus channel mix and closing-cohort journey — across your **current full REISift export**.

**UI:** Docker `http://localhost:3300` → **Consolidated list report** (fourth workflow tab).

**Implementation:** `backend/app/services/monthly_consolidated.py`, API prefix `/api/monthly-consolidated`.

### Inputs

| File | Required columns | Role |
|------|------------------|------|
| **REISift contacts export** | `Lists`, `Tags`, address fields | **All rows** in file → list metrics + CRM/closing tags |
| **Salesforce Total Qualified Leads** | `Lead Source`, `Create Date` (+ address for list attribution) | Full-file Create Date span (same as QL “use full file span”) |

### Cohort (default — no month filter)

- **Cohort** = **every row** in the uploaded REISift CSV (after column validation).
- Qualified leads use the **full Create Date span** of the uploaded Salesforce file.
- Summary sheet may show REISift **Created** min→max as informational context only.
- **Future:** comparing time periods (month-over-month) is out of scope for v1; optional API form field `report_month=YYYY-MM` still exists for scripts if needed later.

### Metric definitions (locked product rules)

| Metric | Definition |
|--------|------------|
| **CRM leads** | Cohort rows with any **`(SF)`** token in `Tags` (e.g. `(SF) UPDATED`, `(SF) STATUS`) — no separate SF CRM file |
| **Qualified leads** | Rows in the SF export passing existing **Total Qualified Leads** rules; **Create Date** filtered to the same calendar month as the cohort |
| **Closings** | Cohort rows with **`(CLOSED) 8020 - MM/YYYY`** (or `M/YYYY`) in `Tags` — same parser as regular attribution |
| **List attribution** | Comma-split **`Lists`**; each property **counts toward every list** on its row (**stacked** = multiple tokens = positive signal) |
| **Closing rate (per list)** | `closings on that list ÷ REISift cohort rows carrying that list token` |
| **List combinations** | **≥2 stackable distress lists** per row (excludes source/import and hygiene lists: DNC, Dead Deals, Closings App, MLSLI, TBD, Buyers, etc.); min rows = **median** multi-list combo size (floor 5); grouped by primary list; ranked by closings (export capped at top 100) |
| **Qualified → list credit** | Address join (`make_address_key`) between in-window SF rows and cohort REISift rows; unmatched SF rows are reported in warnings when match rate &lt; 50% |

Optional column **`List Stack`** (numeric) is present on many exports but is **not** used as the primary stacked classifier — parsed token count on `Lists` drives stacked stats.

### XLSX sheets

| Sheet | Content |
|-------|---------|
| Summary | Cohort counts, CRM/closing/stacked totals, period metadata |
| List Performance | Per-list rows, rates, stacked row counts |
| List Combinations | ≥10-row combinations, ranked by closings |
| Qualified Channels | Channel counts/shares (same as QL workspace) |
| Lifecycle | Funnel stage counts for **closing rows in cohort** |
| Top Paths | Top journey paths (when lifecycle data exists) |

### Large REISift files

Exports with **500k+ rows** are supported but the analyze request is **synchronous** (expect **30–90 seconds**). Apply the same proxy timeout guidance as [Large uploads and reverse proxies](#large-uploads-and-reverse-proxies-easypanel--traefik) if the browser or edge proxy cuts off before the backend finishes.

### Operator checklist

1. Complete REISift ingest / tag updates as needed (Past patches or regular mapper flow).
2. Export **full** contacts CSV including **`Lists`**, **`Tags`**, addresses (and **`Created`** if available).
3. Export Salesforce **Total Qualified Leads** (full export you normally use).
4. Run **Consolidated list report**; review warnings (especially QL address match rate on large files).
5. Download consolidated XLSX; archive alongside any **Regular updates** attribution runs you still run ad hoc.

---

## Marketing ramp report (Gate 3 — unified monthly)

**When:** Measure **lead journey timing** (list → touch → qualified lead → contract → close) per address, **and** include the full **Gate 2 consolidated list report** on the same run.

**UI:** Docker `http://localhost:3300` → **Marketing ramp report** (Gate 3 tab).

**Implementation:** `backend/app/services/marketing_ramp.py` + `monthly_unified.py` (parallel Gate 2), API prefix `/api/marketing-ramp`.

### Inputs

| File | Required columns | Role |
|------|------------------|------|
| **Salesforce Total Qualified Leads** | `Lead Source`, `Create Date`, address | Population rows with Create Date in window |
| **REISift contacts export** | `Tags`, address fields | Touch tags, list purchase, REISift match |
| **Closings workbook** | `Date Closed`, address, `Stage` | Close dates (Closed Lost excluded) |

### Population window

- Default: **Use full file date span** — union of QL Create Date range and closings Date Closed range.
- Optional: explicit `start_date` / `end_date` on the upload form.

### Touch counts (summary panel)

- **Total touches by channel** = sum of all `(8020) CC`, `(8020) SMS`, and `(8020) DM` contact tags across matched REISift rows (Cold Calling, SMS, Direct Mail).
- Per-row journey export still includes `cc_touch_count`, `sms_touch_count`, `dm_touch_count`, and `first_touch_channel`.
- Tags must exist in REISift export; Past patches cold-calling/SMS uploads do **not** auto-generate `(8020)` tags.

### Unified run (Gate 2 + Gate 3)

Each Gate 3 analyze runs **marketing ramp** and **monthly consolidated** in parallel on the shared REISift + QL uploads (closings used only for ramp). The UI shows both sections on one page.

### Export

- **Download full XLSX** — all Gate 2 sheets (Summary, List Performance, combinations, channels, lifecycle, etc.) plus a **Marketing Ramp** sheet with journey rows.
- Legacy saved reports without embedded consolidated data fall back to CSV export (ramp rows only).

### Operator checklist

1. Export Salesforce Total Qualified Leads, REISift contacts, and closings workbook for the period.
2. Run **Marketing ramp report** with all three files.
3. Review total touches (CC / SMS / DM), journey rows, and consolidated list performance on the same screen.
4. Download full XLSX for archiving.

---

## Large uploads and reverse proxies (EasyPanel / Traefik)

Large upload flows can fail when the **UI** nginx container or front proxy timeouts are too low (`frontend/nginx.conf`: `client_max_body_size`, `client_body_timeout`, `proxy_*_timeout`).

**Symptoms:** Small test uploads return `200`; large uploads fail around **60 seconds** with `400`/`502` from the UI hostname, while `GET /api/analyses` still works. Backend logs may show **no** request for the failed upload.

**Cause:** A **front** proxy (commonly **Traefik** on the EasyPanel host) often defaults to a **~60s** responding/read timeout for the client → edge hop. The UI container’s nginx cannot override that.

**Fix (operations):** In EasyPanel (or Traefik static/dynamic config for the `crm-reports-ui` route), raise responding timeouts to at least **600s** to align with UI nginx and backend Gunicorn (`backend/Dockerfile` uses a 600s worker timeout). Exact labels depend on your Traefik version; look for entrypoint or router **read timeout** / **responding timeouts** and increase them for the UI (and API if you upload directly to the API host).

**Optional app-side mitigation:** UI nginx `/api` uses `proxy_request_buffering off` and `proxy_buffering off` (see `frontend/nginx.conf`) to reduce temp-file buffering during long-running upload traffic; redeploy the **frontend** image after changes.

**Backend:** Ensure the API image is rebuilt so Gunicorn runs with high `--timeout` (see `backend/Dockerfile`).

**Upload path:** Gate 2 sends **both whole files in one multipart POST** to `POST /api/monthly-consolidated/analyze` (same as qualified-leads). The backend saves the files and runs analysis — **not row-by-row**. If the edge proxy drops that request (502/timeout), the UI automatically falls back to **binary file chunks** (`/api/upload/resumable/...`) and then starts analysis from assembled paths.

---

## Resumable local uploads (single-host default)

`GET /api/upload/capabilities` now returns `{"resumable_upload": true, "presigned_upload": false, "limits": ...}`. The UI initializes an upload session, sends chunked `PUT`s, then finalizes to get a local `csv_path` / `closings_path` for analysis.

### Required API environment variables

None for baseline operation (works out-of-the-box with local upload storage).

### Optional

| Variable | Default | Role |
|----------|---------|------|
| `UPLOAD_STORAGE_DIR` | `/app/uploads` | Root directory for uploaded files/sessions/chunks. |
| `UPLOAD_MAX_CHUNK_MB` | `8` | Max accepted chunk size for resumable uploads. |
| `UPLOAD_MAX_TOTAL_MB` | `MAX_UPLOAD_MB` | Max total file size for a resumable session. |
| `UPLOAD_SESSION_TTL_HOURS` | `24` | Expiry window for stale resumable sessions/chunks. |

### Analyze request shape

- `csv_path` is required.
- Optional closings path: `closings_path` (legacy alias `excel_path` remains accepted).

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
2. Upload **Cold Calling CSV**, **SMS CSVs** (folder picker or multi-file drop), **CRM updates CSV**, **Closings workbook `.xlsx`**.
3. **Run preview** — review metrics and unmapped statuses; adjust source files or use **Allow unmapped** on export if acceptable.
4. **Download REISift import bundle** (or individual CSVs). Confirm column shapes against REISift’s bulk-import docs.
5. Import into REISift; re-export contacts; run **Regular updates** analysis in this app.

**One-time Podio backfill (scripts, not UI):** When closings live in Podio exports rather than legacy Report `.xlsx` with address columns, use `scripts/one_time_podio_closings_opps_tags_bundle.py` (Podio Closings + Tina New Opportunities Closed/Executed merge) or `scripts/one_time_samples_reisift_zip.py` (Podio Closings only). Artifacts under `_ingest_out/`. See [docs/REPORT_METHODOLOGY.md §11](docs/REPORT_METHODOLOGY.md#11-one-time-podio--offline-ingest-scripts).

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
| `(SF) UPDATED - {status} - YYYY-MM-DD` | Parsed for **lifecycle** (day precision); status label matched to engaged/converted heuristics |
| `(SF) STATUS - {status} - YYYY-MM-DD` | Same (typically lead-created row from mapper) |

**Duplicate tags:** If REISift (or a double import) leaves the **same** token twice in `Tags`, the parser dedupes by `(type, date, channel, label)` so CC/SMS/DM totals and lifecycle are not inflated. See [docs/REPORT_METHODOLOGY.md §4.2](docs/REPORT_METHODOLOGY.md#42-duplicate-tag-deduplication).

**Separator:** `MM/YYYY` or `MM-YYYY` for 8020 and CLOSED lines; `(SF)` lines use **`YYYY-MM-DD`** at the end of the tag.

### Lead lifecycle stages (analysis)

Stages are computed only from tags **strictly before** each deal’s **Date Closed** (except “closed deal” itself uses the derived close date / optional legacy workbook close date):

| Stage | Signal |
|-------|--------|
| ACQUIRED | `List Purchased 8020 …` |
| RESEARCHED | `Skip Traced …` |
| FIRST_CONTACTED | First `(8020) CC\|SMS\|DM …` |
| ENGAGED | `(SF) …` with CRM label in the engaged allow-list (`lifecycle.py`) |
| CONVERTED | `(SF) …` with label treated as converted (e.g. `converted`) |
| CLOSED | Deal has a close date (always true for analyzed deals) — **not** used for “Highest stage” ranking |

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
| **Tag date precision** | `(8020)`, list, skip, `(CLOSED)` use **first of month**; `(SF) UPDATED` / `(SF) STATUS` use **calendar day** (`YYYY-MM-DD`). Comparison to `Date Closed` uses the full close timestamp for the analyzed deal row. |
| **Large CSV upload via UI / EasyPanel** | UI nginx timeouts and body size are in `frontend/nginx.conf`. If large uploads still die near **60s**, raise Traefik/EasyPanel ingress timeouts — see **Large uploads and reverse proxies (EasyPanel / Traefik)**. |
| **Monthly consolidated on huge exports** | Two multipart files (REISift + SF QL); analysis runs synchronously after upload. Timeouts affect **POST** `/api/monthly-consolidated/analyze`, not just resumable attribution uploads. |

---

## Experimental: cadence probes (offline)

**Not** part of the web UI report. Uses the same tag parser to summarize **days between consecutive events** on a REISift export — useful when designing future outreach cadences (see Data Orchestration / Golden Loop brainstorm).

```bash
python scripts/probe_contact_cadence_from_csv.py --csv path/to/export.csv --limit 2000 --mode before_close
```

Module: `backend/app/services/cadence_from_history.py`. `(8020)` tags are month-granular; `(SF)` day tags improve gap resolution. Details: [docs/REPORT_METHODOLOGY.md §12](docs/REPORT_METHODOLOGY.md#12-experimental-cadence-from-history).

---

## Quick reference — API

| Endpoint | Purpose |
|----------|---------|
| `GET /api/upload/capabilities` | Returns upload features/limits (`resumable_upload`, `presigned_upload`, size limits) |
| `POST /api/upload/resumable/init` | JSON `{ kind, filename, total_size, chunk_size }` → upload session metadata (`upload_id`, chunk config) |
| `PUT /api/upload/resumable/<upload_id>/chunk/<chunk_index>` | Binary chunk upload (idempotent overwrite of a chunk index) |
| `GET /api/upload/resumable/<upload_id>/status` | Session progress (`uploaded_chunks`, `total_chunks`, `status`) |
| `POST /api/upload/resumable/<upload_id>/complete` | Assemble chunks and return `csv_path` or `closings_path` |
| `DELETE /api/upload/resumable/<upload_id>` | Cancel and cleanup a resumable upload session |
| `POST /api/analyze` | JSON: required `csv_path`; optional `closings_path` (legacy alias `excel_path` still accepted); optional `as_of` (`YYYY-MM-DD`) |
| `GET /api/analysis/<job_id>/status` | Poll while running |
| `GET /api/analysis/<job_id>` | Full results |
| `GET /api/analysis/<job_id>/export?format=excel\|csv\|json` | Download |
| `GET /api/analyses` | List saved jobs |
| `DELETE /api/analysis/<job_id>` | Remove job + JSON (any location under `REPORTS_DIR`) |
| `POST /api/patches/upload` | Multipart: `cold_csv`, `crm_csv`, `closings_xlsx`, repeated `sms_files` — returns `job_id`, `metrics`, `samples` |
| `GET /api/patches/<job_id>/export?file=all\|property\|phone\|sf\|closings&allow_unmapped=true\|false` | Zip or single CSV |
| `DELETE /api/patches/<job_id>` | Remove patch job working dir |
| `POST /api/qualified-leads/analyze` | Multipart: `qualified_leads_file` (.csv/.xlsx); form `use_full_file_span`, optional `start_date` / `end_date` (`YYYY-MM-DD`) |
| `GET /api/qualified-leads/<job_id>` | Qualified leads metrics JSON |
| `GET /api/qualified-leads/<job_id>/export` | Row-level CSV (channel, in-window flag) |
| `DELETE /api/qualified-leads/<job_id>` | Remove qualified-leads job dir |
| `POST /api/monthly-consolidated/analyze` | Multipart: `reisift_file`, `qualified_leads_file`; optional form `report_month=YYYY-MM` (omit in UI = full file) |
| `GET /api/monthly-consolidated/<job_id>` | Monthly consolidated metrics JSON |
| `GET /api/monthly-consolidated/<job_id>/export` | Multi-sheet XLSX (Summary, lists, combinations, channels, lifecycle) |
| `DELETE /api/monthly-consolidated/<job_id>` | Remove job dir + saved JSON |
| `GET /api/reports` | All saved reports (attribution + qualified leads + monthly consolidated) |
| `GET /api/reports/diagnostics` | Storage health: resolved path, writable flag, report counts by type |

**Report persistence:** Attribution → `{REPORTS_DIR}/{job_id}.json` or `snapshots/{as_of}/`. Qualified leads → `{REPORTS_DIR}/qualified_leads/{job_id}.json`. Monthly consolidated → `{REPORTS_DIR}/monthly_consolidated/{job_id}.json`. Upload working copies → `{UPLOAD_STORAGE_DIR}/monthly_consolidated/{job_id}/`. Docker Compose mounts `./data/reports:/app/reports` (host folder survives image rebuilds; avoid `docker compose down -v` on upload volumes if you need those too).

### Report persistence troubleshooting

1. **Before first `docker compose up`:** create the host folder: `mkdir -p data/reports` (Windows: `mkdir data\reports`).
2. **Verify storage after deploy:** `curl -s http://localhost:8000/api/reports/diagnostics` — expect `"writable": true` and `"resolved_path": "/app/reports"` (or your `REPORTS_DIR`).
3. **Easypanel / single-service image:** mount a persistent volume at `/app/reports` and set `REPORTS_DIR=/app/reports`. Without a volume, reports live inside the container filesystem and are lost on every image rebuild.
4. **Startup logs:** backend logs `Reports storage: path=... writable=...` on boot. In production (`ENV=production`), startup fails if the reports path is not writable.
5. **Do not use `docker compose down -v`** if you need upload session history; the `uploads` named volume is removed. The `./data/reports` bind mount survives unless you delete the host folder.

---

## Environment

| Variable | Role |
|----------|------|
| `REPORTS_DIR` | Persisted JSON (default `/app/reports` in Docker; compose bind-mounts `./data/reports` so rebuilds keep reports) |
| `ENV` | Set to `production` to fail startup when `REPORTS_DIR` is not writable |
| `ALLOW_EPHEMERAL_REPORTS` | Set to `1` in dev/CI to allow temp-dir fallback when no writable path exists |
| `VITE_API_URL` | Frontend API base at build time (dev default `http://localhost:8000/api`) |
| `UPLOAD_STORAGE_DIR` | Root directory for resumable upload files/chunks/manifests |
| `UPLOAD_MAX_CHUNK_MB` | Per-chunk limit for resumable uploads |
| `UPLOAD_MAX_TOTAL_MB` | Per-file limit for resumable upload sessions |
| `UPLOAD_SESSION_TTL_HOURS` | Time-to-live for stale resumable upload sessions |
