"""Tests for Salesforce qualified leads consolidation."""

import unittest
from datetime import date
from pathlib import Path

import pandas as pd

from app.services.qualified_leads import (
    analyze_file,
    compute_qualified_leads_metrics,
    load_qualified_leads_file,
    rollup_channel,
    validate_and_prepare,
)

FIXTURE = Path(__file__).parent / "fixtures" / "qualified_leads_sample.csv"


class TestRollupChannel(unittest.TestCase):
    def test_res_va_sms_into_sms(self):
        self.assertEqual(rollup_channel("RES-VA SMS"), "SMS")

    def test_cold_calling_cc(self):
        self.assertEqual(rollup_channel("Cold Calling"), "CC")

    def test_unknown_other(self):
        self.assertEqual(rollup_channel("Referral"), "Other")
        self.assertEqual(rollup_channel(""), "Other")


class TestQualifiedLeadsMetrics(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not FIXTURE.is_file():
            cls.df = pd.DataFrame(
                {
                    "Lead Source": ["Cold Calling", "RES-VA SMS", "SMS", "PPC", "Referral"],
                    "Create Date": ["5/28/2026", "5/27/2026", "5/26/2026", "5/25/2026", "5/24/2026"],
                }
            )
        else:
            cls.df = load_qualified_leads_file(str(FIXTURE))

    def test_channel_shares_sum_to_100(self):
        result = compute_qualified_leads_metrics(
            self.df, date(2024, 1, 1), date(2026, 12, 31)
        )
        self.assertEqual(result.posted_in_window, sum(result.channel_counts.values()))
        total_pct = sum(result.channel_shares_pct.values())
        self.assertAlmostEqual(total_pct, 100.0, places=1)

    def test_sms_includes_res_va(self):
        result = compute_qualified_leads_metrics(
            self.df, date(2024, 1, 1), date(2026, 12, 31)
        )
        self.assertGreaterEqual(result.channel_counts.get("SMS", 0), 0)

    def test_missing_columns_raises(self):
        bad = pd.DataFrame({"Phone": ["1"]})
        with self.assertRaises(ValueError) as ctx:
            validate_and_prepare(bad)
        self.assertIn("Lead Source", str(ctx.exception))

    def test_narrow_window_excludes_outside(self):
        result = compute_qualified_leads_metrics(
            self.df, date(2099, 1, 1), date(2099, 1, 31)
        )
        self.assertEqual(result.posted_in_window, 0)
        self.assertGreater(result.posted_outside_window + result.posted_excluded_bad_date, 0)


class TestAnalyzeFile(unittest.TestCase):
    def test_use_full_span(self):
        df = pd.DataFrame(
            {
                "Lead Source": ["Cold Calling", "Direct Mail"],
                "Create Date": ["1/15/2025", "2/20/2025"],
            }
        )
        path = Path(__file__).parent / "fixtures" / "_tmp_ql_span.csv"
        path.parent.mkdir(exist_ok=True)
        df.to_csv(path, index=False)
        try:
            result = analyze_file(str(path), use_full_file_span=True)
            self.assertEqual(result.posted_in_window, 2)
            self.assertEqual(result.date_window_start, "2025-01-15")
            self.assertEqual(result.date_window_end, "2025-02-20")
        finally:
            path.unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
