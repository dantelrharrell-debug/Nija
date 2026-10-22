"""Offline regression for synchronous capital publication generation fencing."""
from __future__ import annotations

import importlib.util
from pathlib import Path
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch


SOURCE = Path(__file__).resolve().parents[1] / "bot" / "capital_publication_liveness_v142_patch.py"


class CapitalSyncGenerationTests(unittest.TestCase):
    """Exercise actual execute/publish wrappers without importing trading startup."""

    def setUp(self) -> None:
        spec = importlib.util.spec_from_file_location(
            "bot.capital_publication_liveness_v142_patch", SOURCE,
        )
        self.v142 = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.v142)
        self.published = []

        class Authority:
            _AUTHORIZED_WRITER_ID = "mabm_capital_refresh_coordinator"

            def publish_snapshot(inner, snapshot, writer_id):
                self.published.append(snapshot)
                return True

        self.authority = Authority()
        self.ca = SimpleNamespace(CapitalAuthority=Authority)
        with patch.object(self.v142, "_import_first", return_value=self.ca):
            self.assertTrue(self.v142._patch_publication_generation_fence())

    def _coordinator(self, pipeline):
        class Coordinator:
            def __init__(inner):
                inner._lock = threading.Lock()
                inner._in_flight = False
                inner._boot = SimpleNamespace(is_owner_thread=lambda: True)
                inner._pipeline = lambda broker_map, trigger, open_exposure_usd: pipeline(inner)

            def execute_refresh(inner, broker_map, trigger="coordinator", open_exposure_usd=0.0):
                with inner._lock:
                    if inner._in_flight:
                        return None
                    inner._in_flight = True
                try:
                    return pipeline(inner)
                finally:
                    with inner._lock:
                        inner._in_flight = False

        with (
            patch.object(self.v142, "_capital_flow_module", return_value=SimpleNamespace(
                CapitalRefreshCoordinator=Coordinator,
            )),
            patch.object(self.v142, "_reassert_bounded_fetch_contract", return_value=(True, "ok")),
            patch.object(self.v142, "_runtime_terminal", return_value=False),
        ):
            self.assertTrue(self.v142._patch_coordinator_execute())
        self.v142._reassert_bounded_fetch_contract = lambda: (True, "ok")
        self.v142._runtime_terminal = lambda _: False
        return Coordinator()

    def _publish(self):
        return self.authority.publish_snapshot(object(), self.authority._AUTHORIZED_WRITER_ID)

    def test_new_sync_refresh_can_publish_after_rollover(self) -> None:
        self.v142._retire_generation(None, "test_previous_timeout")
        coordinator = self._coordinator(lambda _: self._publish())
        self.assertTrue(coordinator.execute_refresh({}))
        self.assertEqual(len(self.published), 1)
        self.assertIsNone(coordinator._nija_v142_sync_owner_thread)
        self.assertFalse(hasattr(self.v142._LOCAL, "refresh_generation"))

    def test_retired_sync_generation_cannot_publish(self) -> None:
        def pipeline(coordinator):
            generation = getattr(coordinator, "_nija_v142_sync_generation", None)
            self.assertIsInstance(generation, int)
            self.v142._retire_generation(generation, "test_deadline")
            return self._publish()

        coordinator = self._coordinator(pipeline)
        self.assertFalse(coordinator.execute_refresh({}))
        self.assertEqual(self.published, [])

    def test_prior_thread_context_is_restored(self) -> None:
        self.v142._LOCAL.refresh_generation = 47
        coordinator = self._coordinator(lambda _: self._publish())
        self.assertTrue(coordinator.execute_refresh({}))
        self.assertEqual(self.v142._LOCAL.refresh_generation, 47)

    def test_exception_restores_context_and_owner(self) -> None:
        def failing(_):
            raise RuntimeError("pipeline_failed")

        self.v142._LOCAL.refresh_generation = 47
        coordinator = self._coordinator(failing)
        with self.assertRaisesRegex(RuntimeError, "pipeline_failed"):
            coordinator.execute_refresh({})
        self.assertEqual(self.v142._LOCAL.refresh_generation, 47)
        self.assertIsNone(coordinator._nija_v142_sync_owner_thread)
        self.assertFalse(coordinator._in_flight)

    def test_duplicate_does_not_take_over_or_allocate_generation(self) -> None:
        coordinator = self._coordinator(lambda _: self.fail("duplicate reached pipeline"))
        coordinator._nija_v142_sync_owner_thread = threading.current_thread()
        self.assertIsNone(coordinator.execute_refresh({}))
        self.assertEqual(self.v142._ACTIVE_GENERATION, 0)
        self.assertIs(coordinator._nija_v142_sync_owner_thread, threading.current_thread())

    def test_sequential_refreshes_have_distinct_generations(self) -> None:
        generations = []

        def pipeline(coordinator):
            generations.append(getattr(coordinator, "_nija_v142_sync_generation", None))
            return self._publish()

        coordinator = self._coordinator(pipeline)
        self.assertTrue(coordinator.execute_refresh({}))
        self.assertTrue(coordinator.execute_refresh({}))
        self.assertIsInstance(generations[0], int)
        self.assertGreater(generations[1], generations[0])

    def test_untagged_publish_still_denied_after_rollover(self) -> None:
        self.v142._retire_generation(None, "test_previous_timeout")
        self.assertFalse(self._publish())
        self.assertEqual(self.published, [])

    def test_concurrent_duplicate_cannot_invalidate_live_owner(self) -> None:
        entered = threading.Event()
        release = threading.Event()
        results = []

        def pipeline(_):
            entered.set()
            self.assertTrue(release.wait(timeout=3))
            return self._publish()

        coordinator = self._coordinator(pipeline)
        worker = threading.Thread(target=lambda: results.append(coordinator.execute_refresh({})))
        worker.start()
        try:
            self.assertTrue(entered.wait(timeout=3))
            generation = self.v142._ACTIVE_GENERATION
            self.assertIsNone(coordinator.execute_refresh({}))
            self.assertEqual(self.v142._ACTIVE_GENERATION, generation)
        finally:
            release.set()
            worker.join(timeout=3)
        self.assertFalse(worker.is_alive())
        self.assertEqual(results, [True])
        self.assertEqual(len(self.published), 1)

    def test_nonowner_preterminal_refresh_uses_bounded_worker(self) -> None:
        """BOOT_IDLE alone must not force watchdog calls onto synchronous bootstrap."""
        entered = threading.Event()
        release = threading.Event()

        def slow_pipeline(_):
            entered.set()
            self.assertTrue(release.wait(timeout=3))
            return self._publish()

        coordinator = self._coordinator(slow_pipeline)
        coordinator._boot = SimpleNamespace(is_owner_thread=lambda: False)
        with (
            patch.object(self.v142, "_runtime_deadline_with_caller_context_v142", return_value=0.05),
            patch.object(self.v142, "_canonical_manager", return_value=None),
        ):
            try:
                self.assertIsNone(coordinator.execute_refresh({}, trigger="watchdog"))
                self.assertTrue(entered.is_set())
                self.assertEqual(self.published, [])
                self.assertIsNone(getattr(coordinator, "_nija_v142_sync_owner_thread", None))
                self.assertTrue(coordinator._nija_v142_flight_timed_out)
            finally:
                release.set()
                coordinator._nija_v142_flight_thread.join(timeout=3)
        self.assertFalse(coordinator._nija_v142_flight_thread.is_alive())
        self.assertEqual(self.published, [])

    def test_nonowner_refresh_cannot_claim_bootstrap_thread(self) -> None:
        coordinator = self._coordinator(lambda _: self._publish())
        coordinator._boot = SimpleNamespace(is_owner_thread=lambda: False)
        self.assertFalse(self.v142._caller_owns_bootstrap(coordinator))
        coordinator._boot = SimpleNamespace(is_owner_thread=lambda: (_ for _ in ()).throw(RuntimeError("unavailable")))
        self.assertFalse(self.v142._caller_owns_bootstrap(coordinator))
        coordinator._boot = SimpleNamespace(is_owner_thread=lambda: True)
        self.assertTrue(self.v142._caller_owns_bootstrap(coordinator))

    def test_rollover_retires_exact_sync_generation(self) -> None:
        old = SimpleNamespace(_nija_v142_sync_generation=7)
        manager = SimpleNamespace(_capital_coordinator=old)
        with (
            patch.object(self.v142, "_retire_generation") as retire,
            patch.object(self.v142, "_capital_flow_module", return_value=SimpleNamespace()),
        ):
            self.assertIsNone(self.v142._rollover_coordinator(
                manager, expected_old=old, reason="test_sync_timeout",
            ))
        retire.assert_called_once_with(7, "test_sync_timeout")


if __name__ == "__main__":
    unittest.main()
