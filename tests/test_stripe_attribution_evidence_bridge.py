import unittest
from stripe_attribution_evidence_bridge import stripe_attributed_events
from website_revenue_attribution import summarize


def charge(id="ch_1", **updates):
    data = dict(id=id, amount=5000, amount_refunded=1000, currency="usd",
                livemode=True, status="succeeded", paid=True, captured=True,
                customer="cus_1")
    data.update(updates)
    return data


class BridgeTests(unittest.TestCase):
    def report(self, charges, **kwargs):
        return stripe_attributed_events(charges, {"cus_1": "lead_1"},
                                        period="2026-10", mapping_verified=True,
                                        charges_complete=True, **kwargs)

    def test_revenue_refund_and_deduplication(self):
        result = self.report([charge(), charge()])
        self.assertEqual(result["status"], "verified")
        summary = summarize(result["revenue_events"])
        self.assertEqual(summary["gross_verified_revenue_usd"], "50.00")
        self.assertEqual(summary["verified_refunds_usd"], "10.00")
        self.assertEqual(summary["net_verified_revenue_usd"], "40.00")

    def test_missing_mapping_fails_closed(self):
        result = stripe_attributed_events([charge()], {}, period="2026-10",
                                           mapping_verified=True, charges_complete=True)
        self.assertEqual(result["status"], "unverified")
        self.assertEqual(result["revenue_events"], [])

    def test_conflict_fails_closed(self):
        result = self.report([charge(), charge(amount=9000)])
        self.assertEqual(result["status"], "unverified")
        self.assertEqual(result["revenue_events"], [])

    def test_failed_and_uncaptured_not_revenue(self):
        result = self.report([charge(status="failed", paid=False),
                              charge("ch_2", captured=False)])
        self.assertEqual(result["revenue_events"], [])

    def test_fully_refunded_is_not_profit(self):
        result = self.report([charge(amount_refunded=5000)])
        self.assertEqual(summarize(result["revenue_events"])["net_verified_revenue_usd"], "0.00")


if __name__ == "__main__":
    unittest.main()
