"""Offline negative tests: collector cannot install without independent certification."""
import unittest
from unittest.mock import patch

from bot.kraken_collector_composition_v487 import (
    OTHER_FIELDS, KrakenCollectorBindingDenied,
    compose_reviewed_kraken_providers, install_reviewed_kraken_collector,
)
from bot.pretrade_attestation_validation_v452 import REQUIRED


def provider():
    return {"verified": False}


class CollectorCompositionTests(unittest.TestCase):
    def setUp(self):
        self.ids = {field: "reviewed-" + field for field in REQUIRED}
        self.remaining = {field: (lambda field=field: {"field": field}) for field in OTHER_FIELDS}

    def options(self):
        return dict(
            broker=object(), approved_api_key_sha256="a" * 64,
            approved_iban_sha256="b" * 64, reviewed_provider_ids=self.ids,
            independent_open_intents=provider, independent_positions=provider,
            independent_remaining=self.remaining,
            monitoring_category=object(), independently_reviewed=True,
        )

    def test_missing_independent_review_blocks_composition(self):
        options = self.options()
        options["independently_reviewed"] = False
        with self.assertRaises(KrakenCollectorBindingDenied):
            compose_reviewed_kraken_providers(**options)

    def test_missing_independent_field_blocks_composition(self):
        options = self.options()
        options["independent_remaining"] = dict(self.remaining)
        options["independent_remaining"].pop(next(iter(OTHER_FIELDS)))
        with self.assertRaises(KrakenCollectorBindingDenied):
            compose_reviewed_kraken_providers(**options)

    def test_duplicate_provider_identity_blocks_composition(self):
        options = self.options()
        first, second = list(REQUIRED)[:2]
        options["reviewed_provider_ids"] = dict(self.ids)
        options["reviewed_provider_ids"][second] = options["reviewed_provider_ids"][first]
        with self.assertRaises(KrakenCollectorBindingDenied):
            compose_reviewed_kraken_providers(**options)

    def test_complete_composition_does_not_install(self):
        fake = {field: (lambda: {}) for field in
                ("account_permissions", "account_identity", "broker_balances", "open_order_reconciliation")}
        with patch("bot.kraken_collector_composition_v487.make_reviewed_kraken_producer_bundle",
                   return_value=fake), patch(
                "bot.kraken_collector_composition_v487.make_kraken_protective_exit_provider",
                return_value=provider), patch(
                "bot.kraken_collector_composition_v487.register_reviewed_account_registry"
                ) as install:
            result = compose_reviewed_kraken_providers(**self.options())
            self.assertEqual(set(result), set(REQUIRED))
            install.assert_not_called()
            with self.assertRaises(TypeError):
                result["risk_limits"] = provider

    def test_no_install_without_all_certifications(self):
        with patch("bot.kraken_collector_composition_v487.register_reviewed_account_registry") as register:
            for kw in ({}, {"independently_reviewed": True},
                       {"independently_reviewed": True, "backup_restore_certified": True}):
                with self.assertRaises(KrakenCollectorBindingDenied):
                    install_reviewed_kraken_collector(
                        providers={field: provider for field in REQUIRED},
                        reviewed_provider_ids=self.ids, **kw)
            register.assert_not_called()

    def test_false_evidence_refuses_install(self):
        providers = {field: provider for field in REQUIRED}
        with patch("bot.kraken_collector_composition_v487.register_reviewed_account_registry") as register:
            with self.assertRaises(KrakenCollectorBindingDenied):
                install_reviewed_kraken_collector(providers=providers, reviewed_provider_ids=self.ids, independently_reviewed=True, backup_restore_certified=True, broker_ledger_exits_certified=True)
            register.assert_not_called()

    def test_explicit_install_passes_exact_registry_to_existing_gate(self):
        providers = {field: provider for field in REQUIRED}
        with patch("bot.kraken_collector_composition_v487.register_reviewed_account_registry") as register, patch("bot.kraken_collector_composition_v487.evaluate_pretrade_certificate", return_value={"certified": True, "authorizes_orders": False}):
            install_reviewed_kraken_collector(
                providers=providers, reviewed_provider_ids=self.ids,
                independently_reviewed=True, backup_restore_certified=True,
                broker_ledger_exits_certified=True,
            )
            register.assert_called_once_with(
                providers_by_account={"platform:kraken": providers},
                trusted_provider_ids=self.ids, independently_reviewed=True)


if __name__ == "__main__":
    unittest.main()
