"""Bounded OHLC worker pool with dedupe, backpressure, health gates, and telemetry.

This module replaces the unbounded ``threading.Thread``-per-symbol pattern that
caused thousands of stalled ``_fetch_ohlc`` threads in live operation.

Key capabilities
----------------
* **Bounded concurrency** — ``ThreadPoolExecutor`` with ``NIJA_MAX_OHLC_WORKERS``
  (default 8) workers.  No fallback path that spawns extra threads.
* **Per-symbol in-flight dedupe** — if the same symbol already has an OHLC
  request running (or completed within ``NIJA_OHLC_DEDUPE_TTL_SECONDS``, default
  20 s), the duplicate is dropped and ``OHLC_DUPLICATE_DROPPED`` is logged.
* **Bounded queue with backpressure** — the internal task queue is capped;
  overflow tasks are dropped with ``OHLC_BACKPRESSURE_DROP`` telemetry.
* **Scan-size throttling** — ``throttle_symbol_list()`` limits the working symbol
  set to ``NIJA_MAX_SCAN_SYMBOLS`` (default 100).
* **Market-data health gates** — ``compute_market_data_healthy()`` evaluates
  worker load, timeout rate, and data freshness.  Entries should only proceed
  when this returns ``True``.
* **Cycle telemetry** — ``emit_cycle_telemetry()`` logs a structured record every
  scan cycle so operators can monitor pool health without tailing raw threads.

Environment variables (all optional, safe defaults provided)
------------------------------------------------------------
NIJA_MAX_OHLC_WORKERS        — pool size (default 8)
NIJA_MAX_SCAN_SYMBOLS        — symbol universe cap per cycle (default 100)
NIJA_OHLC_TIMEOUT_SECONDS    — per-symbol fetch timeout (default 8 s)
NIJA_OHLC_DEDUPE_TTL_SECONDS — per-symbol dedup window (default 20 s)
NIJA_OHLC_QUEUE_MAXSIZE      — max pending tasks before backpressure (default 4×workers)
NIJA_OHLC_MAX_TIMEOUT_RATE   — fraction of timeouts that triggers unhealthy (default 0.5)
NIJA_OHLC_POOL_ENABLED       — set to false to bypass pool (not recommended; default true)
"""

from __future__ import annotations

import logging
import os
import queue
import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger("nija.ohlc_worker_pool")

_TRUE = {"1", "true", "yes", "on", "enabled", "y"}

# ─── Environment helpers ──────────────────────────────────────────────────────

def _truthy(name: str, default: str = "true") -> bool:
    return str(os.environ.get(name, default)).strip().lower() in _TRUE


def _int_env(name: str, default: int) -> int:
    try:
        return max(1, int(float(os.environ.get(name, default))))
    except Exception:
        return default


