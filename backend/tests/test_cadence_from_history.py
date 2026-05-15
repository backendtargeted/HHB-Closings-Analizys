"""Cadence summaries from Tags (experimental; month-granular for 8020 tags)."""

import os
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.services.cadence_from_history import (  # noqa: E402
    inter_event_day_gaps,
    summarize_cadence_before_close,
    summarize_tag_cadence,
)
from app.services.analysis import parse_tags  # noqa: E402
from app.services.lifecycle import build_events  # noqa: E402


class TestCadenceFromHistory(unittest.TestCase):
    def test_inter_event_gaps_monthly_contacts(self):
        tags = "(8020) CC - 1/2025,(8020) SMS - 2/2025,(8020) CC - 4/2025"
        ev = build_events(parse_tags(tags))
        gaps = inter_event_day_gaps(ev)
        self.assertEqual(len(gaps), 2)
        self.assertEqual(gaps[0], 31)  # Jan 1 -> Feb 1
        self.assertEqual(gaps[1], 59)  # Feb 1 -> Apr 1

    def test_summarize_tag_cadence_shape(self):
        tags = "(8020) CC - 1/2025,(8020) SMS - 2/2025"
        s = summarize_tag_cadence(tags)
        self.assertEqual(s["n_events"], 2)
        self.assertEqual(s["gap_summary"]["n_gaps"], 1)
        self.assertEqual(s["gap_summary"]["median_days"], 31)

    def test_summarize_before_close_excludes_closing_same_month(self):
        tags = (
            "(8020) CC - 1/2025,(8020) SMS - 2/2025,"
            "(SF) STATUS - converted - 2025-02-15,(CLOSED) 8020 - 3/2025"
        )
        s = summarize_cadence_before_close(tags, "2025-03-01")
        self.assertNotIn("error", s)
        types = s["events_by_type"]
        self.assertIn("contact", types)
        self.assertEqual(types.get("sf_status", 0), 1)


if __name__ == "__main__":
    unittest.main()
