"""Offline plan regressions; no bot bootstrap, broker calls or live orders."""
from __future__ import annotations

import importlib.util
import json
import os
import sys
import tempfile
import time
import types
import unittest
from dataclasses import asdict, replace
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

BOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("_startup_plan_offline", BOT / "startup_verification_plan.py")
P = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = P
SPEC.loader.exec_module(P)


def plan(**changes):
    """Produce synthetic terms unrelated to a current market or live account."""
    data = dict(account_fingerprint="a" * 64, api_key_fingerprint="b" * 128,
                symbol="BTC-USD", pair="XXBTZUSD", budget_usd="25.00", entry_limit="1000",
                base_quantity="0.020", fee_rate_max="0.01", fee_cash_reserve_usd="0.20",
                stop_trigger="950", stop_limit="900", close_limit="990", base_quantum="0.001",
                minimum_base="0.001", minimum_quote="1.00", expires_at_epoch=time.time() + 300)
    data.update(changes)
    return P.StartupVerificationPlan(**data)


class PlanTests(unittest.TestCase):
    def test_fee_inclusive_cash_ceiling(self):
        value = plan()
        value.validate()
        self.assertEqual(value.maximum_cash_debit(), Decimal("20.40000"))
        with self.assertRaisesRegex(P.StartupPlanError, "budget_exceeded"):
            plan(base_quantity="0.025").validate()

    def test_exact_budget_is_allowed_without_rounding_up(self):
        plan(base_quantity="0.025", fee_rate_max="0", fee_cash_reserve_usd="0").validate()

    def test_nonfinite_and_negative_terms_are_rejected(self):
        for field in ("entry_limit", "base_quantity", "fee_rate_max", "fee_cash_reserve_usd", "budget_usd"):
            for value in ("NaN", "Infinity", "-1"):
                with self.subTest(field=field, value=value), self.assertRaises(P.StartupPlanError):
                    plan(**{field: value}).validate()

    def test_protective_exit_minimum_is_not_lowered(self):
        with self.assertRaisesRegex(P.StartupPlanError, "protective_exit_below_minimum"):
            plan(minimum_quote="19").validate()

    def test_terms_and_account_are_bound_to_digest(self):
        value = plan()
        for field, change in {"budget_usd": "24", "entry_limit": "1001", "account_fingerprint": "c" * 64,
                              "stop_trigger": "951", "expires_at_epoch": value.expires_at_epoch + 1}.items():
            self.assertNotEqual(value.digest(), replace(value, **{field: change}).digest())

    def test_bounded_order_descriptions(self):
        value = plan()
        entry = value.order_parameters("entry")
        self.assertEqual((entry["ordertype"], entry["timeinforce"], entry["price"]), ("limit", "FOK", "1000"))
        protect = value.order_parameters("protect", owned_base="0.0199")
        self.assertEqual((protect["ordertype"], protect["price2"], protect["volume"]),
                         ("stop-loss-limit", "900", "0.019"))
        close = value.order_parameters("close", owned_base="0.0199")
        self.assertEqual((close["type"], close["timeinforce"]), ("sell", "FOK"))
        self.assertEqual(len({entry["cl_ord_id"], protect["cl_ord_id"], close["cl_ord_id"]}), 3)
        for order in (entry, protect, close):
            self.assertRegex(order["cl_ord_id"], r"^[0-9a-f]{32}$")
            self.assertNotIn("leverage", order)
            self.assertNotIn("validate", order)

    def test_non_power_of_ten_quantum_is_floored(self):
        value = plan(base_quantum="0.005")
        self.assertEqual(Decimal(value.order_parameters("close", owned_base="0.019")["volume"]), Decimal("0.015"))

    def test_fee_adjusted_exit_must_still_meet_quote_minimum(self):
        with self.assertRaisesRegex(P.StartupPlanError, "quote_minimum"):
            plan(minimum_quote="17").order_parameters("protect", owned_base="0.018")

    def test_no_unowned_volume_or_margin(self):
        value = plan()
        with self.assertRaises(P.StartupPlanError):
            value.order_parameters("close", owned_base="0.021")
        proposed = dict(pair=value.pair, type="buy", volume="0.020", leverage="2")
        with self.assertRaisesRegex(P.StartupPlanError, "margin_order"):
            P.enforce_bounded_startup_parameters(value, proposed, "entry")

    def test_final_envelope_never_increases_risk_sized_quantity(self):
        value = plan()
        with self.assertRaisesRegex(P.StartupPlanError, "risk_sized_volume"):
            P.enforce_bounded_startup_parameters(value, dict(pair=value.pair, type="buy", volume="0.019"), "entry")
        exact = P.enforce_bounded_startup_parameters(
            value, dict(pair=value.pair, type="buy", volume="0.025", ordertype="market", oflags="post,viqc"), "entry"
        )
        self.assertEqual(exact["volume"], "0.020")
        self.assertEqual(exact["ordertype"], "limit")
        self.assertEqual(exact["oflags"], "fciq")


class ApprovalTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.path = Path(self.directory.name) / "approval.json"
        self.value = plan()
        self.identity = types.SimpleNamespace(account_fingerprint=self.value.account_fingerprint,
                                              api_key_fingerprint=self.value.api_key_fingerprint,
                                              observed_at_epoch=time.time())
        self.receipt = dict(approved=True, approved_by="offline operator", ownership_verified=True,
                            plan=asdict(self.value), approved_plan_digest=self.value.digest(),
                            approved_at_epoch=time.time(), bounded_entry_validated=True, native_exit_validated=True)
        self.environment = patch.dict(os.environ, {"NIJA_STARTUP_MAX_CASH_DEBIT_USD": "25.00"})
        self.environment.start()
        self.write()

    def write(self):
        self.path.write_text(json.dumps(self.receipt))
        self.path.chmod(0o600)

    def load(self, **kwargs):
        return P.load_startup_approval(self.identity, symbol="BTC-USD", path=self.path, **kwargs)

    def tearDown(self):
        self.environment.stop()
        self.directory.cleanup()

    def test_exact_private_receipt_can_be_reviewed(self):
        self.assertEqual(self.load(), self.value)

    def test_planning_ceiling_is_not_approval(self):
        self.receipt["approved"] = False
        self.write()
        with self.assertRaisesRegex(P.StartupPlanError, "not_approved"):
            self.load()

    def test_identity_and_symbol_changes_fail(self):
        for field, value in {"account_fingerprint": "c" * 64, "api_key_fingerprint": "c" * 128,
                             "observed_at_epoch": time.time() - 31}.items():
            identity = types.SimpleNamespace(**vars(self.identity))
            setattr(identity, field, value)
            with self.subTest(field=field), self.assertRaises(P.StartupPlanError):
                P.load_startup_approval(identity, symbol="BTC-USD", path=self.path)
        with self.assertRaises(P.StartupPlanError):
            P.load_startup_approval(self.identity, symbol="ETH-USD", path=self.path)

    def test_stale_plan_cannot_start_a_trade(self):
        self.value = replace(self.value, expires_at_epoch=time.time() - 1)
        self.receipt.update(plan=asdict(self.value), approved_plan_digest=self.value.digest())
        self.write()
        with self.assertRaisesRegex(P.StartupPlanError, "expired"):
            self.load()
        self.assertEqual(self.load(permit_exit_after_expiry=True), self.value)

    def test_modified_terms_require_new_approval(self):
        self.receipt["plan"]["entry_limit"] = "1001"
        self.write()
        with self.assertRaisesRegex(P.StartupPlanError, "terms_changed"):
            self.load()

    def test_missing_ownership_and_exit_checks_fail(self):
        for field in ("ownership_verified", "native_exit_validated", "bounded_entry_validated"):
            with self.subTest(field=field):
                old = self.receipt.pop(field)
                self.write()
                with self.assertRaises(P.StartupPlanError):
                    self.load()
                self.receipt[field] = old

    def test_missing_or_lower_operator_ceiling_fails(self):
        for maximum in ("", "24.99", "NaN"):
            with self.subTest(maximum=maximum), patch.dict(os.environ, {"NIJA_STARTUP_MAX_CASH_DEBIT_USD": maximum}):
                with self.assertRaises(P.StartupPlanError):
                    self.load()

    def test_public_or_symlink_receipt_is_rejected(self):
        self.path.chmod(0o644)
        with self.assertRaisesRegex(P.StartupPlanError, "not_private"):
            self.load()
        self.path.chmod(0o600)
        linked = self.path.parent / "link.json"
        linked.symlink_to(self.path)
        with self.assertRaises(P.StartupPlanError):
            P.load_startup_approval(self.identity, symbol="BTC-USD", path=linked)

    def test_malformed_receipt_does_not_expose_file_contents(self):
        self.path.write_text("synthetic-sensitive-file-value")
        with self.assertRaises(P.StartupPlanError) as caught:
            self.load()
        self.assertNotIn("synthetic-sensitive-file-value", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
