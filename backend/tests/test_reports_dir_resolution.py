"""Tests for unified REPORTS_DIR resolution."""

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from app.services import report_store


class TestReportsDirResolution(unittest.TestCase):
    def test_resolve_uses_writable_env_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.dict(os.environ, {"REPORTS_DIR": tmp, "ENV": "development"}, clear=False):
                resolved = report_store.resolve_reports_dir()
                self.assertEqual(resolved, Path(tmp))

    def test_production_raises_when_env_path_not_writable(self):
        with tempfile.TemporaryDirectory() as tmp:
            blocked = Path(tmp) / "blocked"
            blocked.mkdir()
            with mock.patch.dict(
                os.environ,
                {"REPORTS_DIR": str(blocked), "ENV": "production"},
                clear=False,
            ):
                with mock.patch.object(report_store, "_probe_writable", return_value=(False, "denied")):
                    with self.assertRaises(report_store.ReportsDirectoryError):
                        report_store.resolve_reports_dir(allow_temp_fallback=False)

    def test_diagnostics_reports_degraded_when_not_writable(self):
        with mock.patch.object(
            report_store,
            "get_reports_dir",
            side_effect=report_store.ReportsDirectoryError("no dir"),
        ):
            payload = report_store.reports_dir_diagnostics()
            self.assertEqual(payload["status"], "degraded")
            self.assertIsNone(payload["resolved_path"])


if __name__ == "__main__":
    unittest.main()
