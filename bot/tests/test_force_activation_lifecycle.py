"""Regression tests for fail-closed force-activation compatibility behavior."""

from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from bot import readiness_table
from bot.startup_coordinator import (
    LifecyclePhase,
    RuntimeAuthorityState,
    StartupCoordinatorState,
    get_startup_coordinator,
)


class TestForceActivationCompatibility(unittest.TestCase):
    """The legacy API may request activation but may not bypass its proof."""

    def setUp(self) -> None:
        self.coord = get_startup_coordinator()
        self.coord.reset_for_testing()
        readiness_table.reset()

    def tearDown(self) -> None:
        self.coord.reset_for_testing()
        readiness_table.reset()
        os.environ.pop("NIJA_FORCE_ACTIVATION", None)

    def _prepare_canonical_readiness(self) -> None:
        for key in readiness_table.KEYS:
            readiness_table.mark_ready(key)
        self.coord.record_bootstrap_state("RUNNING_SUPERVISED")
        self.coord.record_capital_state(
            state="RUNNING",
            hydrated=True,
            balance=100.0,
            stale=False,
        )
        self.coord.record_threads_launched(1)
        self.coord.record_threads_confirmed_running(
            bootstrap_state="RUNNING_SUPERVISED"
        )
        self.coord.record_authority(ready=True)
        self.coord.record_nonce_status(ready=True)
        self.coord.record_dispatch_health(ready=True)
        self.coord.record_global_gate(ready=True, detail="barrier_passed")

    def test_request_without_prerequisites_is_refused(self) -> None:
        with self.assertRaisesRegex(
            RuntimeError,
            "Force activation compatibility request refused",
        ):
            self.coord.force_activate_bypass("missing_prerequisites")

        self.assertEqual(self.coord._runtime.last_committed_snapshot_version, 0)
        self.assertFalse(self.coord._runtime._activation_committed)
        self.assertNotEqual(
            self.coord._runtime.runtime_authority_state,
            RuntimeAuthorityState.EXECUTING,
        )

    def test_environment_flag_cannot_manufacture_live_state(self) -> None:
        with patch.dict(os.environ, {"NIJA_FORCE_ACTIVATION": "1"}):
            snapshot = self.coord.build_snapshot(
                trading_state="LIVE_ACTIVE",
                activation_intent=True,
            )

        self.assertNotEqual(
            snapshot.runtime_authority_state,
            RuntimeAuthorityState.EXECUTING.value,
        )
        self.assertNotEqual(snapshot.lifecycle_phase, LifecyclePhase.LIVE.value)
        self.assertFalse(snapshot.dispatch_enabled)

    def test_ready_request_commits_through_canonical_proof(self) -> None:
        self._prepare_canonical_readiness()

        self.coord.force_activate_bypass("compatibility_request")
        snapshot = self.coord.build_snapshot(
            trading_state="LIVE_ACTIVE",
            activation_intent=True,
        )

        self.assertEqual(
            snapshot.runtime_authority_state,
            RuntimeAuthorityState.EXECUTING.value,
        )
        self.assertEqual(snapshot.lifecycle_phase, LifecyclePhase.LIVE.value)
        self.assertTrue(snapshot.dispatch_enabled)
        self.assertGreater(snapshot.last_committed_snapshot_version, 0)
        self.assertEqual(
            self.coord._runtime.coordinator_state,
            StartupCoordinatorState.DISPATCH_ENABLED,
        )

    def test_ready_request_is_idempotent(self) -> None:
        self._prepare_canonical_readiness()
        self.coord.force_activate_bypass("first")
        first_commit = self.coord._runtime.last_committed_snapshot_version

        self.coord.force_activate_bypass("second")

        self.assertEqual(
            self.coord._runtime.last_committed_snapshot_version,
            first_commit,
        )

    def test_kill_switch_revokes_compatibility_request(self) -> None:
        self._prepare_canonical_readiness()
        self.coord.record_kill_switch(active=True)

        with self.assertRaises(RuntimeError):
            self.coord.force_activate_bypass("kill_switch_test")

        snapshot = self.coord.build_snapshot(
            trading_state="LIVE_ACTIVE",
            activation_intent=True,
        )
        self.assertNotEqual(
            snapshot.runtime_authority_state,
            RuntimeAuthorityState.EXECUTING.value,
        )
        self.assertFalse(snapshot.dispatch_enabled)

    def test_readiness_loss_revokes_prior_commit(self) -> None:
        self._prepare_canonical_readiness()
        self.coord.force_activate_bypass("ready")

        readiness_table.revoke_many(
            ("authority_ready", "nonce_ready", "execution_ready"),
            reason="writer_lost",
        )
        snapshot = self.coord.build_snapshot(
            trading_state="LIVE_ACTIVE",
            activation_intent=True,
        )

        self.assertEqual(snapshot.last_committed_snapshot_version, 0)
        self.assertFalse(snapshot.dispatch_enabled)
        self.assertNotEqual(snapshot.lifecycle_phase, LifecyclePhase.LIVE.value)


if __name__ == "__main__":
    unittest.main()
