"""Offline end-to-end test of isolated TIQ72 test-mode commerce.

Does not connect a production HTTP route or initiate a Stripe transaction.
"""
import json
import os
import sqlite3
import unittest
from unittest.mock import patch
from tiq72_commerce_store import Tiq72Store, CommerceDenied
from tiq72_test_commerce_orchestrator import Tiq72TestCommerce

class Obj(dict):
    __getattr__ = dict.__getitem__

class FakeStripe:
    def __init__(self):
        self.session = None
        self.checkout = Obj(Session=Obj(create=self.create, retrieve=self.retrieve,
                                         list_line_items=self.items))
        self.Price = Obj(retrieve=self.retrieve_price)
    def retrieve_price(self, price_id):
        return {"id":price_id,"livemode":False,"active":True,"type":"one_time",
                "currency":"usd","unit_amount":100,"product":"prod_test_1"}
    def create(self, **kw):
        self.session = dict(id="cs_test_abc", livemode=False, mode="payment",
            payment_status="paid", status="complete", currency="usd", amount_total=100,
            client_reference_id=kw["client_reference_id"],
            metadata=kw["metadata"], payment_intent={"id":"pi_test","status":"succeeded",
            "amount_received":100}, url="https://checkout.stripe.com/test")
        return self.session
    def retrieve(self, *args, **kw):
        return self.session
    def items(self, *args, **kw):
        return {"data":[{"quantity":1,"price":{"id":"price_test_1","product":"prod_test_1"}}]}

class CommerceIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(":memory:")
        self.store = Tiq72Store(self.db)
        self.stripe = FakeStripe()
        self.service = Tiq72TestCommerce(self.store, self.stripe, "whsec_test")
        self.env = patch.dict(os.environ, {"STRIPE_TEST_SECRET_KEY":"sk_test_fake",
            "TIQ72_TEST_RETURN_ORIGIN":"https://example.org",
            "TIQ72_STRIPE_TEST_PRICE_ID":"price_test_1",
            "TIQ72_STRIPE_TEST_PRODUCT_ID":"prod_test_1",
            "NIJA_GAME_REPORTS_ENABLED":"false",
            "NIJA_GAME_BROWSER_CHECKOUT_ENABLED":"false"})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.addCleanup(self.db.close)

    def test_purchase_report_and_reversal(self):
        run={"challenges":[[{"action":"wait","stop":None} for _ in range(12)] for _ in range(6)]}
        with patch("tiq72_test_commerce_orchestrator.verify_test_webhook") as verify:
            result=self.service.start_checkout(owner_id="adult-1",adult_attested=True,
                canonical_run=run,authoritative_score={"score":70},
                success_url="https://example.org/success",cancel_url="https://example.org/cancel")
            rid=result["reservation_id"]
            verify.return_value={"id":"evt_paid","livemode":False,
                "type":"checkout.session.completed",
                "data":{"object":{"id":"cs_test_abc","metadata":{"tiq72_reservation_id":rid}}}}
            self.assertTrue(self.service.accept_signed_checkout(raw_body=b"signed",signature="sig"))
            self.assertFalse(self.service.accept_signed_checkout(raw_body=b"signed",signature="sig"))
            report=self.service.fulfill_report(owner_id="adult-1",reservation_id=rid,
                                               report={"score":70})
            self.assertEqual(report,{"score":70})
            with self.assertRaisesRegex(CommerceDenied,"reservation_not_owned"):
                self.service.fulfill_report(owner_id="other",reservation_id=rid,report={"score":70})
            self.store.record_verified_event("evt_refund","charge.refunded",rid,
                                             "cs_test_abc",verified_reversal=True)
            with self.assertRaisesRegex(CommerceDenied,"report_unavailable"):
                self.store.get_report(rid,"adult-1")
            self.assertFalse(self.store.record_verified_event("evt_paid",
                "checkout.session.completed",rid,"cs_test_abc",verified_paid=True))
            with self.assertRaisesRegex(CommerceDenied,"report_unavailable"):
                self.store.get_report(rid,"adult-1")

    def test_report_denied_before_verified_payment(self):
        run={"challenges":[[{"action":"wait","stop":None} for _ in range(12)] for _ in range(6)]}
        result=self.service.start_checkout(owner_id="adult-1",adult_attested=True,
            canonical_run=run,authoritative_score={"score":70},
            success_url="https://example.org/success",cancel_url="https://example.org/cancel")
        with self.assertRaisesRegex(CommerceDenied,"active_entitlement_required"):
            self.service.fulfill_report(owner_id="adult-1",
                reservation_id=result["reservation_id"],report={"score":70})

    def test_unpaid_checkout_cannot_grant_entitlement(self):
        run={"challenges":[[{"action":"wait","stop":None} for _ in range(12)] for _ in range(6)]}
        result=self.service.start_checkout(owner_id="adult-1",adult_attested=True,
            canonical_run=run,authoritative_score={"score":70},
            success_url="https://example.org/success",cancel_url="https://example.org/cancel")
        self.stripe.session["payment_status"]="unpaid"
        with patch("tiq72_test_commerce_orchestrator.verify_test_webhook") as verify:
            verify.return_value={"id":"evt_unpaid","livemode":False,
                "type":"checkout.session.completed",
                "data":{"object":{"id":"cs_test_abc","metadata":{
                    "tiq72_reservation_id":result["reservation_id"]}}}}
            with self.assertRaisesRegex(Exception,"checkout_identity_mismatch"):
                self.service.accept_signed_checkout(raw_body=b"signed",signature="sig")
        with self.assertRaisesRegex(CommerceDenied,"report_unavailable"):
            self.store.get_report(result["reservation_id"],"adult-1")

    def test_requires_adult_attestation(self):
        run={"challenges":[[{"action":"wait","stop":None} for _ in range(12)] for _ in range(6)]}
        for attestation in (False, None, 1, "true"):
            with self.subTest(attestation=attestation):
                with self.assertRaisesRegex(CommerceDenied,"adult_identity_required"):
                    self.service.start_checkout(owner_id="adult-1",adult_attested=attestation,
                        canonical_run=run,authoritative_score={"score":70},
                        success_url="https://example.org/success",cancel_url="https://example.org/cancel")
                self.assertEqual(self.db.execute("SELECT COUNT(*) FROM tiq72_runs").fetchone()[0], 0)
                self.assertEqual(self.db.execute("SELECT COUNT(*) FROM tiq72_reservations").fetchone()[0], 0)
        self.assertIsNone(self.stripe.session)

if __name__=="__main__": unittest.main()
