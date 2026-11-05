"""Regression tests: one-time $1 NIJA game results, never trading or subscriptions."""
import os
import unittest
from unittest.mock import patch

import nija_game_billing as game

BROWSER_PROOF = "abcd" * 16
SESSION_ID = "cs_live_0123456789ABCDEFGHIJKLMNOP"


class FakeStripe:
    def __init__(self):
        self.price = {"id": game.PRICE_ID, "active": True, "livemode": True, "type": "one_time",
                      "currency": "usd", "unit_amount": 100, "product": {"id": game.PRODUCT_ID}}
        self.session = {
            "id": SESSION_ID, "livemode": True, "mode": "payment", "status": "complete",
            "payment_status": "paid", "currency": "usd", "amount_total": 100,
            "metadata": {"nija_offer": game.OFFER, "nija_product": game.PRODUCT_ID,
                         "nija_version": "1", "attempt": "l,20,2;s,20,2;w,0,0;w,0,0;l,20,2",
                         "proof_sha256": game.proof_hash(BROWSER_PROOF)},
            "payment_intent": {"status": "succeeded", "currency": "usd", "amount_received": 100,
                               "latest_charge": {"paid": True, "refunded": False,
                                                 "disputed": False, "amount_refunded": 0}},
        }
        self.lines = {"data": [{"quantity": 1, "price": {"id": game.PRICE_ID,
                                                          "product": game.PRODUCT_ID}}]}
        self.recorded = None
        self.Price = type("Price", (), {"retrieve": lambda *args, **kwargs: self.price})()
        self.checkout = type("Checkout", (), {"Session": type("Session", (), {
            "create": lambda *args, **kwargs: self._create(**kwargs),
            "retrieve": lambda *args, **kwargs: self.session,
            "list_line_items": lambda *args, **kwargs: self.lines,
        })()})()

    def _create(self, **kwargs):
        self.recorded = kwargs
        return {"id": SESSION_ID, "url": "https://checkout.stripe.com/c/pay/testonly",
                "livemode": True, "mode": "payment"}


class GamePaymentTests(unittest.TestCase):
    def setUp(self):
        self.stripe = FakeStripe()
        self.decisions = [
            {"choice": "long", "size": 20, "stop": 2},
            {"choice": "short", "size": 20, "stop": 2},
            {"choice": "wait"}, {"choice": "wait"},
            {"choice": "long", "size": 20, "stop": 2},
        ]

    def test_valid_canonical_game_and_round_count(self):
        encoded = game.validate_attempt(self.decisions)
        self.assertEqual(encoded, "l,20,2;s,20,2;w,0,0;w,0,0;l,20,2")
        self.assertEqual(len(game.decode_attempt(encoded)), 5)
        with self.assertRaises(ValueError):
            game.validate_attempt(self.decisions[:4])

    def test_risk_limit_and_invalid_increments(self):
        for size, stop in ((50, 4), (21, 2), (20, .3), (0, .5), (True, 1)):
            entries = list(self.decisions)
            entries[0] = {"choice": "long", "size": size, "stop": stop}
            with self.assertRaises(ValueError):
                game.validate_attempt(entries)

    def test_wait_cannot_carry_position(self):
        entries = list(self.decisions)
        entries[2] = {"choice": "wait", "size": 10, "stop": 1}
        with self.assertRaises(ValueError):
            game.validate_attempt(entries)

    def test_checkout_server_sets_price_and_metadata(self):
        url, proof = game.create_checkout(self.stripe, self.decisions, game.PUBLIC_ORIGIN)
        self.assertTrue(url.startswith("https://checkout.stripe.com/"))
        self.assertEqual(len(proof), 64)
        self.assertEqual(self.stripe.recorded["mode"], "payment")
        self.assertEqual(self.stripe.recorded["line_items"],
                         [{"price": game.PRICE_ID, "quantity": 1}])
        self.assertEqual(self.stripe.recorded["metadata"]["proof_sha256"],
                         game.proof_hash(proof))

    def test_checkout_rejects_wrong_price_and_origin(self):
        self.stripe.price["unit_amount"] = 99
        with self.assertRaises(RuntimeError):
            game.create_checkout(self.stripe, self.decisions, game.PUBLIC_ORIGIN)
        with self.assertRaises(ValueError):
            game.create_checkout(self.stripe, self.decisions, "https://not-nija.example")

    def test_paid_report_same_browser_only(self):
        self.assertEqual(game.verify_paid_attempt(self.stripe, SESSION_ID, BROWSER_PROOF),
                         game.validate_attempt(self.decisions))
        with self.assertRaises(ValueError):
            game.verify_paid_attempt(self.stripe, SESSION_ID, "f" * 64)

    def test_unpaid_and_mismatched_checkout_fail_closed(self):
        for key, value in (("payment_status", "unpaid"), ("status", "open"),
                           ("amount_total", 500), ("currency", "eur"), ("livemode", False)):
            prior = self.stripe.session[key]
            self.stripe.session[key] = value
            with self.assertRaises(ValueError):
                game.verify_paid_attempt(self.stripe, SESSION_ID, BROWSER_PROOF)
            self.stripe.session[key] = prior

    def test_refunded_or_disputed_charge_denied(self):
        charge = self.stripe.session["payment_intent"]["latest_charge"]
        for key, value in (("refunded", True), ("disputed", True),
                           ("amount_refunded", 100), ("paid", False)):
            before = charge[key]
            charge[key] = value
            with self.assertRaises(ValueError):
                game.verify_paid_attempt(self.stripe, SESSION_ID, BROWSER_PROOF)
            charge[key] = before

    def test_other_product_not_accepted(self):
        self.stripe.lines["data"][0]["price"]["id"] = "price_wrong"
        with self.assertRaises(ValueError):
            game.verify_paid_attempt(self.stripe, SESSION_ID, BROWSER_PROOF)

    def test_corrupt_stored_game_data_denied(self):
        self.stripe.session["metadata"]["attempt"] = "invalid;data"
        with self.assertRaises(ValueError):
            game.verify_paid_attempt(self.stripe, SESSION_ID, BROWSER_PROOF)

    def test_gateway_secret_and_feature_flag(self):
        with patch.dict(os.environ, {"NIJA_GAME_GATEWAY_TOKEN": "t" * 64,
                                      "NIJA_GAME_REPORTS_ENABLED": "false",
                                      "STRIPE_SECRET_KEY": "sk_live_mock"}):
            self.assertFalse(game.enabled())
            self.assertFalse(game.trusted_gateway({}))
            self.assertFalse(game.trusted_gateway({"X-NIJA-Game-Gateway": "wrong"}))
            self.assertTrue(game.trusted_gateway({"X-NIJA-Game-Gateway": "t" * 64}))
        with patch.dict(os.environ, {"NIJA_GAME_GATEWAY_TOKEN": "",
                                      "NIJA_GAME_REPORTS_ENABLED": "true",
                                      "STRIPE_SECRET_KEY": "sk_live_mock"}):
            self.assertFalse(game.enabled())


if __name__ == "__main__":
    unittest.main()
