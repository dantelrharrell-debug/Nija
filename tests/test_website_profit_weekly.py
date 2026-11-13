"""Regression tests for the read-only weekly profit aggregation contract."""
import unittest
from datetime import date, timedelta

from website_profit_weekly import compare_weeks, summarize_week


def fixtures(end, count=14):
    return [
        {"date": (end - timedelta(days=i)).isoformat(), "certified": True,
         "source_reconciled": True, "analytics_consent_verified": True,
         "unique_visitors": 10, "qualified_leads": 2, "waitlist_signups": 1,
         "course_purchases": 1, "attributable_revenue_usd": "20.00",
         "attributable_costs_usd": "5.00"}
        for i in range(count)
    ]


def weekly_counts(end):\n    return {"period_start": (end - timedelta(days=6)).isoformat(), "period_end": end.isoformat(),\n            "certified": True, "source_reconciled": True,\n            "unique_visitors": 70, "qualified_leads": 14, "waitlist_signups": 7}\n\n\nclass WeeklyEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.end = date(2026, 11, 12)

    def test_two_complete_weeks(self):
        result = compare_weeks(fixtures(self.end), self.end, [weekly_counts(self.end), weekly_counts(self.end - timedelta(days=7))])
        for week in result.values():
            self.assertEqual(week["verification_status"], "VERIFIED")
            self.assertEqual(week["unique_visitors"], 70)
            self.assertEqual(week["net_profit_usd"], "105.00")
            self.assertEqual(week["net_profit_per_visitor_usd"], "1.50")
            self.assertTrue(week["target_met"])

    def test_missing_day_is_not_zero(self):
        result = summarize_week(fixtures(self.end, 6), self.end)
        self.assertEqual(result["verification_status"], "UNVERIFIED")
        self.assertIsNone(result["unique_visitors"])

    def test_duplicate_date_is_not_accepted(self):
        rows = fixtures(self.end, 7)
        rows[6] = dict(rows[0])
        self.assertEqual(summarize_week(rows, self.end)["verification_status"], "UNVERIFIED")

    def test_unreconciled_source_fails_closed(self):
        rows = fixtures(self.end, 7)
        rows[0]["source_reconciled"] = False
        self.assertIsNone(summarize_week(rows, self.end)["net_profit_usd"])

    def test_missing_cost_cannot_produce_profit(self):
        rows = fixtures(self.end, 7)
        rows[0]["attributable_costs_usd"] = None
        result = summarize_week(rows, self.end)
        self.assertEqual(result["verification_status"], "PARTIAL")
        self.assertIsNone(result["net_profit_per_visitor_usd"])

    def test_zero_visitors_no_division(self):
        rows = fixtures(self.end, 7)
        for row in rows:
            row["unique_visitors"] = 0
        result = summarize_week(rows, self.end)
        self.assertIsNone(result["net_profit_per_visitor_usd"])
        self.assertIsNone(result["target_met"])

    def test_daily_unique_counts_are_not_summed(self):\n        result = summarize_week(fixtures(self.end, 7), self.end)\n        self.assertIsNone(result["unique_visitors"])\n        self.assertIsNone(result["net_profit_per_visitor_usd"])\n\n    def test_negative_or_fractional_counts_rejected(self):
        rows = fixtures(self.end, 7)
        rows[0]["qualified_leads"] = "-1"
        self.assertEqual(summarize_week(rows, self.end)["verification_status"], "PARTIAL")
        rows[0]["qualified_leads"] = "1.5"
        self.assertEqual(summarize_week(rows, self.end)["verification_status"], "PARTIAL")


if __name__ == "__main__":
    unittest.main()
