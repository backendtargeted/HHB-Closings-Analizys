One-time REISift bundle from Data_ingestion_samples (RUNBOOK Past patches / mapper).

ZIP: reisift_import.zip contains property_status_updates.csv, phone_status_tags_updates.csv,
salesforce_status_tags.csv, closings_status_tags.csv.
Closings rows use split Property address / city / State / Zip Code for REISift;
usaddress may fill gaps when Podio omits city/state/zip (see ingest_metrics usaddress_closings_fallback_rows).

Tag vocabulary: see RUNBOOK.md Tag vocabulary cheat sheet.
CRM caveat: updated_on must match Salesforce-style TZ offset or rows may skip (ingest_metrics.json).

Not in this mapper pass: podio/Seller Leads, podio/Opportunities, past_patches/Report-*.xlsx, past_patches/past_closings.xlsx (avoid duplicate closings vs Podio Closings).

Generated UTC 20260505T012744Z.