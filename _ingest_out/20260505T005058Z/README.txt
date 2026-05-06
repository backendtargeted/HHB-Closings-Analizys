One-time REISift bundle from Data_ingestion_samples (RUNBOOK Past patches / mapper).

ZIP: reisift_import.zip contains property_status_updates.csv, phone_status_tags_updates.csv,
salesforce_status_tags.csv, closings_status_tags.csv.

Tag vocabulary: see RUNBOOK.md Tag vocabulary cheat sheet.
CRM caveat: updated_on must match Salesforce-style TZ offset or rows may skip (ingest_metrics.json).

Not in this mapper pass: podio/Seller Leads, podio/Opportunities, past_patches/Report-*.xlsx, past_patches/past_closings.xlsx (avoid duplicate closings vs Podio Closings).

Generated UTC 20260505T005058Z.