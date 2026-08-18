from __future__ import annotations

import importlib.util
import threading
import types
import unittest
from collections import namedtuple
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
PATCH_PATH = ROOT / "bot" / "runtime_startup_convergence_v145_patch.py"
SPEC = importlib.util.spec_from_file_location("runtime_startup_convergence_v145_under_test", PATCH_PATH)
assert SPEC is not None and SPEC.loader is not None
v145 = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(v145)


Observation = namedtuple(
    "Observation",
    "value observed_monotonic observed_epoch sequence",
)
Flight = namedtuple(
    "Flight",
    "thread result_queue sequence started_monotonic timeout_s",
)


class AliveThread:
    def __init__(self, alive: bool = True) -> None:
        self.alive = alive

    def is_alive(self) -> bool:
        return self.alive


class RuntimeStartupConvergenceV145Tests(unittest.TestCase):
    def _guard(self) -> types.ModuleType:
        guard = types.ModuleType("fake_capital_guard")
        guard._IN_FLIGHT = {}
        guard._IN_FLIGHT_LOCK = threading.Lock()
        guard._BROKER_SEQUENCE = {}
        guard._OBSERVATIONS = {}
        guard._OBSERVATION_LOCK = threading.Lock()
        guard._Observation = Observation
        return guard

    def test_alive_flight_before_deadline_is_reusable(self) -> None:
        flight = Flight(AliveThread(True), None, 4, 100.0, 75.0)
        self.assertFalse(v145._expired_alive_flight(flight, now=174.999))

    def test_alive_flight_at_deadline_is_expired(self) -> None:
        flight = Flight(AliveThread(True), None, 4, 100.0, 75.0)
        self.assertTrue(v145._expired_alive_flight(flight, now=175.0))

    def test_dead_thread_is_not_classified_as_expired_alive(self) -> None:
        flight = Flight(AliveThread(False), None, 4, 100.0, 75.0)
        self.assertFalse(v145._expired_alive_flight(flight, now=1000.0))

    def test_expired_flight_is_evicted_and_sequence_fenced(self) -> None:
        guard = self._guard()
        old = Flight(AliveThread(True), None, 5, 100.0, 75.0)
        guard._IN_FLIGHT["kraken"] = old
        guard._BROKER_SEQUENCE["kraken"] = 5

        changed = v145._fence_expired_flight(guard, "kraken", now=180.0)

        self.assertTrue(changed)
        self.assertNotIn("kraken", guard._IN_FLIGHT)
        self.assertEqual(guard._BROKER_SEQUENCE["kraken"], 6)
        fence = guard._OBSERVATIONS["kraken"]
        self.assertEqual(fence.sequence, 6)
        self.assertEqual(fence.value, 0.0)
        self.assertEqual(fence.observed_monotonic, 0.0)
        self.assertEqual(fence.observed_epoch, 0.0)

    def test_expired_flight_preserves_prior_observation_but_advances_sequence(self) -> None:
        guard = self._guard()
        guard._IN_FLIGHT["kraken"] = Flight(AliveThread(True), None, 9, 100.0, 75.0)
        guard._BROKER_SEQUENCE["kraken"] = 9
        guard._OBSERVATIONS["kraken"] = Observation(154.49, 90.0, 1000.0, 8)

        self.assertTrue(v145._fence_expired_flight(guard, "kraken", now=180.0))
        fenced = guard._OBSERVATIONS["kraken"]
        self.assertEqual(fenced.value, 154.49)
        self.assertEqual(fenced.observed_monotonic, 90.0)
        self.assertEqual(fenced.observed_epoch, 1000.0)
        self.assertEqual(fenced.sequence, 10)

    def test_late_superseded_worker_cannot_overwrite_fence(self) -> None:
        guard = self._guard()
        old_seq = 5
        guard._IN_FLIGHT["kraken"] = Flight(AliveThread(True), None, old_seq, 100.0, 75.0)
        guard._BROKER_SEQUENCE["kraken"] = old_seq
        self.assertTrue(v145._fence_expired_flight(guard, "kraken", now=180.0))

        # Mirror the existing worker's guarded observation publication rule.
        previous = guard._OBSERVATIONS.get("kraken")
        if previous is None or old_seq >= previous.sequence:
            guard._OBSERVATIONS["kraken"] = Observation(999.0, 181.0, 2000.0, old_seq)

        fenced = guard._OBSERVATIONS["kraken"]
        self.assertEqual(fenced.sequence, 6)
        self.assertEqual(fenced.value, 0.0)

    def test_nonexpired_flight_is_not_evicted(self) -> None:
        guard = self._guard()
        old = Flight(AliveThread(True), None, 3, 100.0, 75.0)
        guard._IN_FLIGHT["kraken"] = old
        guard._BROKER_SEQUENCE["kraken"] = 3

        self.assertFalse(v145._fence_expired_flight(guard, "kraken", now=150.0))
        self.assertIs(guard._IN_FLIGHT["kraken"], old)
        self.assertEqual(guard._BROKER_SEQUENCE["kraken"], 3)
        self.assertNotIn("kraken", guard._OBSERVATIONS)

    def test_batch_patch_removes_expired_flight_before_original_constructor(self) -> None:
        guard = self._guard()
        observed = {"stale_present_in_original": None}

        class Batch:
            def __init__(self, broker_map):
                observed["stale_present_in_original"] = "kraken" in guard._IN_FLIGHT
                self.broker_map = broker_map

        guard._BalanceFetchBatch = Batch
        guard._IN_FLIGHT["kraken"] = Flight(AliveThread(True), None, 7, 100.0, 10.0)
        guard._BROKER_SEQUENCE["kraken"] = 7

        self.assertTrue(v145._patch_capital_guard(guard))
        with patch.object(v145.time, "monotonic", return_value=120.0):
            Batch({"kraken": object()})

        self.assertFalse(observed["stale_present_in_original"])
        self.assertGreater(guard._BROKER_SEQUENCE["kraken"], 7)

    def test_activation_deferral_coalescing_never_changes_decision_path(self) -> None:
        module = types.ModuleType("fake_activation")
        calls = []

        def log_deferred(trigger, blockers, details):
            calls.append((trigger, tuple(blockers), dict(details)))

        module._log_activation_deferred = log_deferred
        self.assertTrue(v145._patch_activation_deferral(module))
        details = {
            "generation": 4238,
            "bootstrap_state": "THREADS_STARTING",
            "core_registered": False,
            "core_alive": False,
        }
        with patch.dict("os.environ", {"NIJA_ACTIVATION_DEFER_LOG_INTERVAL_S": "15"}, clear=False):
            with patch.object(v145.time, "monotonic", side_effect=[100.0, 101.0, 116.0]):
                module._log_activation_deferred("v15", ["core_registered"], details)
                module._log_activation_deferred("v15", ["core_registered"], details)
                module._log_activation_deferred("v15", ["core_registered"], details)

        self.assertEqual(len(calls), 2)


if __name__ == "__main__":
    unittest.main()
