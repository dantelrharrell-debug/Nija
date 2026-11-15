"""Offline regression tests for TIQ72 Stripe test-mode reconciliation."""
import os
import unittest
from unittest.mock import patch
from tiq72_stripe_test_verification import verify_test_checkout, StripeVerificationError

class Obj(dict):
    __getattr__ = dict.__getitem__

class TestCheckoutIdentity(unittest.TestCase):
    def test_mismatched_client_reference_is_rejected(self):
        session = dict(id="cs_test_abc",livemode=False,mode="payment",payment_status="paid",
            status="complete",currency="usd",amount_total=100,client_reference_id="wrong",
            metadata={"tiq72_reservation_id":"reservation-1","tiq72_version":"v515-72-decisions"},
            payment_intent={"status":"succeeded","amount_received":100})
        client=Obj(checkout=Obj(Session=Obj(retrieve=lambda *a,**k:session)))
        with self.assertRaisesRegex(StripeVerificationError,"checkout_identity_mismatch"):
            verify_test_checkout(client,"cs_test_abc","reservation-1")

if __name__=="__main__": unittest.main()
