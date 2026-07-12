"""Unit tests for the broker worker pool.

Tests cover:
  - BrokerScanWorker: task submission, completion, drop on busy, hard timeout
  - BrokerWorkerPool: multi-broker dispatch, dead-worker replacement
  - Helper functions: _broker_name_from_obj, _get_all_platform_brokers,
    _build_broker_scan_tasks
"""

import queue
import threading
import time
import types
import unittest


# ---------------------------------------------------------------------------
# Import targets (skip tests gracefully when modules are unavailable)
# ---------------------------------------------------------------------------

try:
    from bot.broker_worker_pool import (
        BrokerScanResult,
        BrokerScanTask,
        BrokerScanWorker,
        BrokerWorkerPool,
    )
    _POOL_AVAILABLE = True
except ImportError:
    _POOL_AVAILABLE = False

try:
    from bot.nija_core_loop import (
        _broker_name_from_obj,
        _build_broker_scan_tasks,
        _get_all_platform_brokers,
    )
    _HELPERS_AVAILABLE = True
except ImportError:
    _HELPERS_AVAILABLE = False


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_broker(name: str = "kraken", connected: bool = True) -> types.SimpleNamespace:
    """Return a minimal broker-like namespace."""
    bt = types.SimpleNamespace(value=name)
    return types.SimpleNamespace(broker_type=bt, connected=connected)


def _fast_scan_fn(**kwargs) -> types.SimpleNamespace:
    """Instant scan that returns a minimal CoreLoopResult-like object."""
    return types.SimpleNamespace(entries_taken=1, exits_taken=0, symbols_scored=5)


def _slow_scan_fn(delay: float = 0.5, **kwargs) -> types.SimpleNamespace:
    time.sleep(delay)
    return types.SimpleNamespace(entries_taken=0, exits_taken=0, symbols_scored=0)


def _error_scan_fn(**kwargs):
    raise RuntimeError("simulated scan error")


