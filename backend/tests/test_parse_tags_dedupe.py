"""parse_tags deduplicates identical logical events (same type/date/channel/label)."""

import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.services.analysis import parse_tags, perform_analysis  # noqa: E402


class TestParseTagsDedupe(unittest.TestCase):
    def test_duplicate_contact_token_counted_once(self):
        s = "(8020) CC - 1/2025,(8020) CC - 1/2025,(8020) SMS - 2/2025"
        p = parse_tags(s)
        contacts = [x for x in p if x["type"] == "contact"]
        self.assertEqual(len(contacts), 2)
        self.assertEqual(sum(1 for x in contacts if x["channel"] == "CC"), 1)
        self.assertEqual(sum(1 for x in contacts if x["channel"] == "SMS"), 1)

    def test_duplicate_closing_token_once(self):
        s = "(CLOSED) 8020 - 3/2025,(CLOSED) 8020 - 3/2025"
        p = parse_tags(s)
        closings = [x for x in p if x["type"] == "closing"]
        self.assertEqual(len(closings), 1)

    def test_perform_analysis_contact_count_not_doubled(self):
        csv_payload = (
            "Property address,Property city,Tags\n"
            '"10 Main St","Springfield",'
            '"(8020) CC - 1/2025,(8020) CC - 1/2025,(8020) SMS - 2/2025,(CLOSED) 8020 - 3/2025"\n'
        )
        with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False, encoding="utf-8") as tmp:
            tmp.write(csv_payload)
            csv_path = tmp.name
        try:
            result = perform_analysis(None, csv_path)
            row = result["results"][0]
            self.assertEqual(row["CC Count"], 1)
            self.assertEqual(row["SMS Count"], 1)
            self.assertEqual(row["Total Contacts"], 2)
        finally:
            if os.path.exists(csv_path):
                os.remove(csv_path)


if __name__ == "__main__":
    unittest.main()
