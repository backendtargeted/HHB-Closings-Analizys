Gate 1 monthly ingestion: 2026-09

Review ingestion_summary.json and ingestion_review.csv before importing.
Import marketing_activity_tags.csv as PROPERTY tags using its tag column.
Import salesforce_status_tags.csv as PROPERTY tags using salesforce_tag.
Property and phone status CSVs contain only resolved mappings; historic snapshots can change current REISift statuses.
salesforce_events.csv, ingestion_review.csv and summary files are audit evidence, not imports.
Real event dates determine inclusion. Undated campaign rows use the selected month, never an invented day.
Monthly campaigns do not identify a list provider. No Salesforce snapshot overwrites campaign evidence.
