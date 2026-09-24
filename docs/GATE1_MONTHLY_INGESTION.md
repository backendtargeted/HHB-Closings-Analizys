# Gate 1 monthly ingestion

Choose the Cold calling, SMS, or Salesforce tab. Each has its own reporting month, uploads, preview, processing, and downloads, retained when switching tabs. A calling run needs only the calling CSV; an SMS run needs only SMS CSVs. Salesforce accepts any one report or several reports together. Other tabs never add requirements or files to the selected run. Each run covers one month. Repeat with another month without renaming source files. The legacy CRM workflow remains available separately.

The UI submits a background run and polls its result. Finished exports are stored under `backend/uploads/patches/<job_id>` and remain downloadable after a server restart. An interrupted unfinished run must be submitted again. Nothing is imported into REISift automatically.

## Dates and tags

| Source | Inclusion and evidence | Tag |
|---|---|---|
| Calling | `Log Time (Date)` or another supported activity-date column must fall in the selected month. `Log Time (Time)` orders same-day status changes. | `(MARKETING) CC - M/YYYY` |
| SMS | Row `Labels`/`Label`/`Status` takes precedence over a status filename. Supports `Phone` and `Phone 1`. Source activity dates control inclusion when supplied. | `(MARKETING) SMS - M/YYYY` |
| Qualified Leads | `Create Date` (then missing-date aliases) establishes lead creation, not the present Lead Status or a dated qualification. | `(SF) STATUS - New - YYYY-MM-DD` |
| Opportunities | Actual `Created Date` establishes an opportunity. Present Stage is not backdated; `Close Date` is not treated as an actual closure or loss. | `(SF) UPDATED - Opportunity - YYYY-MM-DD` |
| Transactions | Actual contract-signed fields establish contract events. `Closed Date` requires a recognized closed Path; scheduled dates and dead/pending deals do not create closing tags. | `(SF) UPDATED - Under Contract - YYYY-MM-DD`; `(CLOSED) 8020 - M/YYYY` |

Missing campaign dates use the explicitly selected month, with blank event day and `selected_month_fallback` provenance. Invalid populated dates are excluded, never replaced with the selected month. Salesforce dates have no month fallback. Tags retain the established monthly campaign grammar; audit columns preserve exact source dates where known. No upload date or system date decides the reporting month.

Marketing tags do not identify a list provider. The existing closing token contains `8020` for compatibility but is not marketing attribution evidence. Downstream parsing recognizes the new MARKETING tokens and deduplicates the same channel/month represented by both old and new tokens.

## Status corrections and review

- Decision Maker – NYI is no longer automatically promoted to Lead. Unknown business labels remain unresolved.
- Do Not Call maps to DNC; formatting synonyms such as Call Back and New Lead normalize without inferring a new business stage.
- Several SMS labels map to one phone update only when every label resolves to the same disposition. Contradictory or unknown labels go to review.
- Explicitly untouched records and records labeled only Undefined, No Label, or Duplicate do not establish SMS marketing activity.
- A property receives at most one calling status update per run; a phone receives at most one SMS status update. Latest dated evidence wins. Conflicting same-time or undated evidence is held for review; source-file order does not decide it. An unresolved latest call does not restore an older Lead status.
- Salesforce tags are generated independently of matching a calling/SMS row. Salesforce snapshots do not overwrite campaign evidence.

## Download bundle

- `marketing_activity_tags.csv`: map `tag` to property tags. Multiple dated evidence rows can contain the same monthly token; report parsing counts the channel/month once.
- `salesforce_status_tags.csv`: map `salesforce_tag` to property tags; includes closing markers.
- `property_status_updates.csv` and `phone_status_tags_updates.csv`: resolved status snapshots. For historical backfills, importing these can overwrite current REISift statuses; use dated tag imports when preserving current status.
- `salesforce_events.csv`, `ingestion_review.csv`, `ingestion_summary.json`, and `README.txt`: audit evidence and instructions, not tag import files.

Only relevant source exports are downloadable. The preview reports source-row counts, missing-date fallbacks, exclusions, duplicates, unmapped labels, and sample tags. Missing-date counts overlap included campaign rows. A Salesforce transaction can produce more than one milestone tag.

Import the chosen CSVs into REISift, then re-export contacts for subsequent report gates. Do not upload the audit files as tags.
