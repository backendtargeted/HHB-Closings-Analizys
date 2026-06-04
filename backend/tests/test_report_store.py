"""Tests for unified report persistence."""

import json
import tempfile
import unittest
from pathlib import Path

from app.services.report_store import (
    REPORT_TYPE_QUALIFIED_LEADS,
    list_report_index,
    load_qualified_leads_report,
    save_qualified_leads_report,
)


class TestReportStore(unittest.TestCase):
    def test_save_and_list_qualified_leads(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            save_qualified_leads_report(
                "job-1",
                metrics={"posted_in_window": 100, "rows_ingested": 100},
                use_full_file_span=True,
                rows=[{"lead_source_raw": "Cold Calling", "reporting_channel": "CC"}],
                created_at="2026-05-29T12:00:00+00:00",
                reports_dir=root,
            )
            items = list_report_index(root)
            self.assertEqual(len(items), 1)
            self.assertEqual(items[0]["report_type"], REPORT_TYPE_QUALIFIED_LEADS)
            self.assertIn("100", items[0]["summary"])
            loaded = load_qualified_leads_report("job-1", root)
            self.assertIsNotNone(loaded)
            self.assertEqual(len(loaded["rows"]), 1)


if __name__ == "__main__":
    unittest.main()
