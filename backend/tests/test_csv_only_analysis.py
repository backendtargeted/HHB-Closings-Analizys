"""Targeted tests for CSV-only analysis flow."""

import io
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.main import app  # noqa: E402
from app.services.analysis import perform_analysis  # noqa: E402
from app.utils.file_handler import delete_file  # noqa: E402


class TestCsvOnlyAnalysis(unittest.TestCase):
    def test_perform_analysis_without_closings_workbook_uses_closed_tag(self):
        csv_payload = (
            "Property address,Property city,Tags\n"
            '"10 Main St","Springfield","(8020) CC - 1/2025,(CLOSED) 8020 - 3/2025"\n'
        )
        with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False, encoding="utf-8") as tmp:
            tmp.write(csv_payload)
            csv_path = tmp.name

        try:
            result = perform_analysis(None, csv_path)
            self.assertEqual(result["total_deals"], 1)
            self.assertEqual(result["matched_count"], 1)
            self.assertEqual(len(result["results"]), 1)
            self.assertTrue(str(result["results"][0]["Date Closed"]).startswith("2025-03-01"))
            self.assertTrue(result["results"][0]["Match Found"])
        finally:
            if os.path.exists(csv_path):
                os.remove(csv_path)

    def test_upload_accepts_csv_only(self):
        client = app.test_client()
        response = client.post(
            "/api/upload",
            data={
                "csv_file": (
                    io.BytesIO(b"Property address,Property city,Tags\n10 Main St,Springfield,\n"),
                    "contacts.csv",
                )
            },
            content_type="multipart/form-data",
        )
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertEqual(data["closings_path"], None)
        self.assertEqual(data["excel_path"], None)
        self.assertIn("csv_path", data)
        delete_file(data["csv_path"])

    def test_analyze_requires_csv_path_only(self):
        client = app.test_client()
        response = client.post("/api/analyze", json={})
        self.assertEqual(response.status_code, 400)
        self.assertIn("csv_path is required", response.get_json()["detail"])


if __name__ == "__main__":
    unittest.main()
