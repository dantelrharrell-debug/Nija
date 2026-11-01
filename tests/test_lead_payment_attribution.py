import unittest
from lead_payment_attribution import reconcile_stripe_charges

def charge(id, amount=5000, **kw):
    return dict(id=id, amount=amount, amount_refunded=0, currency="usd",
                livemode=True, status="succeeded", paid=True,
                customer="cus_1", **kw)

class LeadPaymentAttributionTests(unittest.TestCase):
    def run_report(self, charges, mapping=None, **kw):
        return reconcile_stripe_charges(charges, mapping or {"cus_1":"lead_1"},
                 mapping_verified=True, charges_complete=True, **kw)

    def test_paid_dedup_and_refund(self):
        c=charge("ch_1")
        c["amount_refunded"]=1000
        r=self.run_report([c,c])
        self.assertEqual(r["net_collected_usd"],"40.00")
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

if __name__=="__main__":
    unittest.main()
