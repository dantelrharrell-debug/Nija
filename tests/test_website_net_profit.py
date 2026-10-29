import unittest
from website_net_profit import net_profit_report


class NetProfitReportTests(unittest.TestCase):
    @staticmethod
    def revenue():
        return [
            {"type": "visit", "event_id": "v1", "visitor_id": "v1", "period": "2026-10"},
            {"type": "visit", "event_id": "v2", "visitor_id": "v2", "period": "2026-10"},
            {"type": "qualified_lead", "event_id": "l1", "visitor_id": "v1", "lead_id": "l1", "period": "2026-10"},
            {"type": "revenue", "event_id": "p1", "source": "stripe", "verified": True, "amount_usd": "10.00", "period": "2026-10"},
            {"type": "refund", "event_id": "r1", "source": "stripe", "verified": True, "amount_usd": "2.00", "period": "2026-10"},
        ]

    @staticmethod
    def costs():
        return [
            {"event_id": "c1", "category": "advertising", "verified": True, "amount_usd": "3.00", "period": "2026-10"},
            {"event_id": "c2", "category": "payment_processing", "verified": True, "amount_usd": "1.00", "period": "2026-10"},
        ]

    def test_net_after_refunds_and_costs(self):
        result = net_profit_report(self.revenue(), self.costs(), reporting_period="2026-10", revenue_complete=True, costs_complete=True)
        self.assertEqual(result["net_verified_revenue_usd"], "8.00")
        self.assertEqual(result["verified_costs_usd"], "4.00")
        self.assertEqual(result["net_profit_usd"], "4.00")
        self.assertEqual(result["net_profit_per_visitor_usd"], "2.00")
        self.assertEqual(result["net_profit_per_qualified_lead_usd"], "4.00")
        self.assertIs(result["visitor_target_met"], True)

    def test_cost_evidence_incomplete_keeps_profit_unknown(self):
        result = net_profit_report(self.revenue(), self.costs(), reporting_period="2026-10")
        self.assertEqual(result["status"], "incomplete_cost_or_revenue_evidence")
        self.assertIsNone(result["net_profit_per_visitor_usd"])
        self.assertIsNone(result["visitor_target_met"])

    def test_unverified_cost_blocks_certification(self):
        costs = self.costs() + [{"event_id": "bad", "category": "hosting", "verified": False, "period": "2026-10", "amount_usd": "1.00"}]
        result = net_profit_report(self.revenue(), costs, reporting_period="2026-10", revenue_complete=True, costs_complete=True)
        self.assertEqual(result["rejected_cost_events"], 1)
        self.assertIsNone(result["net_profit_usd"])

    def test_deduplicates_cost_evidence(self):
        costs = self.costs()
        result = net_profit_report(self.revenue(), costs + [costs[0]], reporting_period="2026-10", revenue_complete=True, costs_complete=True)
        self.assertEqual(result["verified_costs_usd"], "4.00")

    def test_rejects_fractional_cents(self):
        costs = [{"event_id": "bad", "category": "advertising", "verified": True, "amount_usd": "1.005", "period": "2026-10"}]
        result = net_profit_report(self.revenue(), costs, reporting_period="2026-10", revenue_complete=True, costs_complete=True)
        self.assertIsNone(result["net_profit_usd"])
        self.assertEqual(result["rejected_cost_events"], 1)

    def test_mismatched_period_refuses_certification(self):
        revenue = self.revenue()
        revenue[0]["period"] = "2026-09"
        result = net_profit_report(revenue, self.costs(), reporting_period="2026-10", revenue_complete=True, costs_complete=True)
        self.assertEqual(result["rejected_period_events"], 1)
        self.assertIsNone(result["net_profit_per_visitor_usd"])

    def test_revenue_completeness_required(self):
        result = net_profit_report(self.revenue(), self.costs(), reporting_period="2026-10", costs_complete=True)
        self.assertEqual(result["status"], "incomplete_cost_or_revenue_evidence")


if __name__ == "__main__":
    unittest.main()
