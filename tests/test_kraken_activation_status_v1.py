"""Offline safety tests for the read-only activation projection."""
import unittest
from bot.kraken_activation_status_v1 import (
    REQUIRED_OBSERVATIONS, Snapshot, State, assess,
)


def snapshot(**overrides):
    fields = dict(
        protected_artifacts_verified=True,
        collector_installed=True,
        observations={name: True for name in REQUIRED_OBSERVATIONS},
        broker_reconciled=True,
        security_certified=True,
        independent_receipts_verified=True,
        explicit_bounded_authorization=True,
        canonical_gate_allows_orders=True,
    )
    fields.update(overrides)
    return Snapshot(**fields)


class ActivationStatusTests(unittest.TestCase):
    def test_missing_artifacts_recovery(self):
        result = assess(snapshot(protected_artifacts_verified=False, collector_installed=False))
        self.assertEqual(result.state, State.RECOVERY)
        self.assertFalse(result.authorizes_orders)

    def test_all_missing_observations(self):
        result = assess(snapshot(observations={}))
        self.assertEqual(result.state, State.VERIFYING)
        self.assertEqual(result.observations_verified, 0)
        self.assertEqual(len([x for x in result.blockers if x.startswith("observation_missing:")]), 13)

    def test_approval_is_never_inferred(self):
        result = assess(snapshot(explicit_bounded_authorization=False))
        self.assertEqual(result.state, State.READY_FOR_APPROVAL)
        self.assertFalse(result.authorizes_orders)

    def test_canonical_gate_denial_is_respected(self):
        result = assess(snapshot(canonical_gate_allows_orders=False))
        self.assertEqual(result.state, State.READY_FOR_APPROVAL)

    def test_material_failure_stops(self):
        result = assess(snapshot(material_integrity_failure=True))
        self.assertEqual(result.state, State.PROTECTIVE_STOP)

    def test_controlled_is_diagnostic_not_permission(self):
        result = assess(snapshot())
        self.assertEqual(result.state, State.CONTROLLED)
        self.assertTrue(result.diagnostic_only)
        self.assertFalse(result.authorizes_orders)

    def test_unknown_observation_rejected(self):
        with self.assertRaises(ValueError):
            assess(snapshot(observations={"invented": True}))


if __name__ == "__main__":
    unittest.main()
