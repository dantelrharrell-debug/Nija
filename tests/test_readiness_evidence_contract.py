"""Contract tests: no broker, network, production secrets or live orders."""
import unittest
from datetime import datetime, timedelta, timezone

from readiness_evidence_contract import Evidence, Readiness, assess

NOW = datetime(2026, 11, 3, 20, 0, tzinfo=timezone.utc)
REQUIRED = frozenset({"ledger", "protective_orders"})


def evidence(provider, *, verified=True, deployment="dep-test", age=10, ttl=60):
    return Evidence(provider, "broker-audit", deployment,
                    NOW - timedelta(seconds=age),
                    NOW + timedelta(seconds=ttl), verified)


class ReadinessContractTests(unittest.TestCase):
    def decide(self, records, **kwargs):
        return assess(records, required=REQUIRED, deployment="dep-test", now=NOW, **kwargs)

    def test_missing_provider_blocks(self):
        result = self.decide([evidence("ledger")])
        self.assertEqual(result.state, Readiness.BLOCKED)
        self.assertIn("missing_provider:protective_orders", result.failures)
        self.assertFalse(result.allow_new_orders)

    def test_duplicate_provider_blocks(self):
        result = self.decide([evidence("ledger"), evidence("ledger"),
                              evidence("protective_orders")])
        self.assertIn("duplicate_or_empty_provider", result.failures)

    def test_stale_or_future_evidence_blocks(self):
        result = self.decide([evidence("ledger", ttl=-1),
                              evidence("protective_orders", age=-1)])
        self.assertIn("stale_or_invalid_timestamp", result.failures)

    def test_wrong_deployment_blocks(self):
        result = self.decide([evidence("ledger", deployment="old"),
                              evidence("protective_orders")])
        self.assertIn("source_or_deployment_mismatch", result.failures)

    def test_unverified_provider_blocks(self):
        result = self.decide([evidence("ledger", verified=False),
                              evidence("protective_orders")])
        self.assertIn("provider_not_verified:ledger", result.failures)

    def test_recovering_does_not_grant_orders(self):
        result = self.decide([], recovery_in_progress=True,
                             independently_authorized=True, kill_switch_clear=True)
        self.assertEqual(result.state, Readiness.RECOVERING)
        self.assertFalse(result.allow_new_orders)

    def test_certified_is_not_order_permission(self):
        result = self.decide([evidence("ledger"), evidence("protective_orders")])
        self.assertEqual(result.state, Readiness.CERTIFIED)
        self.assertFalse(result.allow_new_orders)

    def test_authorized_label_never_grants_orders(self):
        result = self.decide([evidence("ledger"), evidence("protective_orders")],
                             independently_authorized=True, kill_switch_clear=True)
        self.assertEqual(result.state, Readiness.AUTHORIZED)
        self.assertFalse(result.allow_new_orders)

    def test_authorization_requires_clear_kill_switch(self):
        result = self.decide([evidence("ledger"), evidence("protective_orders")],
                             independently_authorized=True, kill_switch_clear=False)
        self.assertEqual(result.state, Readiness.CERTIFIED)

    def test_empty_contract_fails_closed(self):
        result = assess([], required=frozenset(), deployment="dep-test", now=NOW)
        self.assertEqual(result.state, Readiness.BLOCKED)


if __name__ == "__main__":
    unittest.main()
