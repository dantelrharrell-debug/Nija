"""Offline tests for signed test-mode refund and dispute reconciliation."""
import unittest
from unittest.mock import patch
from tiq72_test_commerce_orchestrator import Tiq72TestCommerce
from tiq72_stripe_test_verification import StripeVerificationError

class Obj(dict):
    __getattr__ = dict.__getitem__

class DB:
    def execute(self, *args):
        return Obj(fetchall=lambda: [("reservation-1", "cs_test_1")])

class Store:
    db = DB()
    def __init__(self): self.events = []
    def record_verified_event(self, *args, **kwargs):
        self.events.append((args, kwargs))
        return True

def make_client(refunded=True, amount_refunded=100):
    charge = {"id":"ch_1","livemode":False,"refunded":refunded,
              "amount_refunded":amount_refunded,"payment_intent":"pi_1"}
    session = {"livemode":False,"client_reference_id":"reservation-1",
               "payment_intent":{"id":"pi_1"}}
    return Obj(Charge=Obj(retrieve=lambda _:charge),
               Dispute=Obj(retrieve=lambda _:{"id":"dp_1","charge":"ch_1","livemode":False}),
               checkout=Obj(Session=Obj(retrieve=lambda *a,**k:session)))

class ReversalTests(unittest.TestCase):
    def run_event(self, event, client):
        store = Store()
        service = Tiq72TestCommerce(store, client, "whsec_test")
        with patch("tiq72_test_commerce_orchestrator.assert_test_mode_configuration"), patch(
            "tiq72_test_commerce_orchestrator.verify_test_webhook", return_value=event
        ):
            return service.accept_signed_reversal(raw_body=b"signed",signature="sig"), store

    def test_full_refund_revokes(self):
        event={"id":"evt_1","type":"charge.refunded","data":{"object":{"id":"ch_1"}}}
        ok, store=self.run_event(event,make_client())
        self.assertTrue(ok)
        self.assertEqual(store.events[0][1],{"verified_reversal":True})

    def test_partial_refund_does_not_revoke(self):
        event={"id":"evt_1","type":"charge.refunded","data":{"object":{"id":"ch_1"}}}
        with self.assertRaisesRegex(StripeVerificationError,"full_refund_not_verified"):
            self.run_event(event,make_client(refunded=False,amount_refunded=40))

    def test_dispute_revokes(self):
        event={"id":"evt_2","type":"charge.dispute.created","data":{"object":{"id":"dp_1","charge":"ch_1"}}}
        ok,store=self.run_event(event,make_client())
        self.assertTrue(ok)
        self.assertEqual(store.events[0][0][1],"charge.dispute.created")

    def test_mismatched_charge_rejected(self):
        event={"id":"evt_2","type":"charge.refunded","data":{"object":{"id":"ch_other"}}}
        with self.assertRaisesRegex(StripeVerificationError,"test_charge_required"):
            self.run_event(event,make_client())

if __name__=="__main__": unittest.main()
