"""Offline tests for fail-closed v489 seven-source composition."""
import sys
import types
import unittest
from pathlib import Path

if "bot" not in sys.modules:
    package = types.ModuleType("bot")
    package.__path__ = [str(Path(__file__).resolve().parents[1] / "bot")]
    sys.modules["bot"] = package

from bot.kraken_seven_source_registry_v489 import (
    REMAINING_FIELDS, SEVEN_FIELDS, compose_seven_source_kraken_registry,
)
from bot.kraken_reviewed_registry_composition_v484 import KrakenRegistryIncomplete
from bot.pretrade_attestation_validation_v452 import REQUIRED, evaluate_pretrade_certificate


def stub():
    raise AssertionError("composition must never call producers")


class TestSevenSourceRegistry(unittest.TestCase):
    def setUp(self):
        self.broker = {f: stub for f in (
            "account_permissions", "account_identity", "broker_balances",
            "open_order_reconciliation")}
        self.writer = {"writer_lease": stub, "nonce_sequence": stub}
        self.other = {f: stub for f in REMAINING_FIELDS}
        self.ids = {f: "reviewed-" + f for f in REQUIRED}

    def compose(self, **changes):
        kw = dict(broker_providers=self.broker, protective_exit_provider=stub,
                  writer_nonce_providers=self.writer,
                  independent_providers=self.other,
                  trusted_provider_ids=self.ids, independently_reviewed=True)
        kw.update(changes)
        return compose_seven_source_kraken_registry(**kw)

    def test_six_fields_remain_and_registry_complete_without_invocation(self):
        self.assertEqual(REMAINING_FIELDS, {
            "position_ledger_reconciliation", "duplicate_order_fence",
            "operator_authorization", "kill_switch_clear",
            "risk_limits", "position_sync"})
        self.assertEqual(len(SEVEN_FIELDS), 7)
        registry = self.compose()
        self.assertEqual(set(registry), set(REQUIRED))
        self.assertFalse(evaluate_pretrade_certificate(
            {}, account="platform:kraken", trusted_provider_ids=self.ids
        )["certified"])

    def test_missing_six_denied(self):
        for f in REMAINING_FIELDS:
            with self.subTest(f=f), self.assertRaises(KrakenRegistryIncomplete):
                self.compose(independent_providers={
                    k: v for k, v in self.other.items() if k != f})

    def test_missing_writer_denied(self):
        with self.assertRaises(KrakenRegistryIncomplete):
            self.compose(writer_nonce_providers={"writer_lease": stub})

    def test_review_required(self):
        with self.assertRaises(KrakenRegistryIncomplete):
            self.compose(independently_reviewed=False)

    def test_noncallable_denied(self):
        bad = dict(self.other)
        bad["risk_limits"] = None
        with self.assertRaises(KrakenRegistryIncomplete):
            self.compose(independent_providers=bad)


if __name__ == "__main__":
    unittest.main()
