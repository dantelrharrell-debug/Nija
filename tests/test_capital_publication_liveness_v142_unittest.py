from __future__ import annotations

import os
import types
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from bot import capital_publication_liveness_v142_patch as v142
from bot.kill_switch_coordinator_sync_patch import _prepare_capital_publication_liveness


class CapitalPublicationLivenessV142Tests(unittest.TestCase):
    def test_runtime_pipeline_deadline_is_strictly_inside_freshness_ttl(self) -> None:
        with (
            patch.object(v142, "_freshness_ttl_seconds", return_value=90.0),
            patch.object(v142, "_fetch_budget_seconds", return_value=45.0),
            patch.dict(os.environ, {"NIJA_CAPITAL_RUNTIME_PIPELINE_DEADLINE_S": "999"}),
        ):
            self.assertEqual(v142._runtime_pipeline_deadline_seconds(), 80.0)
            self.assertLess(v142._runtime_pipeline_deadline_seconds(), 90.0)

    def test_readiness_truth_separates_connectivity_and_hydration_from_freshness(self) -> None:
        import preactivation_readiness_convergence_v16_patch as v16

        original = v16._collect_proofs

        def stale_capital_proof():
            return (
                {
                    "broker_connected": False,
                    "balance_hydrated": False,
                    "authority_ready": True,
                    "capital_ready": False,
                    "risk_ready": True,
                    "strategy_ready": True,
                    "execution_ready": True,
                    "nonce_ready": True,
                    "bootstrap_ready": True,
                },
                {
                    "capital": {
                        "hydrated": True,
                        "stale": True,
                        "real": 240.07,
                        "registered": 2,
                    }
                },
            )

        try:
            v16._collect_proofs = stale_capital_proof
            with patch.object(
                v142,
                "_canonical_broker_connectivity",
                return_value=(
                    True,
                    {
                        "reason": "ok",
                        "policy": "optional",
                        "registered": ["coinbase", "kraken", "okx"],
                        "connected": ["coinbase", "kraken", "okx"],
                    },
                ),
            ):
                self.assertTrue(v142._patch_readiness_truth())
                proofs, details = v16._collect_proofs()

            self.assertTrue(proofs["broker_connected"])
            self.assertTrue(proofs["balance_hydrated"])
            self.assertFalse(proofs["capital_ready"])
            self.assertTrue(details["v142_readiness_truth"]["capital_stale"])
        finally:
            v16._collect_proofs = original

    def test_retired_generation_is_rejected_without_calling_underlying_publish(self) -> None:
        calls: list[tuple[object, str]] = []

        class FakeAuthority:
            _AUTHORIZED_WRITER_ID = "mabm_capital_refresh_coordinator"

            def publish_snapshot(self, snapshot, writer_id):
                calls.append((snapshot, writer_id))
                return True

        fake_ca = types.ModuleType("fake_capital_authority_v142")
        fake_ca.CapitalAuthority = FakeAuthority

        old_active = v142._ACTIVE_GENERATION
        old_next = v142._NEXT_GENERATION
        old_rollover = v142._ROLLOVER_OCCURRED
        prior_local = getattr(v142._LOCAL, "refresh_generation", None)
        had_prior_local = hasattr(v142._LOCAL, "refresh_generation")
        try:
            v142._ACTIVE_GENERATION = 8
            v142._NEXT_GENERATION = 8
            v142._ROLLOVER_OCCURRED = True
            v142._LOCAL.refresh_generation = 7
            with patch.object(v142, "_import_first", return_value=fake_ca):
                self.assertTrue(v142._patch_publication_generation_fence())
                self.assertFalse(
                    FakeAuthority().publish_snapshot(
                        SimpleNamespace(),
                        "mabm_capital_refresh_coordinator",
                    )
                )
            self.assertEqual(calls, [])
        finally:
            v142._ACTIVE_GENERATION = old_active
            v142._NEXT_GENERATION = old_next
            v142._ROLLOVER_OCCURRED = old_rollover
            if had_prior_local:
                v142._LOCAL.refresh_generation = prior_local
            else:
                try:
                    delattr(v142._LOCAL, "refresh_generation")
                except AttributeError:
                    pass

    def test_rollover_reuses_manager_fsm_objects_and_preserves_hydration(self) -> None:
        created: list[object] = []

        class FakeCoordinator:
            def __init__(self, bus, boot, runtime) -> None:
                self._bus = bus
                self._boot = boot
                self._runtime = runtime
                self._in_flight = False
                self.balance_hydrated = False
                import threading
                self.balance_hydrated_event = threading.Event()
                created.append(self)

        fake_flow = types.ModuleType("fake_capital_flow_v142")
        fake_flow.CapitalRefreshCoordinator = FakeCoordinator
        bus = object()
        boot = object()
        runtime = object()
        old = SimpleNamespace(
            _in_flight=True,
            _nija_v142_flight_generation=3,
            _nija_v142_flight_started_monotonic=1.0,
            _nija_v142_flight_trigger="stuck-test",
            _nija_v142_flight_thread=None,
        )
        manager = SimpleNamespace(
            _capital_coordinator=old,
            _capital_event_bus=bus,
            _capital_bootstrap_fsm=boot,
            _capital_runtime_fsm=runtime,
        )

        old_active = v142._ACTIVE_GENERATION
        old_next = v142._NEXT_GENERATION
        old_rollover = v142._ROLLOVER_OCCURRED
        try:
            with (
                patch.object(v142, "_capital_flow_module", return_value=fake_flow),
                patch.object(v142, "_authority", return_value=SimpleNamespace(is_hydrated=True)),
            ):
                replacement = v142._rollover_coordinator(
                    manager,
                    expected_old=old,
                    reason="test_stuck_runtime_refresh",
                )

            self.assertIs(replacement, manager._capital_coordinator)
            self.assertIsNot(replacement, old)
            self.assertIs(replacement._bus, bus)
            self.assertIs(replacement._boot, boot)
            self.assertIs(replacement._runtime, runtime)
            self.assertTrue(replacement.balance_hydrated)
            self.assertTrue(replacement.balance_hydrated_event.is_set())
            self.assertEqual(created, [replacement])
        finally:
            v142._ACTIVE_GENERATION = old_active
            v142._NEXT_GENERATION = old_next
            v142._ROLLOVER_OCCURRED = old_rollover

    def test_upgrade_rolls_untracked_inflight_owner_before_expiry_when_v137_due(self) -> None:
        from bot import capital_publication_deadline_v137_patch as v137

        old = SimpleNamespace(_in_flight=True)
        replacement = SimpleNamespace(_in_flight=False)
        manager = SimpleNamespace(_capital_coordinator=old)
        reasons: list[str] = []

        fake = SimpleNamespace(
            _nija_startup_chain_prepared=False,
            _coordinator_in_flight_v142=lambda manager: True,
            _authority=lambda: SimpleNamespace(),
        )

        def rollover(target_manager, *, expected_old=None, reason):
            self.assertIs(expected_old, old)
            reasons.append(str(reason))
            target_manager._capital_coordinator = replacement
            return replacement

        fake._rollover_coordinator = rollover
        with patch.object(
            v137,
            "_publication_refresh_due",
            return_value=(
                True,
                {
                    "due_reason": "pre_expiry_headroom",
                    "remaining_s": 42.0,
                },
            ),
        ):
            self.assertTrue(_prepare_capital_publication_liveness(fake))
            self.assertFalse(fake._coordinator_in_flight_v142(manager))

        self.assertIs(manager._capital_coordinator, replacement)
        self.assertEqual(reasons, ["untracked_inflight_refresh_due:pre_expiry_headroom"])

    def test_release_manifest_patch_can_be_verified_without_mutating_real_manifest(self) -> None:
        fake_manifest = SimpleNamespace(
            _REQUIRED_FLAGS={},
            _INSTALLERS=(),
            DECLARED_RELEASE_ID="old-release",
            RELEASE_ID="old-release",
        )
        real_import = v142.importlib.import_module

        def fake_import(name: str):
            if name == "bot.runtime_release_manifest_patch":
                return fake_manifest
            return real_import(name)

        with (
            patch.object(v142.importlib, "import_module", side_effect=fake_import),
            patch.dict(os.environ, {}, clear=False),
        ):
            self.assertTrue(v142._patch_release_manifest())
            self.assertEqual(os.environ.get("NIJA_RUNTIME_RELEASE_ID"), v142.RELEASE_ID)

        self.assertEqual(fake_manifest.DECLARED_RELEASE_ID, v142.RELEASE_ID)
        self.assertEqual(fake_manifest.RELEASE_ID, v142.RELEASE_ID)
        self.assertEqual(
            fake_manifest._REQUIRED_FLAGS["capital_publication_liveness_v142"],
            "NIJA_CAPITAL_PUBLICATION_LIVENESS_V142_READY",
        )
        self.assertIn(
            ("bot.capital_publication_liveness_v142_patch", "install_import_hook"),
            fake_manifest._INSTALLERS,
        )


if __name__ == "__main__":
    unittest.main()
