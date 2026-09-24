"""Recheck streamed details without repeating unchanged large CRM joins."""
import csv
import json
import os
import sys
from collections import Counter
from pathlib import Path

OUT = Path(__file__).resolve().parent
ROOT = OUT.parents[1]
os.environ['REPORTS_DIR'] = str(OUT / 'preview_reports')
sys.path.insert(0, str(ROOT / 'backend'))
from app.services.buybox_towns import evaluate_buybox
from app.services.investor_sold_details import screen_property_details
from app.services.investor_sold import result_from_metrics_dict, build_export_workbook
from app.services.report_store import save_investor_sold_report

baseline = json.loads((OUT / 'verified_report_metrics.json').read_text(encoding='utf-8'))
targets = {r['dataflik_id']: {
    'key': 'df:' + r['dataflik_id'], 'dataflik_id': r['dataflik_id'],
    'county': r['county'], 'state': r['state'], 'sold_month': r['sold_month'],
    'parcels': [], 'sale_events': [],
} for r in baseline['rows']}
with Path(r'C:\Users\USER\Downloads\reproject (1)\sold_properties_full.csv').open(encoding='utf-8-sig', newline='') as stream:
    for row in csv.DictReader(stream):
        target = targets.get(row['dataflik_id'])
        if not target or not evaluate_buybox(row['property_city'], row['property_zip'], county=row['county'], state=row['state']).included:
            continue
        target['parcels'].append(row['parcel_number'])
        if row['period_date'][:7] == target['sold_month']:
            target['sale_events'].append({k: row[k] for k in ('buyer_full_name', 'sale_amount')})
decisions, summary = screen_property_details(r'D:\HHB\CleanREISift\data\sold_property_details.jsonl', list(targets.values()))
metrics_path = OUT / 'screened_report_metrics.json'
metrics = json.loads(metrics_path.read_text(encoding='utf-8'))
assert {k[3:] for k, d in decisions.items() if d['status'] == 'eligible'} == {r['dataflik_id'] for r in metrics['rows']}
for row in metrics['rows']:
    decision = decisions['df:' + row['dataflik_id']]
    for field in ('seller_name', 'seller_category', 'seller_match_status', 'property_type'):
        row[field] = decision[field]
    row['property_details_status'], row['property_details_reason'] = decision['status'], decision['reason']
for row in metrics['property_screening_rows']:
    row.update(decisions['df:' + row['dataflik_id']])
summary['enabled'] = True
summary['seller_categories'] = dict(Counter(r['seller_category'] for r in metrics['rows']))
metrics['property_screening'] = summary
metrics_path.write_text(json.dumps(metrics, indent=2), encoding='utf-8')
report_summary_path = OUT / 'screened_report_summary.json'
report_summary = json.loads(report_summary_path.read_text(encoding='utf-8'))
report_summary['property_screening'] = summary
report_summary_path.write_text(json.dumps(report_summary, indent=2), encoding='utf-8')
result = result_from_metrics_dict(metrics)
assert result.to_api_dict() == metrics
(OUT / 'screened_report.xlsx').write_bytes(build_export_workbook(result))
save_investor_sold_report('gate7-screened-review', metrics, reports_dir=OUT / 'preview_reports')
print(json.dumps(summary, indent=2))
