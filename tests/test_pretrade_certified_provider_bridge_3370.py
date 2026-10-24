"""Offline bridge tests: no broker requests or order admission."""
import unittest
from bot.pretrade_attestation_validation_v452 import REQUIRED, SOURCES, PROOF_BY_SOURCE
from bot.pretrade_certified_provider_bridge_3370 import build_diagnostic_collector
from bot.pretrade_independent_attestation import install_authenticated_collector, inspect_authenticated_attestations
from bot import pretrade_independent_attestation as att

class BridgeTests(unittest.TestCase):
    def setUp(self):
        self.old = att._COLLECTOR
        att._COLLECTOR = None
        self.account = "platform:kraken"
        self.now = 1000.0
        self.ids = {field: "trusted_" + SOURCES[field] for field in REQUIRED}

    def tearDown(self):
        att._COLLECTOR = self.old

    def providers(self):
        result = {}
        for field in REQUIRED:
            source = SOURCES[field]
            row = {
                "account": self.account, "verified": True, "read_only": True,
                "scope_verified": True, "source": source,
                "provider_id": self.ids[field], "evidence_id": "proof_" + field,
                "observed_at_epoch": self.now,
                "provenance": {
                    "account_scope_verified": True, "collector_identity_verified": True,
                    "snapshot_complete": True, "complete_pagination_verified": True,
                    PROOF_BY_SOURCE[source]: True,
                },
            }
            result[field] = lambda row=row: row
        return result

    def inspect(self, providers, ids=None):
        install_authenticated_collector(build_diagnostic_collector(
            providers, self.ids if ids is None else ids, clock=lambda: self.now))
        return inspect_authenticated_attestations(self.account, now=self.now)

    def test_valid_multisource_certificate_stays_diagnostic(self):
        report = self.inspect(self.providers())
        self.assertEqual(report["producer_status"], "checks_passed_diagnostic_only")
        self.assertTrue(all(report["checks"].values()))
        self.assertIs(report["authorizes_orders"], False)

    def test_missing_ledger_provider_denied(self):
        providers = self.providers()
        del providers["position_ledger_reconciliation"]
        self.assertFalse(any(self.inspect(providers)["checks"].values()))

    def test_self_declared_trust_identity_denied(self):
        ids = dict(self.ids)
        ids["account_identity"] = "wrong_provider"
        self.assertFalse(any(self.inspect(self.providers(), ids)["checks"].values()))

    def test_missing_protection_denied(self):
        providers = self.providers()
        del providers["protective_exit_readback"]
        self.assertFalse(any(self.inspect(providers)["checks"].values()))

    def test_stale_broker_evidence_denied(self):
        providers = self.providers()
        providers["broker_balances"] = lambda: dict(
            self.providers()["broker_balances"](), observed_at_epoch=self.now - 61)
        self.assertFalse(any(self.inspect(providers)["checks"].values()))

if __name__ == "__main__":
    unittest.main()