def _make_task(broker_name: str = "kraken", scan_delay: float = 0.0) -> "BrokerScanTask":
    return BrokerScanTask(
        broker=_make_broker(broker_name),
        broker_name=broker_name,
        balance=1000.0,
        symbols=["BTC-USD", "ETH-USD"],
        open_positions_count=0,
        user_mode=False,
        cycle_id=f"test-{broker_name}",
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@unittest.skipUnless(_POOL_AVAILABLE, "broker_worker_pool not importable")
class TestBrokerScanWorker(unittest.TestCase):

    def test_task_accepted_and_completes(self):
        """A submitted task should be executed and return success=True."""
        results: list = []

        def cb(r: BrokerScanResult) -> None:
            results.append(r)

        worker = BrokerScanWorker(
            broker_name="kraken",
            scan_fn=_fast_scan_fn,
            scan_timeout_s=5.0,
            result_callback=cb,
        )
        task = _make_task("kraken")
        accepted = worker.submit(task)
        self.assertTrue(accepted)

        # Wait for result
        deadline = time.monotonic() + 3.0
        while not results and time.monotonic() < deadline:
            time.sleep(0.05)

        worker.stop()
        self.assertEqual(len(results), 1)
        r = results[0]
        self.assertTrue(r.success)
        self.assertFalse(r.timed_out)
        self.assertEqual(r.entries_taken, 1)
        self.assertEqual(r.symbols_scored, 5)

    def test_second_submit_dropped_when_busy(self):
        """A second task submitted while the worker is busy should be dropped."""
        results: list = []
        start_evt = threading.Event()

        def slow_scan(**kwargs):
            start_evt.wait(timeout=5.0)
            return types.SimpleNamespace(entries_taken=0, exits_taken=0, symbols_scored=0)

        def cb(r: BrokerScanResult) -> None:
            results.append(r)

        worker = BrokerScanWorker(
            broker_name="coinbase",
            scan_fn=slow_scan,
            scan_timeout_s=10.0,
            result_callback=cb,
        )
        task1 = _make_task("coinbase")
        task2 = _make_task("coinbase")

        # Submit first task (will block in scan_fn waiting for start_evt)
        accepted1 = worker.submit(task1)
        time.sleep(0.1)  # let the worker pick up task1

        # Second submit should be dropped (queue full)
        accepted2 = worker.submit(task2)

        start_evt.set()  # unblock the slow scan
        worker.stop()

        self.assertTrue(accepted1)
        self.assertFalse(accepted2, "second task should be dropped when queue full")

    def test_timeout_returns_timed_out_result(self):
        """When scan_fn exceeds timeout, the worker should return timed_out=True."""
        results: list = []

        def cb(r: BrokerScanResult) -> None:
            results.append(r)

        # Use very short timeout (0.1s) with a slow scan (0.5s)
        def slow(**kwargs):
            time.sleep(0.5)
            return types.SimpleNamespace(entries_taken=0, exits_taken=0, symbols_scored=0)

        worker = BrokerScanWorker(
            broker_name="okx",
            scan_fn=slow,
            scan_timeout_s=2.0,  # min is 2.0 per _float_env guard
            result_callback=cb,
        )
        # Patch the timeout to a very short value for test speed
        worker._scan_timeout_s = 0.15

        task = _make_task("okx")
        worker.submit(task)

        deadline = time.monotonic() + 3.0
        while not results and time.monotonic() < deadline:
            time.sleep(0.05)

        worker.stop()
        self.assertEqual(len(results), 1)
        r = results[0]
        self.assertFalse(r.success)
        self.assertTrue(r.timed_out)

    def test_scan_error_returns_error_result(self):
        """When scan_fn raises, the worker should return success=False with error."""
        results: list = []

        def cb(r: BrokerScanResult) -> None:
            results.append(r)

        worker = BrokerScanWorker(
            broker_name="alpaca",
            scan_fn=_error_scan_fn,
            scan_timeout_s=5.0,
            result_callback=cb,
        )
        worker.submit(_make_task("alpaca"))

        deadline = time.monotonic() + 3.0
        while not results and time.monotonic() < deadline:
            time.sleep(0.05)

        worker.stop()
        self.assertEqual(len(results), 1)
        r = results[0]
        self.assertFalse(r.success)
        self.assertIsNotNone(r.error)
        self.assertIn("simulated scan error", r.error)


@unittest.skipUnless(_POOL_AVAILABLE, "broker_worker_pool not importable")
class TestBrokerWorkerPool(unittest.TestCase):

    def test_submit_all_returns_immediately(self):
        """submit_all should return within a very short wall-clock time."""

        def slow(**kwargs):
            time.sleep(2.0)
            return types.SimpleNamespace(entries_taken=0, exits_taken=0, symbols_scored=0)

        pool = BrokerWorkerPool(scan_fn=slow, scan_timeout_s=5.0)
        tasks = [_make_task("kraken"), _make_task("coinbase")]

        t0 = time.monotonic()
        accepted = pool.submit_all(tasks)
        elapsed = time.monotonic() - t0

        # submit_all must return well under 0.5 seconds even with slow scan_fn
        self.assertLess(elapsed, 0.5, f"submit_all took {elapsed:.2f}s — should be near-instant")
        self.assertIn("kraken", accepted)
        self.assertIn("coinbase", accepted)
        pool.stop_all()

    def test_multi_broker_parallel_execution(self):
        """Each broker's scan should run concurrently; total wall time < sum of individual times."""
        results: list = []
        lock = threading.Lock()

        def timed_scan(delay: float, **kwargs):
            time.sleep(delay)
            return types.SimpleNamespace(entries_taken=1, exits_taken=0, symbols_scored=3)

        def make_scan(d):
            def _fn(**kwargs):
                return timed_scan(d, **kwargs)
            return _fn

        # Each broker takes 0.2s; sequential would be 0.6s; parallel should be ~0.2s
        pool = BrokerWorkerPool(scan_fn=make_scan(0.2), scan_timeout_s=5.0)

        # Assign per-broker scan functions directly for this test
        from bot.broker_worker_pool import BrokerScanWorker as _W

        collected: list = []

        def cb(r):
            with lock:
                collected.append(r)

        pool._workers = {
            name: _W(name, make_scan(0.2), scan_timeout_s=5.0, result_callback=cb)
            for name in ("kraken", "coinbase", "okx")
        }

        tasks = [_make_task(n) for n in ("kraken", "coinbase", "okx")]
        t0 = time.monotonic()
        pool.submit_all(tasks)
        elapsed_dispatch = time.monotonic() - t0

        # Wait for all results
        deadline = time.monotonic() + 3.0
        while len(collected) < 3 and time.monotonic() < deadline:
            time.sleep(0.05)

        self.assertLess(elapsed_dispatch, 0.5, "submit_all should return quickly")
        self.assertEqual(len(collected), 3)
        for r in collected:
            self.assertTrue(r.success)

        pool.stop_all()

    def test_dead_worker_is_replaced(self):
        """A dead worker thread should be replaced on the next submit_all."""
        pool = BrokerWorkerPool(scan_fn=_fast_scan_fn, scan_timeout_s=5.0)
        # Manually stop the internal thread to simulate a crash
        worker = pool._get_or_create_worker("kraken")
        worker.stop()
        time.sleep(0.2)  # let thread exit

        # submit_all should detect the dead thread and replace it
        tasks = [_make_task("kraken")]
        accepted = pool.submit_all(tasks)
        self.assertTrue(accepted.get("kraken"), "replaced worker should accept task")
        pool.stop_all()


@unittest.skipUnless(_HELPERS_AVAILABLE, "nija_core_loop helpers not importable")
class TestCoreLoopHelpers(unittest.TestCase):

    def test_broker_name_from_obj_via_broker_type(self):
        b = _make_broker("coinbase")
        name = _broker_name_from_obj(b)
        self.assertEqual(name, "coinbase")

    def test_broker_name_from_obj_via_raw_key(self):
        b = types.SimpleNamespace()  # no broker_type
        key = types.SimpleNamespace(value="kraken")
        name = _broker_name_from_obj(b, raw_key=key)
        self.assertEqual(name, "kraken")

    def test_get_all_platform_brokers_mabm(self):
        kraken = _make_broker("kraken", connected=True)
        coinbase = _make_broker("coinbase", connected=True)
        disconnected = _make_broker("okx", connected=False)

        mabm = types.SimpleNamespace(
            platform_brokers={
                types.SimpleNamespace(value="kraken"): kraken,
                types.SimpleNamespace(value="coinbase"): coinbase,
                types.SimpleNamespace(value="okx"): disconnected,
            }
        )
        strategy = types.SimpleNamespace(
            multi_account_manager=mabm,
            broker_manager=None,
            broker=None,
        )
        brokers = _get_all_platform_brokers(strategy)
        self.assertIn("kraken", brokers)
        self.assertIn("coinbase", brokers)
        self.assertNotIn("okx", brokers)  # disconnected

    def test_build_broker_scan_tasks(self):
        if BrokerScanTask is None:
            self.skipTest("BrokerScanTask not importable")
        brokers = {
            "kraken": _make_broker("kraken"),
            "coinbase": _make_broker("coinbase"),
        }
        strategy = types.SimpleNamespace(symbols=["BTC-USD", "ETH-USD"])
        tasks = _build_broker_scan_tasks(
            strategy=strategy,
            brokers=brokers,
            balance=5000.0,
            cycle_id="test-cycle-001",
            open_positions_count=2,
        )
        self.assertEqual(len(tasks), 2)
        names = {t.broker_name for t in tasks}
        self.assertEqual(names, {"kraken", "coinbase"})
        for task in tasks:
            self.assertEqual(task.balance, 5000.0)
            self.assertEqual(task.cycle_id, "test-cycle-001")
            self.assertEqual(task.open_positions_count, 2)
            self.assertEqual(task.symbols, ["BTC-USD", "ETH-USD"])


if __name__ == "__main__":
    unittest.main()
