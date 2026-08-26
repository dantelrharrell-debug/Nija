"""Regression tests for heartbeat authenticated-read single-flight retirement v210/v231."""
from __future__ import annotations

import threading
import time
import unittest
from unittest.mock import patch

import bot.runtime_heartbeat_auth_probe_bound_v210_patch as v210


class _Broker:
    pass


class HeartbeatAuthProbeV210Tests(unittest.TestCase):
    def setUp(self) -> None:
        with v210._LOCK:
            # Tests only create bounded fake workers and always release them before
            # teardown. Clear any prior test registry state defensively.
            v210._FLIGHTS.clear()
            v210._FLIGHT_CANCEL.clear()
        self._thread = threading.current_thread()
        self._old_name = self._thread.name

    def tearDown(self) -> None:
        self._thread.name = self._old_name
        deadline = time.time() + 1.0
        while time.time() < deadline:
            with v210._LOCK:
                alive = [worker for worker in v210._FLIGHTS.values() if worker.is_alive()]
            if not alive:
                break
            time.sleep(0.005)
        with v210._LOCK:
            v210._FLIGHTS.clear()
            v210._FLIGHT_CANCEL.clear()

    def _heartbeat_thread(self) -> None:
        self._thread.name = "HeartbeatTrade-Test"

    def test_timeout_keeps_single_flight_until_worker_exits_then_allows_retry(self) -> None:
        broker = _Broker()
        release = threading.Event()
        calls = []

        def read(_self):
            calls.append(time.monotonic())
            release.wait(timeout=1.0)
            return {"balance": 123.45}

        wrapped = v210._wrap_heartbeat_auth_method(
            read,
            broker_class_name="CoinbaseBroker",
            method_name="get_account_balance",
        )
        self._heartbeat_thread()

        with patch.object(v210, "_timeout_s", return_value=0.02):
            with self.assertRaisesRegex(TimeoutError, "timed out"):
                wrapped(broker)

            key = (id(broker), "get_account_balance")
            with v210._LOCK:
                first_worker = v210._FLIGHTS.get(key)
                first_cancel = v210._FLIGHT_CANCEL.get(key)
            self.assertIsNotNone(first_worker)
            self.assertTrue(first_worker.is_alive())
            self.assertIsNotNone(first_cancel)
            self.assertTrue(first_cancel.is_set())

            # The timed-out call is logically cancelled, but a duplicate private
            # read must not start while the exact underlying worker still runs.
            with self.assertRaisesRegex(TimeoutError, "still in flight"):
                wrapped(broker)
            self.assertEqual(len(calls), 1)

            # Once the bounded underlying call exits, its finally block retires
            # the exact registry entry. A later heartbeat may safely start anew.
            release.set()
            first_worker.join(timeout=0.5)
            self.assertFalse(first_worker.is_alive())
            deadline = time.time() + 0.5
            while time.time() < deadline:
                with v210._LOCK:
                    if key not in v210._FLIGHTS:
                        break
                time.sleep(0.005)
            with v210._LOCK:
                self.assertNotIn(key, v210._FLIGHTS)
                self.assertNotIn(key, v210._FLIGHT_CANCEL)

            result = wrapped(broker)
            self.assertEqual(result, {"balance": 123.45})
            self.assertEqual(len(calls), 2)

    def test_kraken_read_bounds_failure_blocks_before_starting_worker(self) -> None:
        broker = _Broker()
        calls = []

        def read(_self):
            calls.append(1)
            return {"balance": 1.0}

        wrapped = v210._wrap_heartbeat_auth_method(
            read,
            broker_class_name="KrakenBroker",
            method_name="get_account_balance",
        )
        self._heartbeat_thread()

        with patch.object(v210, "_reassert_kraken_read_bounds", return_value=False):
            with self.assertRaisesRegex(TimeoutError, "bounded read protections unavailable"):
                wrapped(broker)

        self.assertEqual(calls, [])
        with v210._LOCK:
            self.assertEqual(v210._FLIGHTS, {})
            self.assertEqual(v210._FLIGHT_CANCEL, {})

    def test_non_heartbeat_read_path_is_unchanged(self) -> None:
        broker = _Broker()
        calls = []

        def read(_self, value=7):
            calls.append(value)
            return value

        wrapped = v210._wrap_heartbeat_auth_method(
            read,
            broker_class_name="KrakenBroker",
            method_name="get_account_balance",
        )
        self._thread.name = "MainThread-Test"

        with patch.object(v210, "_reassert_kraken_read_bounds") as reassert:
            self.assertEqual(wrapped(broker, value=9), 9)
        reassert.assert_not_called()
        self.assertEqual(calls, [9])
        with v210._LOCK:
            self.assertEqual(v210._FLIGHTS, {})

    def test_retire_does_not_remove_a_newer_exact_flight(self) -> None:
        broker = _Broker()
        key = (id(broker), "get_account_balance")
        old = threading.Thread(target=lambda: None)
        new = threading.Thread(target=lambda: None)
        with v210._LOCK:
            v210._FLIGHTS[key] = new
            v210._FLIGHT_CANCEL[key] = threading.Event()

        v210._retire_flight(
            key,
            old,
            broker_class_name="KrakenBroker",
            method_name="get_account_balance",
        )

        with v210._LOCK:
            self.assertIs(v210._FLIGHTS.get(key), new)
            self.assertIn(key, v210._FLIGHT_CANCEL)


if __name__ == "__main__":
    unittest.main()
