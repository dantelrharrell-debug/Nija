"""Checkout test-mode credential and return-origin security boundary tests."""
import os
import unittest
from unittest.mock import patch
from tiq72_stripe_test_verification import (
    StripeVerificationError, assert_test_mode_configuration, create_test_checkout,
)

class FakeStripe:
    def __init__(self):
        self.calls = []
        self.checkout = type("Checkout", (), {})()
        self.checkout.Session = type("Session", (), {})()
        self.checkout.Session.create = self.create

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return {"id": "cs_test_123", "livemode": False}

class TestTiq72CheckoutReturnOrigin(unittest.TestCase):
    def setUp(self):
        self.client = FakeStripe()
        self.settings = patch.dict(os.environ, {
            "STRIPE_TEST_SECRET_KEY": "sk_test_synthetic_only",
            "STRIPE_SECRET_KEY": "unrelated_live_credential",
            "TIQ72_STRIPE_TEST_PRICE_ID": "price_approved_test",
            "TIQ72_STRIPE_TEST_PRODUCT_ID": "prod_approved_test",
            "TIQ72_TEST_RETURN_ORIGIN": "https://nija.example",
            "NIJA_GAME_REPORTS_ENABLED": "false",
            "NIJA_GAME_BROWSER_CHECKOUT_ENABLED": "false",
        }, clear=False)
        self.settings.start()
        self.addCleanup(self.settings.stop)

    def test_allows_only_approved_https_return_origin(self):
        create_test_checkout(self.client, "reservation-1", "https://nija.example/success?a=1",
                             "https://nija.example/cancel")
        self.assertEqual(len(self.client.calls), 1)
        self.assertEqual(self.client.calls[0]["line_items"],
                         [{"price": "price_approved_test", "quantity": 1}])

    def test_untrusted_or_ambiguous_redirects_never_call_stripe(self):
        bad = (
            "http://nija.example/success", "https://nija.example.evil.test/success",
            "https://nija.example@evil.test/success", "https://evil.test@nija.example/success",
            "https://nija.example:8443/success", "https://nija.example/#fragment",
            "https://nija.example\\@evil.test/success", "https://nija.example//\\evil.test",
            "https://nija.example/success\n", "https:///nija.example/success",
            "https://nija.example",
        )
        for url in bad:
            with self.subTest(url=url):
                with self.assertRaises(StripeVerificationError):
                    create_test_checkout(self.client, "reservation-1", url,
                                         "https://nija.example/cancel")
        self.assertEqual(self.client.calls, [])

    def test_origin_configuration_must_be_explicit(self):
        os.environ.pop("TIQ72_TEST_RETURN_ORIGIN", None)
        with self.assertRaisesRegex(StripeVerificationError, "approved_return_origin_required"):
            create_test_checkout(self.client, "reservation-1", "https://nija.example/success",
                                 "https://nija.example/cancel")
        self.assertEqual(self.client.calls, [])

    def test_test_key_only_never_uses_generic_live_key(self):
        os.environ.pop("STRIPE_TEST_SECRET_KEY", None)
        with self.assertRaisesRegex(StripeVerificationError, "test_key_required"):
            assert_test_mode_configuration()

    def test_legacy_live_checkout_flags_block_test_checkout(self):
        os.environ["NIJA_GAME_BROWSER_CHECKOUT_ENABLED"] = "true"
        with self.assertRaisesRegex(StripeVerificationError, "legacy_payment_flags"):
            create_test_checkout(self.client, "reservation-1", "https://nija.example/success",
                                 "https://nija.example/cancel")
        self.assertEqual(self.client.calls, [])

if __name__ == "__main__":
    unittest.main()
