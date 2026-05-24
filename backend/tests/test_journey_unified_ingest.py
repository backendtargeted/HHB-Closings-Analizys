"""Tests for unified journey stitch and tag synthesis."""

import sys
import tempfile
import unittest
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.services.journey_stitch import (  # noqa: E402
    dedupe_closings_for_mapper,
    stitch_journey,
)
from app.services.reisift_tag_builder import (  # noqa: E402
    build_sf_tags_from_crm_rows,
    format_closed_lost_tag,
)
from app.services.unified_crm_adapter import synthesize_crm_rows  # noqa: E402
from app.services.unified_precedence import (  # noqa: E402
    load_precedence_policy,
    parse_source_file_date,
    resolve_duplicate_rows,
)


class TestPrecedence(unittest.TestCase):
    def test_parse_report_filename_date(self):
        dt = parse_source_file_date("Report-2025-04-28-13-12-10.xlsx")
        self.assertIsNotNone(dt)
        self.assertEqual(dt.year, 2025)

    def test_resolve_tina_before_report(self):
        policy = load_precedence_policy()
        rows = [
            {"source_system": "salesforce_report", "source_file": "Report-2025-06-01.xlsx", "stage": "A"},
            {"source_system": "salesforce_tina", "source_file": "New Opportunities Report - Tina.xlsx", "stage": "B"},
        ]
        ordered = resolve_duplicate_rows(rows, policy)
        self.assertEqual(ordered[0]["source_system"], "salesforce_tina")


class TestJourneyStitch(unittest.TestCase):
    def test_stitch_mini_unified(self):
        with tempfile.TemporaryDirectory() as tmp:
            u = Path(tmp)
            (u / "unified").mkdir()
            pd.DataFrame(
                [
                    {
                        "source_file": "Closings - Last view used.xlsx",
                        "source_row_id": 2,
                        "source_system": "podio_closings",
                        "property_address": "10 Main St",
                        "property_city": "Springfield",
                        "property_state": "IL",
                        "property_zip": "62701",
                        "date_closed": "2025-03-15",
                        "phone": "2175550100",
                        "stage": "Closed",
                        "lead_source": "CC",
                        "address_key": "10 main st|springfield|il|62701",
                        "has_valid_close_date": True,
                    }
                ]
            ).to_csv(u / "unified" / "closings.csv", index=False)
            pd.DataFrame(
                [
                    {
                        "source_file": "Opportunities - All Opportunities.xlsx",
                        "source_row_id": 2,
                        "source_system": "podio_opportunities",
                        "stage": "New",
                        "close_date": "",
                        "created_date": "2025-01-10",
                        "lead_source": "SMS",
                        "property_address": "10 Main St",
                        "property_city": "Springfield",
                        "property_state": "IL",
                        "property_zip": "62701",
                        "phone": "2175550100",
                        "address_key": "10 main st|springfield|il|62701",
                    }
                ]
            ).to_csv(u / "unified" / "opportunities.csv", index=False)
            pd.DataFrame(
                [
                    {
                        "source_file": "Seller Leads - All Seller Leads.xlsx",
                        "source_row_id": 2,
                        "source_system": "podio_seller_leads",
                        "entity_type": "seller_lead",
                        "stage": "New",
                        "lead_source": "CC",
                        "property_address": "10 Main St",
                        "property_city": "Springfield",
                        "property_state": "IL",
                        "property_zip": "62701",
                        "close_date": "",
                        "created_date": "2025-01-05",
                        "phone": "2175550100",
                        "address_key": "10 main st|springfield|il|62701",
                    }
                ]
            ).to_csv(u / "unified" / "status_snapshots.csv", index=False)

            events, stats = stitch_journey(u / "unified")
            self.assertGreater(stats["events_total"], 0)
            self.assertEqual(
                events.loc[events["event_kind"] == "closing", "lead_source"].iloc[0],
                "CC",
            )

    def test_dedupe_closings_earliest(self):
        policy = load_precedence_policy()
        df = pd.DataFrame(
            [
                {
                    "address_key": "a|b|c|d",
                    "date_closed": "2025-06-01",
                    "source_system": "salesforce_report",
                    "property_address": "1",
                    "property_city": "X",
                    "property_state": "Y",
                    "property_zip": "1",
                    "phone": "",
                    "stage": "Closed",
                    "has_valid_close_date": True,
                },
                {
                    "address_key": "a|b|c|d",
                    "date_closed": "2025-03-01",
                    "source_system": "podio_closings",
                    "property_address": "1",
                    "property_city": "X",
                    "property_state": "Y",
                    "property_zip": "1",
                    "phone": "",
                    "stage": "Closed",
                    "has_valid_close_date": True,
                },
            ]
        )
        out = dedupe_closings_for_mapper(df, policy)
        self.assertEqual(len(out), 1)
        self.assertEqual(out.iloc[0]["Date Closed"].month, 3)


class TestSfTagBuilder(unittest.TestCase):
    def test_closed_lost_token_option_a(self):
        tag = format_closed_lost_tag("Closed Lost", "2025-04-01")
        self.assertIn("(SF) UPDATED", tag)
        self.assertIn("Closed Lost", tag)

    def test_sf_tags_from_synthetic_crm(self):
        events = pd.DataFrame(
            [
                {
                    "address_key": "k1",
                    "event_kind": "opportunity",
                    "event_subtype": "crm_lead_created",
                    "event_date": "2025-01-10",
                    "stage": "New",
                    "is_tag_eligible": True,
                    "phone": "2175550100",
                    "property_address": "10 Main",
                    "property_city": "Springfield",
                    "property_state": "IL",
                    "property_zip": "62701",
                    "source_file": "f.xlsx",
                    "source_system": "podio_opportunities",
                },
                {
                    "address_key": "k1",
                    "event_kind": "opportunity",
                    "event_subtype": "sf_updated",
                    "event_date": "2025-02-15",
                    "stage": "Follow Up",
                    "is_tag_eligible": True,
                    "phone": "2175550100",
                    "property_address": "10 Main",
                    "property_city": "Springfield",
                    "property_state": "IL",
                    "property_zip": "62701",
                    "source_file": "f.xlsx",
                    "source_system": "podio_opportunities",
                },
            ]
        )
        crm = synthesize_crm_rows(events)
        tags, metrics = build_sf_tags_from_crm_rows(crm)
        self.assertGreater(metrics["sf_tags_created_total"], 0)
        self.assertFalse(tags.empty)


if __name__ == "__main__":
    unittest.main()
