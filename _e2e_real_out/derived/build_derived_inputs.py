"""Build derivative CSV/XLSX for REAL E2E API tests from Data_ingestion_samples only."""

from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent


def main() -> None:
    sms_src = REPO / "Data_ingestion_samples/Weekly_and_monthly/Charles SMS Logs.csv"
    ch = pd.read_csv(sms_src, low_memory=False, nrows=4000)
    ch2 = pd.DataFrame(
        {
            "Phone": ch["Phone 1"].astype(str).str.strip(),
            "Property address": ch["Address"].astype(str),
            "Property city": ch["City"].astype(str),
            "Property state": ch["State"].astype(str),
            "Property zip": ch["Zip Code"].astype(str),
        }
    )
    ch2 = ch2[ch2["Phone"].str.len() > 5]
    # Basename Decision Maker*.csv drives SMS status normalization in marketing_mapper.process_sms_files
    sms_out = OUT / "Decision Maker.csv"
    ch2.to_csv(sms_out, index=False)

    rep_src = REPO / "Data_ingestion_samples/past_patches/Report-2026-05-04-16-02-00.xlsx"
    usecols = [
        "Close Date",
        "Lead Source",
        "Address (Street)",
        "Address (City)",
    ]
    rep = pd.read_excel(rep_src, usecols=usecols, engine="openpyxl")
    rep = rep.dropna(subset=["Close Date", "Lead Source", "Address (Street)", "Address (City)"])
    rep = rep.head(100)
    street = rep["Address (Street)"].astype(str).str.strip()
    city = rep["Address (City)"].astype(str).str.strip()
    excel_rows = pd.DataFrame(
        {
            # Same layout as attribution GUI: normalized matching uses composite Address string.
            "Address": (street + " " + city).str.strip(),
            "Date Closed": rep["Close Date"],
            "Lead Source": rep["Lead Source"].astype(str),
        }
    )
    hist = pd.DataFrame({"Property address": street, "Property city": city, "Tags": ""})
    excel_path = OUT / "e2e_report_paired_closings.xlsx"
    csv_path = OUT / "e2e_report_paired_history.csv"
    excel_rows.to_excel(excel_path, index=False)
    hist.to_csv(csv_path, index=False)

    print("WROTE", sms_out, "rows", len(ch2))
    print("WROTE", excel_path, "rows", len(excel_rows))
    print("WROTE", csv_path, "rows", len(hist))


if __name__ == "__main__":
    main()
