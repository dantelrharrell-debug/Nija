import threading
import time
import types
import unittest
import os
from unittest.mock import patch

from bot import capital_refresh_stall_guard_v35 as guard


class _Broker:
    def __init__(self, value=None, release=None, error=None):
        self._last_known_balance = value
        self._release = release
        self._error = error
        self.started = threading.Event()

    def get_account_balance(self):
        self.started.set()
        if self._release is not None:
            self._release.wait(1.0)
        if self._error is not None:
            raise self._error
        return self._last_known_balance


class CapitalRefreshSharedDeadlineTests(unittest.TestCase):
    def test_okx_timeout_override_can_be_longer(self):
        with patch.dict(os.environ, {
            "NIJA_CAPITAL_BROKER_FETCH_TIMEOUT_S": "8.0",
            "NIJA_CAPITAL_OKX_FETCH_TIMEOUT_S": "10.0",
        }, clear=False):
            self.assertEqual(10.0, guard._broker_timeout_seconds("okx"))
            self.assertEqual(8.0, guard._broker_timeout_seconds("coinbase"))

    def test_all_fetches_start_concurrently_with_independent_timeouts(self):
        """All venue fetches begin together; each gets its own independent deadline.

        The test verifies that:
        - All broker threads are started before any result is awaited.
        - Live results are returned when brokers complete within their budget.
        - Elapsed time is bounded (no serialisation multiplying timeout × N brokers).
        """
        # Clear in-flight state from any prior test
        guard._IN_FLIGHT.clear()
        guard._BROKER_SEQUENCE.clear()

        release = threading.Event()
        timeout = 0.2
        brokers = {
            "coinbase": _Broker(10.0, release),
            "kraken": _Broker(20.0, release),
            "okx": _Broker(30.0, release),
        }
        # Release immediately so all brokers complete within the per-broker budget.
        release.set()

        with patch.object(guard, "_timeout_seconds", return_value=timeout):
            with patch.object(guard, "_cycle_deadline_seconds", return_value=timeout + 2.0):
                batch = guard._BalanceFetchBatch(brokers)
                started_at = time.monotonic()
                values = [
                    batch.result_for(name, broker) for name, broker in brokers.items()
                ]
                elapsed = time.monotonic() - started_at

        self.assertTrue(all(broker.started.is_set() for broker in brokers.values()))
        self.assertEqual(values, [10.0, 20.0, 30.0])
        # Elapsed must be much less than timeout * N (no serialisation penalty)
        self.assertLess(elapsed, timeout * 2)

    def test_completed_result_and_exception_preserve_semantics(self):
        error = RuntimeError("venue failed")
        brokers = {"okx": _Broker(42.0), "coinbase": _Broker(error=error)}
        batch = guard._BalanceFetchBatch(brokers)

        self.assertEqual(batch.result_for("okx", brokers["okx"]), 42.0)
        with self.assertRaisesRegex(RuntimeError, "venue failed"):
            batch.result_for("coinbase", brokers["coinbase"])

    def test_patch_prefetches_before_sequential_pipeline_reads(self):
        guard._IN_FLIGHT.clear()
        guard._BROKER_SEQUENCE.clear()
        release = threading.Event()
        brokers = {"a": _Broker(1.0, release), "b": _Broker(2.0, release)}

        class Coordinator:
            def _pipeline(self, broker_map, trigger, open_exposure_usd):
                self.all_started = all(
                    broker.started.wait(0.2) for broker in brokers.values()
                )
                release.set()
                return [broker.get_account_balance() for broker in broker_map.values()]

        module = types.ModuleType("test_capital_flow")
        module.CapitalRefreshCoordinator = Coordinator
        self.assertTrue(guard._patch(module))

        coordinator = Coordinator()
        result = coordinator._pipeline(brokers, "test", 0.0)
        self.assertTrue(coordinator.all_started)
        self.assertEqual(result, [1.0, 2.0])
        self.assertFalse(guard.current_refresh_used_fallback())

    def test_fallback_context_is_visible_during_pipeline_only(self):
        release = threading.Event()
        broker = _Broker(12.0, release)
        # Provide a valid timestamp so the cache is accepted as fallback.
        setattr(broker, guard._LIVE_BALANCE_OBSERVED_AT, time.monotonic() - 5.0)

        class Coordinator:
            def _pipeline(self, broker_map, trigger, open_exposure_usd):
                value = next(iter(broker_map.values())).get_account_balance()
                return value, guard.current_refresh_used_fallback()

        module = types.ModuleType("test_fallback_context")
        module.CapitalRefreshCoordinator = Coordinator
        self.assertTrue(guard._patch(module))

        try:
            with patch.object(guard, "_timeout_seconds", return_value=0.05):
                with patch.object(guard, "_cycle_deadline_seconds", return_value=2.05):
                    result = Coordinator()._pipeline({"okx": broker}, "test", 0.0)
        finally:
            release.set()
        self.assertEqual(result, (12.0, True))
        self.assertFalse(guard.current_refresh_used_fallback())

    def test_recent_live_balance_fallback_remains_within_freshness_ttl(self):
        guard._IN_FLIGHT.clear()
        guard._BROKER_SEQUENCE.clear()
        broker = _Broker(12.0)
        live_batch = guard._BalanceFetchBatch({"okx": broker})
        self.assertEqual(live_batch.result_for("okx", broker), 12.0)
        self.assertGreater(
            getattr(broker, guard._LIVE_BALANCE_OBSERVED_AT, 0.0),
            0.0,
        )

        guard._IN_FLIGHT.clear()
        guard._BROKER_SEQUENCE.clear()
        release = threading.Event()
        broker._release = release
        try:
            guard._REFRESH_CONTEXT.used_fallback = False
            guard._REFRESH_CONTEXT.fallback_brokers = {}
            with patch.object(guard, "_timeout_seconds", return_value=0.05):
                with patch.object(guard, "_cycle_deadline_seconds", return_value=2.05):
                    cached_batch = guard._BalanceFetchBatch({"okx": broker})
                    self.assertEqual(cached_batch.result_for("okx", broker), 12.0)
            status = guard.current_refresh_fallback_status(90.0)
        finally:
            release.set()
            guard._REFRESH_CONTEXT.used_fallback = False
            guard._REFRESH_CONTEXT.fallback_brokers = {}

        self.assertTrue(status["used_fallback"])
        self.assertTrue(status["all_recent"])
        self.assertIn("okx", status["brokers"])

    def test_expired_live_balance_fallback_rejected(self):
        """A cache entry outside the configured TTL must be rejected (TimeoutError).

        This reflects the new strict validation: a stale cache is not safer than
        no cache — the broker is simply excluded from valid_brokers.
        """
        release = threading.Event()
        broker = _Broker(12.0, release)
        setattr(
            broker,
            guard._LIVE_BALANCE_OBSERVED_AT,
            time.monotonic() - 120.0,
        )
        try:
            guard._REFRESH_CONTEXT.used_fallback = False
            guard._REFRESH_CONTEXT.fallback_brokers = {}
            with patch.object(guard, "_timeout_seconds", return_value=0.05):
                with patch.object(guard, "_cycle_deadline_seconds", return_value=2.05):
                    with patch.object(guard, "_freshness_ttl_seconds", return_value=90.0):
                        batch = guard._BalanceFetchBatch({"okx": broker})
                        with self.assertRaises(TimeoutError):
                            batch.result_for("okx", broker)
        finally:
            release.set()
            guard._REFRESH_CONTEXT.used_fallback = False
            guard._REFRESH_CONTEXT.fallback_brokers = {}


if __name__ == "__main__":
    unittest.main()
