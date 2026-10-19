"""Offline regression tests for registered-platform capital evidence diagnostics.

No network access, broker orders, execution readiness, or live activation.
"""
from __future__ import annotations

import threading
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from bot import runtime_registered_platform_capital_completeness_v270_patch as v270


class _Authority:
    def get_snapshot_publication_status(self):
        return SimpleNamespace(accepted=True, stale=False)

    def is_stale(self):
        return False

    def is_brokers_complete(self):
        return True


class _Manager:
    def __init__(self):
        self._capital_state_lock = threading.RLock()
        self._capital_ready = True
        self._trading_halted_due_to_capital = False


class TestCapitalV270ExactEvidence(unittest.TestCase):
    def _check(self, valid, *, connected=3, registered=3, accepted=True):
        manager = _Manager()
        authority = _Authority() if accepted else None
        result = {"ready": 1.0, "total_capital": 758.62, "valid_brokers": valid}
        with patch.object(v270, "_authority", return_value=authority):
            output = v270._fail_closed_result(
                manager, result, registered=registered, connected=connected
            )
        return manager, result, output

    def test_three_registered_three_connected_three_valid_preserves_result(self):
        manager, original, result = self._check(3)
        self.assertIs(result, original)
        self.assertTrue(manager._capital_ready)
        self.assertFalse(manager._trading_halted_due_to_capital)

    def test_inflated_extra_contributors_never_grant_three_broker_readiness(self):
        manager, _, output = self._check(4)
        self.assertEqual(output["ready"], 0.0)
        self.assertEqual(output["registered_platform_complete"], 0.0)
        self.assertFalse(manager._capital_ready)
        self.assertTrue(manager._trading_halted_due_to_capital)

    def test_zero_contributors_fail_closed_even_when_brokers_connected(self):
        manager, _, output = self._check(0)
        self.assertEqual(output["ready"], 0.0)
        self.assertEqual(output["total_capital"], 758.62)
        self.assertFalse(manager._capital_ready)
        self.assertTrue(manager._trading_halted_due_to_capital)

    def test_missing_connected_broker_still_fails_closed(self):
        manager, _, output = self._check(3, connected=2)
        self.assertEqual(output["ready"], 0.0)
        self.assertEqual(output["connected_platform_brokers"], 2.0)
        self.assertFalse(manager._capital_ready)

    def test_rejected_publication_still_fails_closed(self):
        manager, _, output = self._check(3, accepted=False)
        self.assertFalse(output["publication_current"])
        self.assertEqual(output["ready"], 0.0)
        self.assertFalse(manager._capital_ready)

    def test_failure_reason_codes_are_static_and_non_authorizing(self):
        reasons = v270._capital_failure_reasons(
            {"ready": 0.0, "valid_brokers": 0, "dedup": 1.0, "pending": 1.0},
            registered=3, connected=3, valid=0, publication_current=False,
        )
        self.assertIn("coalesced_refresh", reasons)
        self.assertIn("upstream_refresh_pending", reasons)
        self.assertIn("contributing_broker_count_mismatch", reasons)
        self.assertIn("publication_unaccepted_stale_or_incomplete", reasons)
        self.assertNotIn("registered_connectivity_incomplete", reasons)

    def test_extra_contributors_report_identity_inconsistency(self):
        reasons = v270._capital_failure_reasons(
            {"ready": 1.0, "valid_brokers": 4}, registered=3, connected=3,
            valid=4, publication_current=True,
        )
        self.assertEqual(reasons, (
            "contributing_broker_count_mismatch", "contributors_exceed_connected"
        ))

    def test_missing_result_is_not_accepted_as_valid_snapshot(self):
        manager = _Manager()
        with patch.object(v270, "_authority", return_value=_Authority()):
            output = v270._fail_closed_result(
                manager, None, registered=3, connected=3
            )
        self.assertEqual(output["ready"], 0.0)
        self.assertFalse(manager._capital_ready)
        self.assertIn("refresh_result_unavailable", v270._capital_failure_reasons(
            None, registered=3, connected=3, valid=0, publication_current=True
        ))


if __name__ == "__main__":
    unittest.main()
