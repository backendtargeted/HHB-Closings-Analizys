"""Run the real Gate 7 service against the supplied reports and verify its grain."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
from app.services.investor_sold import analyze, result_from_metrics_dict

source = Path(r"C:\Users\USER\Downloads\reproject (1)")
result = analyze(
    str(source / "sold_properties_full.csv"),
    str(source / "reisift_export.csv"),
    str(source / "Tina -  Total Qualified Leads-2026-09-11-13-34-32.xlsx"),
    str(source / "New Opportunities Report - Tina-2026-09-11-13-36-27.xlsx"),
    str(source / "Copy of Transaction Pipeline-2026-09-11-13-38-11.xlsx"),
    property_details_path=r"D:\HHB\CleanREISift\data\sold_property_details.jsonl",
    on_progress=lambda pct, message: print(f"{pct}% {message}", flush=True),
)
metrics = result.to_api_dict()
restored = result_from_metrics_dict(metrics)
assert result.sold_rows_scanned == 72918
assert result.sold_rows_ingested == 4838
assert result.property_screening["target_count"] == 4790
assert result.property_rows == result.property_screening["eligible"]
assert sum(result.property_screening[k] for k in ("eligible", "excluded", "unresolved")) == 4790
assert len({r.dataflik_id for r in result.rows}) == result.property_rows
assert sum(m["count"] for m in result.by_sold_month) == result.property_rows
assert sum(result.buybox_exclusions.values()) == result.sold_rows_excluded_buybox
assert result.property_grain == restored.property_grain == "property_earliest_sale"
assert [r.to_dict() for r in result.rows] == [r.to_dict() for r in restored.rows]
out = Path(__file__).parent
(out / "screened_report_metrics.json").write_text(json.dumps(metrics, indent=2), encoding="utf-8")
summary = {"property_screening": metrics["property_screening"], "inputs": metrics["inputs"], "multi_transaction_properties": sum(r.transaction_count > 1 for r in result.rows),
    "by_first_sold_month": metrics["by_sold_month"], "lost": metrics["lost"], "match": metrics["match"]}
(out / "screened_report_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
print(json.dumps(summary, indent=2), flush=True)
