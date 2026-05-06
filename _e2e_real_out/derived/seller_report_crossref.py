"""
Cross-reference Podio Seller Leads with Report closings by address, then build
main-analysis inputs: Excel uses Report Close Date + Lead Source; CSV uses
Seller street/city + Tags synthesized from Seller SMS Communications dates
that fall strictly before the closing date (8020 tag format expected by analysis.py).
"""

from __future__ import annotations

import re
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "backend"))
from app.services.analysis import normalize_address, normalize_city  # noqa: E402

REPORT = REPO / "Data_ingestion_samples/past_patches/Report-2026-05-04-16-02-00.xlsx"
SELLER = REPO / "Data_ingestion_samples/past_patches/podio/Seller Leads - All Seller Leads.xlsx"
OUT_DIR = Path(__file__).resolve().parent


def _join_key(street: str, city: str) -> str:
    return normalize_address(str(street).strip()) + "|" + normalize_city(str(city).strip())


def _dates_from_blob(text: object) -> list[datetime]:
    if text is None or (isinstance(text, float) and pd.isna(text)):
        return []
    s = str(text)
    out: list[datetime] = []
    for m in re.finditer(r"\b(20\d{2})-(\d{2})-(\d{2})\b", s):
        y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
        try:
            out.append(datetime(y, mo, d))
        except ValueError:
            continue
    return out


def _tags_before_close(sms_blob: object, close: pd.Timestamp) -> str:
    close_ts = pd.Timestamp(close).normalize()
    seen: set[tuple[int, int]] = set()
    parts: list[str] = []
    for dt in _dates_from_blob(sms_blob):
        ts = pd.Timestamp(dt)
        if ts.normalize() >= close_ts:
            continue
        key = (dt.year, dt.month)
        if key in seen:
            continue
        seen.add(key)
        parts.append(f"(8020) SMS - {dt.month}/{dt.year}")
    parts.sort()
    return ", ".join(parts)


def main(max_rows: int = 500) -> None:
    r = pd.read_excel(
        REPORT,
        engine="openpyxl",
        usecols=["Close Date", "Lead Source", "Address (Street)", "Address (City)"],
    )
    r = r.dropna(subset=["Close Date", "Lead Source", "Address (Street)", "Address (City)"])
    r["k"] = r.apply(
        lambda x: _join_key(x["Address (Street)"], x["Address (City)"]),
        axis=1,
    )

    s = pd.read_excel(
        SELLER,
        sheet_name="Seller Leads",
        engine="openpyxl",
        usecols=["Address - Address", "Address - City", "SMS Communications"],
    )
    s = s.dropna(subset=["Address - Address", "Address - City"])
    s["k"] = s.apply(
        lambda x: _join_key(x["Address - Address"], x["Address - City"]),
        axis=1,
    )
    s["sms_len"] = s["SMS Communications"].fillna("").astype(str).str.len()
    s = s.sort_values("sms_len", ascending=False).drop_duplicates(subset=["k"], keep="first")

    j = r.merge(s, on="k", how="inner")
    j = j.sort_values("Close Date").head(max_rows).reset_index(drop=True)

    street = j["Address - Address"].astype(str).str.strip()
    city = j["Address - City"].astype(str).str.strip()
    excel_rows = pd.DataFrame(
        {
            "Address": (street + " " + city).str.strip(),
            "Date Closed": j["Close Date"],
            "Lead Source": j["Lead Source"].astype(str),
        }
    )
    tags = [
        _tags_before_close(blob, close)
        for blob, close in zip(j["SMS Communications"], j["Close Date"])
    ]
    hist = pd.DataFrame(
        {
            "Property address": street,
            "Property city": city,
            "Tags": tags,
        }
    )

    excel_path = OUT_DIR / "e2e_seller_x_report_closings.xlsx"
    csv_path = OUT_DIR / "e2e_seller_x_report_history.csv"
    excel_rows.to_excel(excel_path, index=False)
    hist.to_csv(csv_path, index=False)

    nonempty = sum(1 for t in tags if str(t).strip())
    print("WROTE", excel_path, "rows", len(excel_rows))
    print("WROTE", csv_path, "rows", len(hist), "nonempty Tags", nonempty)


if __name__ == "__main__":
    main()
