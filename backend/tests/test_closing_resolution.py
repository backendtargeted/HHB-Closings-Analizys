"""Tests for close vs under-contract milestone resolution."""

import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.services.analysis import derive_closed_deals_from_csv  # noqa: E402
from app.services.closing_resolution import (  # noqa: E402
    is_closing_report_stage,
    resolve_milestones_from_parsed,
)
from app.services.analysis import parse_tags  # noqa: E402
from app.services.marketing_mapper import process_closings_for_tags  # noqa: E402

import pandas as pd  # noqa: E402


class TestClosingReportStage(unittest.TestCase):
    def test_closed_lost_excluded(self):
        self.assertFalse(is_closing_report_stage("Closed Lost"))
        self.assertFalse(is_closing_report_stage("closed lost"))

    def test_closing_stages_included(self):
        for stage in ("Closed", "Executed", "Closed Won", "Funded"):
            self.assertTrue(is_closing_report_stage(stage), stage)

    def test_pipeline_stages_excluded(self):
        self.assertFalse(is_closing_report_stage("Follow-up"))


class TestResolveMilestones(unittest.TestCase):
    def test_closed_tag_only_not_sf_converted(self):
        tags = "(8020) CC - 1/2025,(CLOSED) 8020 - 3/2025"
        parsed = parse_tags(tags)
        resolved = resolve_milestones_from_parsed(parsed, legacy_mode=False)
        self.assertIsNotNone(resolved.date_closed)
        self.assertEqual(resolved.close_source, "closed_tag")
        self.assertFalse(resolved.has_contract_sf_tag)

    def test_sf_converted_alone_not_closed_without_legacy(self):
        tags = "(SF) UPDATED - converted - 2025-01-15"
        parsed = parse_tags(tags)
        resolved = resolve_milestones_from_parsed(parsed, legacy_mode=False)
        self.assertIsNone(resolved.date_closed)
        self.assertIsNotNone(resolved.date_under_contract)
        self.assertTrue(resolved.has_contract_sf_tag)

    def test_earliest_close_when_workbook_and_tag_disagree(self):
        tags = "(CLOSED) 8020 - 6/2025"
        parsed = parse_tags(tags)
        from datetime import datetime

        wb = datetime(2025, 3, 15)
        resolved = resolve_milestones_from_parsed(
            parsed, legacy_mode=False, workbook_close=wb
        )
        self.assertEqual(resolved.date_closed, wb)
        self.assertEqual(resolved.close_source, "earliest_workbook_and_tag")

    def test_legacy_min_includes_sf_converted(self):
        tags = "(SF) UPDATED - under contract - 2025-01-15,(CLOSED) 8020 - 6/2025"
        parsed = parse_tags(tags)
        resolved = resolve_milestones_from_parsed(parsed, legacy_mode=True)
        self.assertEqual(resolved.date_closed.year, 2025)
        self.assertEqual(resolved.date_closed.month, 1)
        self.assertEqual(resolved.close_source, "legacy_min")


class TestDeriveClosedDealsCsv(unittest.TestCase):
    def test_converted_only_excluded_by_default(self):
        csv_payload = (
            "Property address,Property city,Tags\n"
            '"10 Main St","Springfield","(SF) UPDATED - converted - 2025-02-01"\n'
        )
        df = pd.read_csv(pd.io.common.StringIO(csv_payload))
        deals = derive_closed_deals_from_csv(df)
        self.assertEqual(len(deals), 0)

    def test_closed_tag_included(self):
        csv_payload = (
            "Property address,Property city,Tags\n"
            '"10 Main St","Springfield","(CLOSED) 8020 - 3/2025"\n'
        )
        df = pd.read_csv(pd.io.common.StringIO(csv_payload))
        deals = derive_closed_deals_from_csv(df)
        self.assertEqual(len(deals), 1)
        self.assertTrue(deals.iloc[0]["Has_CLOSED_Tag"])

    def test_legacy_env_restores_converted_as_close(self):
        csv_payload = (
            "Property address,Property city,Tags\n"
            '"10 Main St","Springfield","(SF) UPDATED - converted - 2025-02-01"\n'
        )
        prev = os.environ.get("USE_LEGACY_MIN_CLOSE_DATE")
        os.environ["USE_LEGACY_MIN_CLOSE_DATE"] = "1"
        try:
            df = pd.read_csv(pd.io.common.StringIO(csv_payload))
            deals = derive_closed_deals_from_csv(df)
            self.assertEqual(len(deals), 1)
        finally:
            if prev is None:
                os.environ.pop("USE_LEGACY_MIN_CLOSE_DATE", None)
            else:
                os.environ["USE_LEGACY_MIN_CLOSE_DATE"] = prev


class TestProcessClosingsStageFilter(unittest.TestCase):
    def test_stage_filter_excludes_closed_lost(self):
        df = pd.DataFrame(
            {
                "Address": ["1 A St", "2 B St", "3 C St"],
                "City": ["X", "Y", "Z"],
                "Close Date": ["2025-03-01", "2025-04-01", "2025-05-01"],
                "Stage": ["Closed", "Closed Lost", "Executed"],
            }
        )
        with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as tmp:
            path = tmp.name
        try:
            df.to_excel(path, index=False)
            out = process_closings_for_tags(path)
            self.assertEqual(len(out), 2)
        finally:
            os.remove(path)


if __name__ == "__main__":
    unittest.main()
