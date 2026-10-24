"""Fail-closed regression tests for independent pre-trade evidence.

No network requests, broker calls, order submission, or production changes.
"""
import unittest
from unittest.mock import patch

from bot import pretrade_independent_attestation as att


class IndependentPretradeAttestationTests(unittest.TestCase):
    def setUp(self):
        self.previous = att._COLLECTOR
        att._COLLECTOR = None
        self.account = "platform:kraken"
        self.now = 1000.0

    def tearDown(self):
        att._COLLECTOR = self.previous

    def valid(self):
        return {
            "account": self.account,
            "observed_at_epoch": self.now,
            "source": "authenticated_independent",
            "read_only": True,
            "scope_verified": True,
            "provenance": {
                "authenticated_broker_read_verified": True,
                "ledger_snapshot_verified": True,
                "complete_pagination_verified": True,
                "collector_identity_verified": True,
                "account_scope_verified": True,
            },
            "checks": {key: True for key in att.FIELDS},
        }

    def inspect(self, payload):
        att.install_authenticated_collector(lambda _account: payload)
        return att.inspect_authenticated_attestations(self.account, now=self.now)

    def assert_denied(self, report):
        self.assertFalse(all(report["checks"].values()))
        self.assertIs(report["authorizes_orders"], False)

    def test_missing_collector_denied(self):
        report = att.inspect_authenticated_attestations(self.account, now=self.now)
        self.assertEqual(report["producer_status"], "collector_missing")
        self.assert_denied(report)

    def test_missing_scope_denied_without_collector_call(self):
        called = []
        att.install_authenticated_collector(lambda scope: called.append(scope))
        report = att.inspect_authenticated_attestations(" ", now=self.now)
        self.assertEqual(report["producer_status"], "account_scope_invalid")
        self.assertEqual(called, [])
        self.assert_denied(report)

    def test_wrong_account_denied(self):
        payload = self.valid()
        payload["account"] = "user:other:kraken"
        report = self.inspect(payload)
        self.assertEqual(report["producer_status"], "account_scope_mismatch")
        self.assert_denied(report)

    def test_stale_observation_denied(self):
        payload = self.valid()
        payload["observed_at_epoch"] -= 61
        report = self.inspect(payload)
        self.assertEqual(report["producer_status"], "observation_missing_future_or_stale")
        self.assert_denied(report)

    def test_future_observation_denied(self):
        payload = self.valid()
        payload["observed_at_epoch"] += 1
        self.assert_denied(self.inspect(payload))

    def test_unverified_pagination_denied(self):
        payload = self.valid()
        payload["provenance"]["complete_pagination_verified"] = False
        report = self.inspect(payload)
        self.assertEqual(report["producer_status"], "provenance_unverified")
        self.assert_denied(report)

    def test_missing_protective_exits_denied(self):
        payload = self.valid()
        payload["checks"]["protective_exit_readback"] = False
        report = self.inspect(payload)
        self.assertEqual(report["producer_status"], "checks_incomplete")
        self.assert_denied(report)

    def test_ledger_mismatch_denied(self):
        payload = self.valid()
        payload["checks"]["position_ledger_reconciliation"] = False
        self.assert_denied(self.inspect(payload))

    def test_nonce_conflict_denied(self):
        payload = self.valid()
        payload["checks"]["nonce_sequence"] = False
        self.assert_denied(self.inspect(payload))

    def test_disconnected_broker_denied(self):
        payload = self.valid()
        payload["checks"]["broker_balances"] = False
        self.assert_denied(self.inspect(payload))

    def test_registry_eligibility_cannot_substitute_for_authenticated_proof(self):
        payload = self.valid()
        payload["source"] = "registry_all_connected"
        report = self.inspect(payload)
        self.assertEqual(report["producer_status"], "producer_source_untrusted")
        self.assert_denied(report)

    def test_complete_report_remains_diagnostic_not_order_authorization(self):
        report = self.inspect(self.valid())
        self.assertEqual(report["producer_status"], "checks_passed_diagnostic_only")
        self.assertTrue(all(report["checks"].values()))
        self.assertIs(report["authorizes_orders"], False)


if __name__ == "__main__":
    unittest.main()
