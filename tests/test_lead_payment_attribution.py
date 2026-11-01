import unittest
from lead_payment_attribution import reconcile_stripe_charges

def charge(id, amount=5000, **kw):
    result = dict(id=id, amount=amount, amount_refunded=0, currency="usd",
                  livemode=True, status="succeeded", paid=True, captured=True,
                  customer="cus_1")
    result.update(kw)
    return result

class LeadPaymentAttributionTests(unittest.TestCase):
    def run_report(self, charges, mapping=None, **kw):
        return reconcile_stripe_charges(charges, mapping or {"cus_1":"lead_1"},
                 mapping_verified=True, charges_complete=True, **kw)

    def test_paid_dedup_and_refund(self):
        c=charge("ch_1")
        c["amount_refunded"]=1000
        r=self.run_report([c,c])
        self.assertEqual(r["net_collected_usd"],"40.00")
        self.assertEqual(r["paid_charges"],1)
        self.assertEqual(r["refunded_usd"],"10.00")
        self.assertEqual(r["attributed_paid_leads"],1)
        self.assertEqual(r["duplicate_charge_ids"],1)

    def test_failed_and_trial_do_not_count(self):
        c=charge("ch_fail")
        c["status"]="failed"; c["paid"]=False
        r=self.run_report([c])
        self.assertEqual(r["paid_charges"],0)
        self.assertEqual(r["net_collected_usd"],"0.00")

    def test_missing_mapping_never_claims_attributed_revenue(self):
        r=self.run_report([charge("ch_1")],{"other":"lead_2"})
        self.assertIsNone(r["net_collected_usd"])
        self.assertEqual(r["unattributed_paid_charges"],1)

    def test_conflicting_duplicate_fails_closed(self):
        r=self.run_report([charge("ch_1"),charge("ch_1",amount=7000)])
        self.assertEqual(r["status"],"unverified")
        self.assertIsNone(r["net_collected_usd"])

    def test_incomplete_source_fails_closed(self):
        r=reconcile_stripe_charges([charge("ch_1")],{"cus_1":"lead_1"},
                 mapping_verified=True,charges_complete=False)
        self.assertIsNone(r["net_collected_usd"])

    def test_ambiguous_mapping(self):
        r=self.run_report([charge("ch_1")],{"cus_1":["lead_1","lead_2"]})
        self.assertEqual(r["ambiguous_mappings"],1)
        self.assertIsNone(r["net_collected_usd"])

    def test_invalid_amount(self):
        c=charge("ch_1")
        c["amount_refunded"]=6000
        r=self.run_report([c])
        self.assertEqual(r["status"],"unverified")

    def test_missing_status_paid_or_refund_evidence_fails_closed(self):
        for field in ("status", "paid", "amount_refunded"):
            with self.subTest(field=field):
                c=charge("ch_1")
                del c[field]
                r=self.run_report([c])
                self.assertEqual(r["status"],"unverified")
                self.assertIsNone(r["net_collected_usd"])

    def test_uncaptured_or_missing_capture_evidence_does_not_count(self):
        uncaptured = self.run_report([charge("ch_uncaptured", captured=False)])
        self.assertEqual(uncaptured["paid_charges"],0)
        self.assertEqual(uncaptured["attributed_paid_leads"],0)
        self.assertEqual(uncaptured["net_collected_usd"],"0.00")

        for captured in (None, "true"):
            with self.subTest(captured=captured):
                r=self.run_report([charge("ch_invalid", captured=captured)])
                self.assertEqual(r["status"],"unverified")
                self.assertIsNone(r["paid_charges"])
                self.assertIsNone(r["net_collected_usd"])

        missing = charge("ch_missing_capture")
        del missing["captured"]
        r=self.run_report([missing])
        self.assertEqual(r["status"],"unverified")
        self.assertIsNone(r["net_collected_usd"])

    def test_zero_net_charges_reconcile_refunds_without_attribution(self):
        zero_amount = charge("ch_zero", amount=0)
        fully_refunded = charge("ch_refunded", amount_refunded=5000)
        r=self.run_report([zero_amount, fully_refunded])
        self.assertEqual(r["paid_charges"],0)
        self.assertEqual(r["refunded_usd"],"50.00")
        self.assertEqual(r["net_collected_usd"],"0.00")
        self.assertEqual(r["attributed_paid_leads"],0)
        self.assertEqual(r["unattributed_paid_charges"],0)

if __name__=="__main__":
    unittest.main()
