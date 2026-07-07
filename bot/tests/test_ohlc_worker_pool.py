"""Tests for OHLCWorkerPool: dedupe, backpressure, and singleton worker guards.

These tests validate the three core safety mechanisms introduced to prevent
thread leaks and duplicate background workers in live operation.
"""
from __future__ import annotations

import threading
import time
import unittest
from unittest.mock import patch


class TestOHLCWorkerPoolDedupe(unittest.TestCase):
    """Per-symbol in-flight deduplication."""

    def _make_pool(self, dedupe_ttl: float = 30.0, max_workers: int = 4, queue_maxsize: int = 32):
        from bot.ohlc_worker_pool import OHLCWorkerPool
        return OHLCWorkerPool(
            max_workers=max_workers,
            queue_maxsize=queue_maxsize,
            dedupe_ttl=dedupe_ttl,
            timeout=5.0,
        )

    def test_first_submit_returns_future(self):
        pool = self._make_pool()
        future = pool.submit("BTC-USD", lambda: {"ok": True})
        self.assertIsNotNone(future)
        result = future.result(timeout=5)
        self.assertEqual(result, {"ok": True})

    def test_duplicate_submit_within_ttl_dropped(self):
        pool = self._make_pool(dedupe_ttl=60.0)
        # First submission should succeed
        f1 = pool.submit("ETH-USD", lambda: {"candles": []})
        self.assertIsNotNone(f1)
        f1.result(timeout=5)  # wait for first to register
        # Second submission within TTL should be dropped
        f2 = pool.submit("ETH-USD", lambda: {"candles": []})
        self.assertIsNone(f2, "Duplicate within TTL must return None")

    def test_duplicate_after_ttl_allowed(self):
        pool = self._make_pool(dedupe_ttl=0.05)  # 50 ms TTL
        f1 = pool.submit("SOL-USD", lambda: 42)
        self.assertIsNotNone(f1)
        f1.result(timeout=5)
        time.sleep(0.1)  # wait for TTL to expire
        f2 = pool.submit("SOL-USD", lambda: 99)
        self.assertIsNotNone(f2, "After TTL expiry a new submit must be allowed")

    def test_duplicate_dropped_counter_increments(self):
        pool = self._make_pool(dedupe_ttl=60.0)
        f1 = pool.submit("ADA-USD", lambda: 1)
        self.assertIsNotNone(f1)
        f1.result(timeout=5)
        pool.submit("ADA-USD", lambda: 2)  # duplicate → dropped
        snap = pool.counters().snapshot()
        self.assertGreaterEqual(snap["duplicate_ohlc_dropped"], 1)

    def test_different_symbols_not_deduped(self):
        pool = self._make_pool(dedupe_ttl=60.0)
        fa = pool.submit("LINK-USD", lambda: "link")
        fb = pool.submit("DOT-USD", lambda: "dot")
        self.assertIsNotNone(fa)
        self.assertIsNotNone(fb)

    def test_dedupe_is_thread_safe(self):
        """Concurrent submits for the same symbol: only one should proceed."""
        pool = self._make_pool(dedupe_ttl=60.0)
        results = []
        lock = threading.Lock()

        def _submit():
            f = pool.submit("XRP-USD", lambda: "ok")
            with lock:
                results.append(f)

        threads = [threading.Thread(target=_submit) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        non_none = [r for r in results if r is not None]
        # Only the first submitter should get a future
        self.assertEqual(len(non_none), 1)


class TestOHLCWorkerPoolBackpressure(unittest.TestCase):
    """Queue backpressure: overflow drops instead of creating extra threads."""

    def _make_pool(self, max_workers: int = 2, queue_maxsize: int = 1):
        from bot.ohlc_worker_pool import OHLCWorkerPool
        return OHLCWorkerPool(
            max_workers=max_workers,
            queue_maxsize=queue_maxsize,
            dedupe_ttl=0.0,  # disable dedupe for backpressure tests
            timeout=5.0,
        )

    def test_backpressure_drop_when_queue_full(self):
        """When queue is full, submit returns None and increments counter."""
        barrier = threading.Barrier(2)
        done = threading.Event()

        def _slow():
            barrier.wait()
            done.wait(timeout=10)
            return "slow"

        pool = self._make_pool(max_workers=1, queue_maxsize=1)
        # Fill the executor slot
        f_block = pool.submit("AVAX-USD", _slow)
        barrier.wait()  # ensure worker is running

        # Fill the queue
        pool.submit("LINK-USD", lambda: "q")

        # Now queue is full — next submit should be dropped
        f_drop = pool.submit("SOL-USD", lambda: "dropped")
        self.assertIsNone(f_drop, "Overflow submit must return None (backpressure)")
        snap = pool.counters().snapshot()
        self.assertGreaterEqual(snap["backpressure_dropped"], 1)

        done.set()
        if f_block:
            f_block.result(timeout=5)

    def test_no_thread_created_on_backpressure(self):
        """Thread count must not grow when backpressure drops a task."""
        barrier = threading.Barrier(2)
        done = threading.Event()

        def _slow():
            barrier.wait()
            done.wait(timeout=10)
            return "slow"

        pool = self._make_pool(max_workers=1, queue_maxsize=1)
        f_block = pool.submit("BTC-USD", _slow)
        barrier.wait()
        pool.submit("ETH-USD", lambda: "q")  # fill queue

        before = threading.active_count()
        for i in range(5):
            pool.submit(f"OVERFLOW-{i}", lambda: "x")
        after = threading.active_count()

        # Thread count must not have grown from backpressure drops
        self.assertLessEqual(after, before + 1)  # +1 tolerance for timing

        done.set()
        if f_block:
            f_block.result(timeout=5)


class TestOHLCWorkerPoolHealthGate(unittest.TestCase):
    """Market-data health gate computation."""

    def _make_pool(self):
        from bot.ohlc_worker_pool import OHLCWorkerPool
        return OHLCWorkerPool(max_workers=8, queue_maxsize=32, dedupe_ttl=20.0, timeout=8.0)

    def test_healthy_when_no_activity(self):
        pool = self._make_pool()
        # Fresh pool with no work: workers=0, timeouts=0 — should be healthy
        # (data_age check passes because last_data_ts=0 is treated as "no data yet")
        with patch.dict("os.environ", {
            "NIJA_MAX_OHLC_WORKERS": "8",
            "NIJA_THREAD_SAFE_LIMIT": "500",
            "NIJA_OHLC_MAX_TIMEOUT_RATE": "0.5",
            "NIJA_DATA_STALENESS_SECONDS": "120",
        }):
            healthy, detail = pool.compute_market_data_healthy()
        self.assertTrue(healthy)
        self.assertTrue(detail["workers_ok"])
        self.assertTrue(detail["threads_ok"])
        self.assertTrue(detail["timeout_rate_ok"])

    def test_unhealthy_when_timeout_rate_too_high(self):
        pool = self._make_pool()
        # Manually inject timeouts
        for _ in range(5):
            pool.counters().incr_timeout()
        with patch.dict("os.environ", {
            "NIJA_MAX_OHLC_WORKERS": "8",
            "NIJA_OHLC_MAX_TIMEOUT_RATE": "0.3",  # 5/5 = 1.0 > 0.3 → unhealthy
        }):
            healthy, detail = pool.compute_market_data_healthy()
        self.assertFalse(healthy)
        self.assertFalse(detail["timeout_rate_ok"])


class TestOHLCWorkerPoolSymbolThrottle(unittest.TestCase):
    """Symbol universe throttling."""

    def test_large_list_capped(self):
        from bot.ohlc_worker_pool import throttle_symbol_list
        syms = [f"SYM{i}-USD" for i in range(500)]
        with patch.dict("os.environ", {"NIJA_MAX_SCAN_SYMBOLS": "100"}):
            result = throttle_symbol_list(syms)
        self.assertEqual(len(result), 100)

    def test_order_preserved(self):
        from bot.ohlc_worker_pool import throttle_symbol_list
        syms = [f"SYM{i}-USD" for i in range(200)]
        with patch.dict("os.environ", {"NIJA_MAX_SCAN_SYMBOLS": "50"}):
            result = throttle_symbol_list(syms)
        self.assertEqual(result, syms[:50])

    def test_short_list_unchanged(self):
        from bot.ohlc_worker_pool import throttle_symbol_list
        syms = ["BTC-USD", "ETH-USD"]
        with patch.dict("os.environ", {"NIJA_MAX_SCAN_SYMBOLS": "100"}):
            result = throttle_symbol_list(syms)
        self.assertEqual(result, syms)

    def test_empty_list_uses_shortlist(self):
        from bot.ohlc_worker_pool import throttle_symbol_list, _SAFE_SHORTLIST
        with patch.dict("os.environ", {"NIJA_MAX_SCAN_SYMBOLS": "10"}):
            result = throttle_symbol_list([])
        self.assertEqual(len(result), 10)
        self.assertEqual(result, _SAFE_SHORTLIST[:10])


class TestSingletonWorkerGuard(unittest.TestCase):
    """Process-level singleton guard via ensure_worker_singleton."""

    def setUp(self):
        # Reset the singleton state before each test
        from bot import ohlc_worker_pool as owp
        with owp._WORKER_LOCK:
            owp._WORKER_STARTED.clear()

    def test_first_start_returns_true(self):
        from bot.ohlc_worker_pool import ensure_worker_singleton
        self.assertTrue(ensure_worker_singleton("nija-trailing-stop"))

    def test_second_start_returns_false(self):
        from bot.ohlc_worker_pool import ensure_worker_singleton
        ensure_worker_singleton("nija-trailing-stop")
        result = ensure_worker_singleton("nija-trailing-stop")
        self.assertFalse(result)

    def test_different_workers_independent(self):
        from bot.ohlc_worker_pool import ensure_worker_singleton
        self.assertTrue(ensure_worker_singleton("nija-trailing-stop"))
        self.assertTrue(ensure_worker_singleton("nija-breakeven-stop"))
        self.assertTrue(ensure_worker_singleton("nija-auto-exit-sl-tp"))

    def test_concurrent_start_only_one_wins(self):
        from bot.ohlc_worker_pool import ensure_worker_singleton
        results = []
        lock = threading.Lock()

        def _try():
            ok = ensure_worker_singleton("nija-combo-be-trailing")
            with lock:
                results.append(ok)

        threads = [threading.Thread(target=_try) for _ in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        true_count = sum(1 for r in results if r)
        self.assertEqual(true_count, 1, "Exactly one thread must win the singleton race")


class TestWorkerPatchSingletons(unittest.TestCase):
    """Verify that individual worker patches use process-level guards."""

    def _reset_patch_module(self, module_path: str, attr: str = "_PROCESS_STARTED") -> None:
        import sys
        mod = sys.modules.get(module_path)
        if mod is not None:
            setattr(mod, attr, False)

    def _make_engine(self):
        """Minimal engine stub with required attributes."""
        from types import SimpleNamespace
        engine = SimpleNamespace(
            trade_ledger=None,
            broker_client=None,
            active_exit_orders=set(),
        )
        return engine

    def test_trailing_stop_singleton(self):
        import importlib
        mod = importlib.import_module("bot.trailing_stop_loss_runtime_patch")
        mod._PROCESS_STARTED = False
        engine = self._make_engine()
        # Disable the env flag so the loop exits immediately
        with patch.dict("os.environ", {"NIJA_TRAILING_STOP_ENABLED": "false"}):
            mod._start_monitor(engine)
            mod._start_monitor(engine)
        # Second call is suppressed by process guard — flag should still be False
        # since ENABLED=false causes early return before flag is set
        # (i.e., both calls bail before setting _PROCESS_STARTED)
        self.assertFalse(mod._PROCESS_STARTED)

    def test_trailing_stop_singleton_enabled(self):
        import importlib
        mod = importlib.import_module("bot.trailing_stop_loss_runtime_patch")
        mod._PROCESS_STARTED = False
        engine = self._make_engine()
        started_count = {"n": 0}
        original_thread_start = threading.Thread.start

        def counting_start(self_thread, *a, **kw):
            if getattr(self_thread, "name", "") == "nija-trailing-stop":
                started_count["n"] += 1
            original_thread_start(self_thread, *a, **kw)

        with patch.object(threading.Thread, "start", counting_start):
            with patch.dict("os.environ", {"NIJA_TRAILING_STOP_ENABLED": "true"}):
                mod._start_monitor(engine)
                mod._start_monitor(engine)

        self.assertEqual(started_count["n"], 1, "Trailing stop worker must start at most once")


if __name__ == "__main__":
    unittest.main()
