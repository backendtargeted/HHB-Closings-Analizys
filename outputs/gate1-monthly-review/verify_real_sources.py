"""Read-only source audit through the same Gate 1 service used by the UI."""
import json
from pathlib import Path
import shutil
import sys
import time
import zipfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
from app.services.monthly_ingestion import run_monthly_ingestion, write_monthly_exports

out = Path(__file__).parent
raw = out / "inputs"
raw.mkdir(exist_ok=True)
with zipfile.ZipFile(r"C:\Users\USER\Downloads\rerequestformonthlycallresultsreport.zip") as archive:
    for name in ("Cweb_Sep_Call_Logs_Report.csv", "Charles SMS Labels (2).csv"):
        with archive.open(name) as source, (raw / name).open("wb") as target:
            shutil.copyfileobj(source, target, 1024 * 1024)
sf = Path(r"C:\Users\USER\Downloads\reproject (1)\salesforce reports")
started = time.monotonic()
frames, payload = run_monthly_ingestion(
    "2026-09", cold_path=str(raw / "Cweb_Sep_Call_Logs_Report.csv"),
    sms_entries=[("Charles SMS Labels (2).csv", str(raw / "Charles SMS Labels (2).csv"))],
    qualified_leads=str(next(sf.glob("Tina -  Total Qualified Leads*.xlsx"))),
    opportunities=str(next(sf.glob("New Opportunities*.xlsx"))),
    transactions=str(next(sf.glob("Copy of Transaction Pipeline*.xlsx"))),
)
write_monthly_exports(frames, payload, out / "september")
summary = {"seconds": round(time.monotonic() - started, 1), "monthly": payload["monthly"],
           "metrics": payload["metrics"], "exports": {name: len(frame) for name, frame in frames.items()}}
(out / "verification.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
print(json.dumps(summary, indent=2))