def _float_env(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except Exception:
        return default


# ─── Telemetry counters ───────────────────────────────────────────────────────

class _Counters:
    """Thread-safe integer counters reset on each telemetry cycle."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.duplicate_dropped: int = 0
        self.backpressure_dropped: int = 0
        self.timeouts: int = 0
        self.completed: int = 0
        self.errors: int = 0
        self._last_emit: float = time.time()

    def incr_duplicate(self) -> None:
        with self._lock:
            self.duplicate_dropped += 1

    def incr_backpressure(self) -> None:
        with self._lock:
            self.backpressure_dropped += 1

    def incr_timeout(self) -> None:
        with self._lock:
            self.timeouts += 1

    def incr_completed(self) -> None:
        with self._lock:
            self.completed += 1

    def incr_error(self) -> None:
        with self._lock:
            self.errors += 1

    def snapshot(self) -> Dict[str, int]:
        with self._lock:
            return {
                "duplicate_ohlc_dropped": self.duplicate_dropped,
                "backpressure_dropped": self.backpressure_dropped,
                "ohlc_timeouts": self.timeouts,
                "ohlc_completed": self.completed,
                "ohlc_errors": self.errors,
            }

    def reset_cycle(self) -> None:
        with self._lock:
            self.duplicate_dropped = 0
            self.backpressure_dropped = 0
            self.timeouts = 0
            self.completed = 0
            self.errors = 0
            self._last_emit = time.time()


# ─── OHLCWorkerPool ──────────────────────────────────────────────────────────

class OHLCWorkerPool:
    """Bounded, deduplicating OHLC worker pool.

    Usage::

        pool = get_pool()
        future = pool.submit(symbol, fetch_fn, symbol, timeframe, limit)
        result = future.result(timeout=NIJA_OHLC_TIMEOUT_SECONDS) if future else None
    """

    def __init__(
        self,
        max_workers: int,
        queue_maxsize: int,
        dedupe_ttl: float,
        timeout: float,
    ) -> None:
        self._max_workers = max_workers
        self._timeout = timeout
        self._dedupe_ttl = dedupe_ttl
        # Bounded queue for backpressure; tasks placed here before executor picks up.
        self._queue: queue.Queue = queue.Queue(maxsize=queue_maxsize)
        self._executor = ThreadPoolExecutor(
            max_workers=max_workers,
            thread_name_prefix="nija-ohlc",
        )
        # Dedupe: symbol -> timestamp of last submission (float epoch seconds)
        self._inflight: Dict[str, float] = {}
        self._inflight_lock = threading.Lock()
        # Active futures counter
        self._active: int = 0
        self._active_lock = threading.Lock()
        self._counters = _Counters()
        self._last_data_ts: float = 0.0  # timestamp of most recent successful fetch
        self._data_ts_lock = threading.Lock()

    # ── Public API ─────────────────────────────────────────────────────────

    def submit(
        self,
        symbol: str,
        fn: Callable[..., Any],
        *args: Any,
        **kwargs: Any,
    ) -> Optional[Future]:
        """Submit an OHLC fetch for *symbol* via *fn*.

        Returns a :class:`concurrent.futures.Future` or ``None`` when the
        request is dropped (dedupe or backpressure).
        """
        now = time.time()
        dedupe_ttl = _float_env("NIJA_OHLC_DEDUPE_TTL_SECONDS", self._dedupe_ttl)

        # ── 1. Per-symbol in-flight dedupe ────────────────────────────────
        with self._inflight_lock:
            last = self._inflight.get(symbol)
            if last is not None and (now - last) < dedupe_ttl:
                self._counters.incr_duplicate()
                logger.info(
                    "OHLC_DUPLICATE_DROPPED symbol=%s age_s=%.1f ttl_s=%.1f reason=in_flight_dedupe",
                    symbol,
                    now - last,
                    dedupe_ttl,
                )
                return None
            self._inflight[symbol] = now

        # ── 2. Queue backpressure ─────────────────────────────────────────
        try:
            self._queue.put_nowait(symbol)
        except queue.Full:
            # Remove from inflight so next cycle can try again
            with self._inflight_lock:
                self._inflight.pop(symbol, None)
            self._counters.incr_backpressure()
            qs = self._queue.qsize()
            logger.warning(
                "OHLC_BACKPRESSURE_DROP symbol=%s queue_size=%d max_workers=%d reason=queue_full",
                symbol,
                qs,
                self._max_workers,
            )
            print(
                f"[NIJA-PRINT] OHLC_BACKPRESSURE_DROP symbol={symbol} queue_size={qs}",
                flush=True,
            )
            return None

        # ── 3. Submit to bounded executor ─────────────────────────────────
        with self._active_lock:
            self._active += 1

        def _wrapped() -> Any:
            try:
                # Drain queue slot immediately so the count reflects real work
                try:
                    self._queue.get_nowait()
                except queue.Empty:
                    pass
                result = fn(*args, **kwargs)
                self._counters.incr_completed()
                if result is not None:
                    with self._data_ts_lock:
                        self._last_data_ts = time.time()
                return result
            except Exception as exc:
                self._counters.incr_error()
                logger.warning("OHLC_WORKER_ERROR symbol=%s err=%s", symbol, exc)
                return None
            finally:
                with self._active_lock:
                    self._active = max(0, self._active - 1)
                with self._inflight_lock:
                    # Only clear dedupe once the work is done so a very fast
                    # re-submit of the same symbol during execution is also blocked.
                    pass  # keep inflight entry until TTL expires

        try:
            future = self._executor.submit(_wrapped)
            return future
        except RuntimeError as exc:
            # Executor shut down or process fork limit hit
            with self._active_lock:
                self._active = max(0, self._active - 1)
            with self._inflight_lock:
                self._inflight.pop(symbol, None)
            try:
                self._queue.get_nowait()
            except queue.Empty:
                pass
            self._counters.incr_error()
            logger.critical(
                "OHLC_EXECUTOR_SUBMIT_FAILED symbol=%s err=%s",
                symbol,
                exc,
            )
            return None

    def active_workers(self) -> int:
        with self._active_lock:
            return self._active

    def queue_depth(self) -> int:
        return self._queue.qsize()

    def counters(self) -> _Counters:
        return self._counters

    def last_data_timestamp(self) -> float:
        with self._data_ts_lock:
            return self._last_data_ts

    def compute_market_data_healthy(
        self,
        runtime_state: str = "LIVE_ACTIVE",
        execution_authority: int = 1,
    ) -> Tuple[bool, Dict[str, Any]]:
        """Return ``(healthy, detail_dict)`` for this cycle's health gate.

        Criteria (all must pass):
        1. active_ohlc_workers <= NIJA_MAX_OHLC_WORKERS
        2. total process thread count <= NIJA_THREAD_SAFE_LIMIT (default 300)
        3. OHLC timeout rate < NIJA_OHLC_MAX_TIMEOUT_RATE (default 0.5)
        4. Last successful data fetch within NIJA_DATA_STALENESS_SECONDS (default 120)
        """
        max_w = _int_env("NIJA_MAX_OHLC_WORKERS", self._max_workers)
        safe_threads = _int_env("NIJA_THREAD_SAFE_LIMIT", 300)
        max_timeout_rate = _float_env("NIJA_OHLC_MAX_TIMEOUT_RATE", 0.5)
        staleness_limit = _float_env("NIJA_DATA_STALENESS_SECONDS", 120.0)

        active = self.active_workers()
        snap = self._counters.snapshot()
        total_threads = threading.active_count()
        now = time.time()
        last_data = self.last_data_timestamp()
        data_age = now - last_data if last_data > 0 else float("inf")

        completed = snap["ohlc_completed"]
        timeouts = snap["ohlc_timeouts"]
        total_attempts = completed + timeouts
        timeout_rate = (timeouts / total_attempts) if total_attempts > 0 else 0.0

        checks = {
            "workers_ok": active <= max_w,
            "threads_ok": total_threads <= safe_threads,
            "timeout_rate_ok": timeout_rate < max_timeout_rate,
            "data_fresh_ok": data_age <= staleness_limit or last_data == 0.0,
        }
        healthy = all(checks.values())

        detail: Dict[str, Any] = {
            "market_data_healthy": healthy,
            "active_ohlc_workers": active,
            "max_ohlc_workers": max_w,
            "total_threads": total_threads,
            "timeout_rate": round(timeout_rate, 4),
            "data_age_s": round(data_age, 1) if last_data > 0 else None,
            **checks,
        }
        return healthy, detail

    def emit_cycle_telemetry(
        self,
        runtime_state: str,
        execution_authority: int,
        scan_symbols: int,
        new_entry_allowed: bool,
    ) -> None:
        """Log a structured cycle telemetry record."""
        healthy, health_detail = self.compute_market_data_healthy(
            runtime_state=runtime_state,
            execution_authority=execution_authority,
        )
        snap = self._counters.snapshot()
        record = {
            "runtime_state": runtime_state,
            "execution_authority": execution_authority,
            "scan_symbols": scan_symbols,
            "active_ohlc_workers": self.active_workers(),
            "ohlc_queue_depth": self.queue_depth(),
            "ohlc_timeouts": snap["ohlc_timeouts"],
            "duplicate_ohlc_dropped": snap["duplicate_ohlc_dropped"],
            "market_data_healthy": healthy,
            "new_entry_allowed": new_entry_allowed,
        }
        kv = " ".join(f"{k}={v}" for k, v in record.items())
        logger.critical("NIJA_CYCLE_TELEMETRY %s", kv)
        print(f"[NIJA-PRINT] NIJA_CYCLE_TELEMETRY {kv}", flush=True)
        # Reset per-cycle counters after telemetry emission
        self._counters.reset_cycle()

    def purge_stale_dedupe(self) -> None:
        """Remove expired entries from the in-flight dedupe map (housekeeping)."""
        ttl = _float_env("NIJA_OHLC_DEDUPE_TTL_SECONDS", self._dedupe_ttl)
        now = time.time()
        with self._inflight_lock:
            stale = [sym for sym, ts in self._inflight.items() if now - ts > ttl]
            for sym in stale:
                del self._inflight[sym]


# ─── Process-global singleton pool ───────────────────────────────────────────

_POOL: Optional[OHLCWorkerPool] = None
_POOL_LOCK = threading.Lock()


def get_pool() -> OHLCWorkerPool:
    """Return (or create) the process-global :class:`OHLCWorkerPool`."""
    global _POOL
    if _POOL is not None:
        return _POOL
    with _POOL_LOCK:
        if _POOL is not None:
            return _POOL
        max_workers = _int_env("NIJA_MAX_OHLC_WORKERS", 8)
        queue_maxsize = _int_env("NIJA_OHLC_QUEUE_MAXSIZE", max_workers * 4)
        dedupe_ttl = _float_env("NIJA_OHLC_DEDUPE_TTL_SECONDS", 20.0)
        timeout = _float_env("NIJA_OHLC_TIMEOUT_SECONDS", 8.0)
        _POOL = OHLCWorkerPool(
            max_workers=max_workers,
            queue_maxsize=queue_maxsize,
            dedupe_ttl=dedupe_ttl,
            timeout=timeout,
        )
        logger.warning(
            "OHLC_WORKER_POOL_CREATED max_workers=%d queue_maxsize=%d dedupe_ttl_s=%.1f timeout_s=%.1f",
            max_workers,
            queue_maxsize,
            dedupe_ttl,
            timeout,
        )
        print(
            f"[NIJA-PRINT] OHLC_WORKER_POOL_CREATED max_workers={max_workers} "
            f"queue_maxsize={queue_maxsize} dedupe_ttl_s={dedupe_ttl} timeout_s={timeout}",
            flush=True,
        )
    return _POOL


# ─── Symbol universe throttling ───────────────────────────────────────────────

# Preferred safe shortlist of liquid Kraken USD/USDT pairs.
# Used as the deterministic top-N fallback when the caller does not supply a
# pre-ranked list.  Order reflects approximate liquidity (high → lower).
_SAFE_SHORTLIST: List[str] = [
    "BTC-USD", "ETH-USD", "SOL-USD", "XRP-USD", "ADA-USD", "AVAX-USD",
    "DOT-USD", "LINK-USD", "MATIC-USD", "LTC-USD", "BCH-USD", "ATOM-USD",
    "UNI-USD", "ALGO-USD", "FIL-USD", "NEAR-USD", "SAND-USD", "MANA-USD",
    "CRV-USD", "AAVE-USD", "COMP-USD", "SNX-USD", "MKR-USD", "YFI-USD",
    "1INCH-USD", "SUSHI-USD", "BAL-USD", "BAND-USD", "KNC-USD", "ZRX-USD",
    "ENJ-USD", "CHZ-USD", "FLOW-USD", "ICP-USD", "THETA-USD", "VET-USD",
    "XTZ-USD", "EOS-USD", "TRX-USD", "XLM-USD", "DASH-USD", "ZEC-USD",
    "ETC-USD", "XMR-USD", "SHIB-USD", "DOGE-USD", "APE-USD", "IMX-USD",
    "OP-USD", "ARB-USD",
]


def throttle_symbol_list(
    symbols: List[str],
    max_symbols: Optional[int] = None,
) -> List[str]:
    """Return a capped symbol list for the current scan cycle.

    If *symbols* is longer than *max_symbols* (``NIJA_MAX_SCAN_SYMBOLS``,
    default 100), the list is truncated.  The input order is preserved so
    callers that already rank by liquidity/priority get the best symbols.

    If *symbols* is empty, ``_SAFE_SHORTLIST`` is returned (capped) as a
    deterministic fallback.
    """
    cap = max_symbols if max_symbols is not None else _int_env("NIJA_MAX_SCAN_SYMBOLS", 100)
    if not symbols:
        capped = _SAFE_SHORTLIST[:cap]
        logger.warning(
            "SCAN_SYMBOL_THROTTLE input=0 using_shortlist=True cap=%d result=%d",
            cap,
            len(capped),
        )
        return capped
    if len(symbols) <= cap:
        return list(symbols)
    capped = list(symbols[:cap])
    logger.warning(
        "SCAN_SYMBOL_THROTTLE input=%d cap=%d result=%d dropped=%d",
        len(symbols),
        cap,
        len(capped),
        len(symbols) - cap,
    )
    print(
        f"[NIJA-PRINT] SCAN_SYMBOL_THROTTLE input={len(symbols)} cap={cap} result={len(capped)}",
        flush=True,
    )
    return capped


# ─── Process-level singleton worker guard ────────────────────────────────────

_WORKER_STARTED: Dict[str, bool] = {}
_WORKER_LOCK = threading.Lock()


def ensure_worker_singleton(worker_name: str) -> bool:
    """Return True if *worker_name* may start; False if already running.

    Emits ``WORKER_ALREADY_RUNNING`` telemetry when a duplicate start is blocked.
    Thread-safe: uses a module-level lock and a dict of started worker names.

    This is the **process-level** guard.  Individual patch modules should call
    this *before* spawning their background thread so that duplicate engine
    instantiation cannot create duplicate workers.
    """
    with _WORKER_LOCK:
        if _WORKER_STARTED.get(worker_name):
            logger.warning(
                "WORKER_ALREADY_RUNNING worker=%s action=skip_duplicate_start",
                worker_name,
            )
            print(
                f"[NIJA-PRINT] WORKER_ALREADY_RUNNING worker={worker_name}",
                flush=True,
            )
            return False
        _WORKER_STARTED[worker_name] = True
        return True


def is_worker_running(worker_name: str) -> bool:
    """Return True if *worker_name* has been registered as started."""
    with _WORKER_LOCK:
        return bool(_WORKER_STARTED.get(worker_name))
