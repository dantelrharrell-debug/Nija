import unittest
from datetime import datetime, timezone
from stripe_attribution_evidence_bridge import stripe_attributed_events
from website_revenue_attribution import summarize


def timestamp(date):
    return int(datetime.fromisoformat(date).replace(tzinfo=timezone.utc).timestamp())


def charge(id="ch_1", **updates):
    refunded = updates.get("amount_refunded", 1000)
    refunds = updates.get("refunds")
    if refunds is None:
        refund_data = ([{
            "id": "re_" + id, "amount": refunded, "currency": "usd",
            "status": "succeeded", "created": timestamp("2026-10-15"),
        }] if refunded else [])
        refunds = {"data": refund_data, "has_more": False}
    data = dict(id=id, amount=5000, amount_refunded=1000, currency="usd",
                livemode=True, status="succeeded", paid=True, captured=True,
                customer="cus_1", created=timestamp("2026-10-01"), refunds=refunds)
    data.update(updates)
    return data


class BridgeTests(unittest.TestCase):
    def report(self, charges, period="2026-10", **kwargs):
        return stripe_attributed_events(charges, {"cus_1": "lead_1"},
                                        period=period, mapping_verified=True,
                                        charges_complete=True, refunds_complete=True,
                                        **kwargs)

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

    def test_refund_is_reported_in_its_own_period(self):
        refund = {
            "id": "re_november", "amount": 1000, "currency": "usd",
            "status": "succeeded", "created": timestamp("2026-11-02"),
        }
        result = self.report(
            [charge(refunds={"data": [refund], "has_more": False})],
            period="2026-11",
        )
        self.assertEqual(result["status"], "verified")
        self.assertEqual(len(result["revenue_events"]), 1)
        event = result["revenue_events"][0]
        self.assertEqual(event["type"], "refund")
        self.assertEqual(event["amount_usd"], "10.00")
        self.assertEqual(event["provider_adjustment_id"], "re_november")
        october = self.report(
            [charge(refunds={"data": [refund], "has_more": False})],
            period="2026-10",
        )
        self.assertEqual(
            [(event["type"], event["amount_usd"]) for event in october["revenue_events"]],
            [("revenue", "50.00")],
        )

    def test_missing_or_incomplete_period_evidence_fails_closed(self):
        missing_charge_timestamp = charge()
        del missing_charge_timestamp["created"]
        incomplete_refunds = charge(refunds={"data": [], "has_more": True})
        missing_adjustment_id = charge(refunds={
            "data": [{
                "amount": 1000, "currency": "usd", "status": "succeeded",
                "created": timestamp("2026-10-15"),
            }],
            "has_more": False,
        })
        for item in (missing_charge_timestamp, incomplete_refunds, missing_adjustment_id):
            with self.subTest(charge=item):
                result = self.report([item])
                self.assertEqual(result["status"], "unverified")
                self.assertEqual(result["revenue_events"], [])
        missing_coverage = stripe_attributed_events(
            [charge()], {"cus_1": "lead_1"}, period="2026-10",
            mapping_verified=True, charges_complete=True,
        )
        self.assertEqual(missing_coverage["status"], "unverified")
        self.assertEqual(missing_coverage["revenue_events"], [])


if __name__ == "__main__":
    unittest.main()
