"""Unit tests for tag parsing and lead lifecycle helpers."""

import sys
import unittest
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.services.analysis import parse_tags  # noqa: E402
from app.services.lifecycle import (  # noqa: E402
    build_events,
    compute_first_touch,
    compute_ordered_path,
    compute_stage_funnel,
    events_before_close,
    get_highest_stage,
)


class TestParseTags(unittest.TestCase):
    def test_sf_updated(self):
        tags = "(SF) UPDATED - Follow Up - 2025-03-15"
        out = parse_tags(tags)
        sf = [x for x in out if x["type"] == "sf_updated"]
        self.assertEqual(len(sf), 1)
        self.assertEqual(sf[0]["label"], "Follow Up")
        self.assertEqual(sf[0]["precision"], "day")
        self.assertTrue(sf[0]["date"].startswith("2025-03-15"))

    def test_sf_status(self):
        tags = "(SF) STATUS - New - 2025-01-10"
        out = parse_tags(tags)
        sf = [x for x in out if x["type"] == "sf_status"]
        self.assertEqual(len(sf), 1)
        self.assertEqual(sf[0]["label"], "New")

    def test_contact_and_list(self):
        tags = "List Purchased 8020 1/2025,(8020) CC - 2/2025"
        out = parse_tags(tags)
        types = {x["type"] for x in out}
        self.assertIn("list_purchase", types)
        self.assertIn("contact", types)


class TestLifecycle(unittest.TestCase):
    def test_build_events_orders_sf_before_contact_same_month(self):
        raw = parse_tags(
            "(8020) SMS - 3/2025,(SF) UPDATED - new - 2025-03-01"
        )
        ev = build_events(raw)
        self.assertGreaterEqual(len(ev), 2)
        # SF day event sorts before same-month contact (March 1 vs Mar 1 month start = tie on day; sf has lower rank)
        types_order = [e.type for e in ev]
        i_sf = types_order.index("sf_updated")
        i_co = types_order.index("contact")
        self.assertLess(i_sf, i_co)

    def test_stage_funnel_and_path(self):
        raw = parse_tags(
            "List Purchased 8020 1/2025,"
            "Skip Traced 2/2025,"
            "(8020) CC - 3/2025,"
            "(SF) UPDATED - new - 2025-03-10"
        )
        ev = build_events(raw)
        closed = pd.Timestamp("2025-06-15")
        stages = compute_stage_funnel(ev, closed)
        self.assertTrue(stages["ACQUIRED"]["reached"])
        self.assertTrue(stages["RESEARCHED"]["reached"])
        self.assertTrue(stages["FIRST_CONTACTED"]["reached"])
        path = compute_ordered_path(ev, closed)
        self.assertIn("LIST", path)
        self.assertIn("SKIP", path)
        self.assertIn("CC", path)
        self.assertTrue(path.endswith("CLOSED"))
        self.assertEqual(get_highest_stage(stages), "ENGAGED")

    def test_events_before_close(self):
        raw = parse_tags("(8020) CC - 1/2025,(8020) SMS - 3/2025")
        ev = build_events(raw)
        closed = pd.Timestamp("2025-06-01")
        before = events_before_close(ev, closed)
        self.assertEqual(len(before), 2)
        self.assertEqual({e.type for e in before}, {"contact"})

    def test_first_touch(self):
        raw = parse_tags("List Purchased 8020 1/2025,(8020) SMS - 2/2025,(SF) UPDATED - follow up - 2025-02-15")
        ev = build_events(raw)
        closed = pd.Timestamp("2025-12-01")
        ft = compute_first_touch(ev, closed)
        self.assertEqual(ft["channel"], "SMS")
        self.assertIsNotNone(ft["days_list_to_first_touch"])


if __name__ == "__main__":
    unittest.main()
