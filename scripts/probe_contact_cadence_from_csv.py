"""
CLI probe: aggregate inter-touch gap stats from a REISift-style contact CSV.

Uses Tags + Date Closed (when present) via summarize_cadence_before_close / summarize_tag_cadence.

Example:
  python scripts/probe_contact_cadence_from_csv.py \\
    --csv Data_ingestion_samples/Weekly_and_monthly/some_export.csv \\
    --limit 500
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "backend"))

from app.services.cadence_from_history import (  # noqa: E402
    summarize_cadence_before_close,
    summarize_tag_cadence,
)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", type=Path, required=True)
    ap.add_argument("--limit", type=int, default=0, help="0 = all rows")
    ap.add_argument(
        "--mode",
        choices=("before_close", "full"),
        default="before_close",
        help="before_close needs Date Closed column on CSV",
    )
    args = ap.parse_args()

    df = pd.read_csv(args.csv, low_memory=False)
    if "Tags" not in df.columns:
        raise SystemExit("CSV must have a Tags column")

    lim = args.limit or len(df)
    df = df.head(lim)

    all_gaps: list[int] = []
    used = 0
    for _, row in df.iterrows():
        tags = row.get("Tags", "")
        if pd.isna(tags) or not str(tags).strip():
            continue
        if args.mode == "before_close":
            dc = row.get("Date Closed") or row.get("date closed")
            if dc is None or (isinstance(dc, float) and pd.isna(dc)):
                s = summarize_tag_cadence(str(tags))
            else:
                s = summarize_cadence_before_close(str(tags), str(dc))
                if s.get("error"):
                    s = summarize_tag_cadence(str(tags))
        else:
            s = summarize_tag_cadence(str(tags))
        gaps = s.get("inter_event_gaps_days") or []
        all_gaps.extend(gaps)
        used += 1

    out = {
        "csv": str(args.csv.resolve()),
        "rows_scanned": int(len(df)),
        "rows_with_tags": used,
        "mode": args.mode,
        "total_inter_event_gaps": len(all_gaps),
        "gap_median": float(statistics.median(all_gaps)) if all_gaps else None,
        "gap_mean": float(statistics.mean(all_gaps)) if all_gaps else None,
        "note": "8020 tags are month-granular; SF day tags tighten gaps. Not Golden Loop output.",
    }
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
