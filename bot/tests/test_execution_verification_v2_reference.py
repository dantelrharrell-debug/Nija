"""Offline regression suite for non-authorizing NIJA verification v2 reference."""
from __future__ import annotations

import unittest

from bot.execution_verification_v2_reference import (
    PREFLIGHT_FACTS, classify_preflight, classify_broker_observation,
)


def _intent():
    return {
        "tenant_id": "tenantA", "account_fingerprint": "accountA",
        "venue": "kraken", "portfolio_id": "platform",
        "client_order_id": "intent-001", "broker_order_id": "broker-001",
        "symbol": "BABY-USD", "side": "buy", "requested_qty": "3",
    }


def _fill(**overrides):
    observation = dict(_intent())
    observation.update({
        "authenticated_by_adapter": True, "source": "private_ws",
        "event_kind": "fill", "execution_id": "exec-1",
        "fill_qty": "1", "fill_price": "3.5",
        "cumulative_qty": "1", "canonical_execution_digest": "a" * 64,
    })
    observation.update(overrides)
    return observation


class TestExecutionV2Reference(unittest.TestCase):
    def test_idle_healthy_account_can_be_preflight_candidate_without_old_fill(self):
        result = classify_preflight({k: True for k in PREFLIGHT_FACTS},
                                    sampled_at_epoch=1000, now_epoch=1010,
                                    max_snapshot_age_s=30)
        self.assertTrue(result["preflight_candidate_observed"])
        self.assertTrue(result["diagnostic_only"])
        self.assertFalse(result["execution_authority_granted"])
        self.assertTrue(result["old_execution_marker_ignored_for_preflight"])

    def test_unknown_cost_basis_capital_or_exits_prevents_candidate(self):
        facts = {k: True for k in PREFLIGHT_FACTS}
        for key in ("cost_basis_reconciled", "capital_publication_fresh",
                    "protective_exits_verified", "kill_switch_clear"):
            missing = dict(facts)
            missing[key] = False
            result = classify_preflight(missing, sampled_at_epoch=1000,
                                        now_epoch=1005, max_snapshot_age_s=30)
            self.assertFalse(result["preflight_candidate_observed"])
            self.assertIn(key, result["preflight_missing"])

    def test_stale_snapshot_blocks_even_with_all_other_facts(self):
        result = classify_preflight({k: True for k in PREFLIGHT_FACTS},
                                    sampled_at_epoch=1000, now_epoch=2000,
                                    max_snapshot_age_s=30)
        self.assertFalse(result["preflight_candidate_observed"])
        self.assertIn("authenticated_account_snapshot_fresh", result["preflight_missing"])


    def test_ack_wrong_order_is_quarantined(self):
        result = classify_broker_observation(
            _intent(), _fill(event_kind="acknowledged", broker_order_id="other"),
            prior_fill_digests={})
        self.assertEqual(result["status"], "quarantine")
        self.assertEqual(result["reason"], "broker_order_identity_mismatch")

    def test_terminal_wrong_order_is_quarantined(self):
        result = classify_broker_observation(
            _intent(), _fill(event_kind="canceled", broker_order_id="other"),
            prior_fill_digests={})
        self.assertEqual(result["status"], "quarantine")
        self.assertEqual(result["reason"], "broker_order_identity_mismatch")

    def test_terminal_without_broker_order_id_is_quarantined(self):
        result = classify_broker_observation(
            _intent(), _fill(event_kind="rejected", broker_order_id=""),
            prior_fill_digests={})
        self.assertEqual(result["reason"], "broker_order_id_missing")

    def test_ack_not_fill(self):
        result = classify_broker_observation(
            _intent(), _fill(event_kind="acknowledged"), prior_fill_digests={})
        self.assertEqual(result["status"], "ack_only")
        self.assertFalse(result["execution_authority_granted"])
        self.assertFalse(result["ledger_mutated"])

    def test_valid_partial_fill_is_still_unreconciled(self):
        result = classify_broker_observation(
            _intent(), _fill(event_kind="partial_fill"), prior_fill_digests={})
        self.assertEqual(result["status"], "fill_candidate_for_reconciliation")
        self.assertEqual(result["fill_qty"], "1")
        self.assertFalse(result["new_order_allowed"])

    def test_identical_execution_replay_is_idempotent(self):
        result = classify_broker_observation(
            _intent(), _fill(), prior_fill_digests={"exec-1": "a" * 64})
        self.assertEqual(result["status"], "duplicate")
        self.assertFalse(result["ledger_mutated"])

    def test_conflicting_duplicate_execution_is_quarantined(self):
        result = classify_broker_observation(
            _intent(), _fill(), prior_fill_digests={"exec-1": "b" * 64})
        self.assertEqual(result["status"], "quarantine")
        self.assertEqual(result["reason"], "conflicting_execution_id")

    def test_wrong_tenant_is_quarantined(self):
        result = classify_broker_observation(
            _intent(), _fill(tenant_id="other"), prior_fill_digests={})
        self.assertEqual(result["reason"], "identity_mismatch:tenant_id")

    def test_unauthenticated_source_is_quarantined(self):
        result = classify_broker_observation(
            _intent(), _fill(authenticated_by_adapter=False), prior_fill_digests={})
        self.assertEqual(result["reason"], "authenticated_broker_source_missing")

    def test_nonfinite_fill_is_quarantined(self):
        result = classify_broker_observation(
            _intent(), _fill(fill_price="NaN"), prior_fill_digests={})
        self.assertEqual(result["reason"], "invalid_or_nonfinite_fill")

    def test_overfill_is_quarantined(self):
        result = classify_broker_observation(
            _intent(), _fill(fill_qty="4", cumulative_qty="4"), prior_fill_digests={})
        self.assertEqual(result["reason"], "overfill_or_inconsistent_cumulative_quantity")

    def test_cancel_does_not_prove_zero_fills(self):
        result = classify_broker_observation(
            _intent(), _fill(event_kind="canceled"), prior_fill_digests={})
        self.assertEqual(result["status"], "terminal_unreconciled")


if __name__ == "__main__":
    unittest.main()
