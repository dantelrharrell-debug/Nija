"""Per-broker asynchronous scan worker infrastructure.

Each configured platform broker (Kraken, Coinbase, OKX, user accounts) runs
in its own daemon thread with its own bounded task queue (maxsize=1).  The
main trading loop submits scan requests to all workers simultaneously and
returns immediately — no worker can block the main loop and no broker can
delay another.

Architecture
------------
::

    TradingLoop (main thread)
         │
         ├─ BrokerScanWorker("kraken")   ← daemon thread + queue(1)
         ├─ BrokerScanWorker("coinbase") ← daemon thread + queue(1)
         ├─ BrokerScanWorker("okx")      ← daemon thread + queue(1)
         └─ BrokerScanWorker("user_*")   ← daemon thread + queue(1)

Isolation guarantees
--------------------
* If a worker is still busy when a new scan is submitted the new task is
  **dropped** (not queued) and the main loop continues unblocked.
* Each scan call is wrapped in a configurable hard timeout
  (``NIJA_BROKER_SCAN_TIMEOUT_S``, default ``5`` s).  A hung broker is
  abandoned and becomes available for the next cycle.
* Exit management and position synchronisation execute inside the worker
  thread and cannot delay other brokers or the main loop.

Environment variables
---------------------
NIJA_BROKER_SCAN_TIMEOUT_S    — per-broker hard scan timeout in seconds
                                (default: 5, min: 2, max: 60)
NIJA_BROKER_WORKER_POOL_ENABLED — set to "false" to disable the pool and
                                revert to the legacy sequential path
                                (default: true)
"""

from __future__ import annotations

import logging
import os
import queue
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)

_TRUE_SET = {"1", "true", "yes", "on", "enabled", "y"}


def _truthy(name: str, default: str = "true") -> bool:
    return str(os.environ.get(name, default)).strip().lower() in _TRUE_SET


def _float_env(name: str, default: float, lo: float = 0.0, hi: float = 1e9) -> float:
    try:
        val = float(os.environ.get(name, default))
        return max(lo, min(hi, val))
    except Exception:
        return default


# Hard timeout applied to each broker's scan phase call.
_DEFAULT_SCAN_TIMEOUT_S = _float_env("NIJA_BROKER_SCAN_TIMEOUT_S", 5.0, lo=2.0, hi=60.0)


# ---------------------------------------------------------------------------
# Data containers
# ---------------------------------------------------------------------------

@dataclass
class BrokerScanTask:
    """Parameters for one broker scan cycle dispatched to a worker."""

    broker: Any
    broker_name: str
    balance: float
    symbols: List[str]
    open_positions_count: int
    user_mode: bool
    cycle_id: str
    submitted_at: float = field(default_factory=time.monotonic)


@dataclass
class BrokerScanResult:
    """Summary result reported after a broker scan completes or times out."""

    broker_name: str
    success: bool
    elapsed_s: float
    entries_taken: int = 0
    exits_taken: int = 0
    symbols_scored: int = 0
    error: Optional[str] = None
    timed_out: bool = False
    dropped: bool = False


# ---------------------------------------------------------------------------
# Per-broker worker
# ---------------------------------------------------------------------------

class BrokerScanWorker:
    """Daemon worker thread for one broker's scan phase.

    The worker loop picks one task at a time from its bounded queue (maxsize=1)
    and executes the scan phase with a hard timeout.  If the scan exceeds the
    timeout the worker logs a warning and resets — it is immediately available
    for the next cycle.  A second task submitted while the worker is busy is
    dropped; the calling thread is never blocked.

    Parameters
    ----------
    broker_name:
        Human-readable broker identifier used in log messages.
    scan_fn:
        Callable that performs the actual scan.  Signature::

            scan_fn(
                broker,
                balance,
                symbols,
                open_positions_count,
                user_mode,
            ) -> CoreLoopResult

    scan_timeout_s:
        Hard timeout (seconds) for one scan_fn call.
    result_callback:
        Optional function called with a :class:`BrokerScanResult` after
        each scan finishes.  Executed on the worker thread; must not block.
    """

    def __init__(
        self,
        broker_name: str,
        scan_fn: Callable[..., Any],
        scan_timeout_s: float = _DEFAULT_SCAN_TIMEOUT_S,
        result_callback: Optional[Callable[[BrokerScanResult], None]] = None,
    ) -> None:
        self.broker_name = broker_name
        self._scan_fn = scan_fn
        self._scan_timeout_s = max(2.0, float(scan_timeout_s))
        self._result_callback = result_callback

        # maxsize=1: only one pending task accepted; subsequent submits are dropped.
        self._task_queue: "queue.Queue[Optional[BrokerScanTask]]" = queue.Queue(maxsize=1)
        self._busy = threading.Event()
        self._stop = threading.Event()

        self._thread = threading.Thread(
            target=self._worker_loop,
            name=f"BrokerWorker-{broker_name}",
            daemon=True,
        )
        self._thread.start()
        logger.info(
            "[BrokerWorkerPool] Worker started: %s (scan_timeout=%.1fs)",
            broker_name,
            self._scan_timeout_s,
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def submit(self, task: BrokerScanTask) -> bool:
        """Submit a scan task without blocking.

        Returns ``True`` if the task was accepted, ``False`` if dropped
        because the worker is still processing the previous cycle.
        """
        # If the worker is currently executing a scan, drop the new task
        # immediately rather than queuing it — a queued task would be stale
        # by the time the worker picks it up.
        if self._busy.is_set():
            logger.warning(
                "⚠️  [BrokerWorker:%s] scan DROPPED — worker still busy with previous "
                "cycle.  Main loop advancing without waiting. "
                "(cycle_id=%s)",
                self.broker_name,
                task.cycle_id,
            )
            print(
                f"[NIJA-PRINT] BROKER_SCAN_DROPPED broker={self.broker_name} "
                f"cycle_id={task.cycle_id}",
                flush=True,
            )
            return False

        try:
            self._task_queue.put_nowait(task)
            logger.debug(
                "[BrokerWorker:%s] task submitted (cycle_id=%s)",
                self.broker_name,
                task.cycle_id,
            )
            return True
        except queue.Full:
            logger.warning(
                "⚠️  [BrokerWorker:%s] scan DROPPED — worker still busy with previous "
                "cycle.  Main loop advancing without waiting. "
                "(cycle_id=%s)",
                self.broker_name,
                task.cycle_id,
            )
            print(
                f"[NIJA-PRINT] BROKER_SCAN_DROPPED broker={self.broker_name} "
                f"cycle_id={task.cycle_id}",
                flush=True,
            )
            return False

    @property
    def is_alive(self) -> bool:
        """True when the underlying daemon thread is still running."""
        return self._thread.is_alive()

    def stop(self) -> None:
        """Signal the worker thread to exit cleanly."""
        self._stop.set()
        try:
            self._task_queue.put_nowait(None)  # sentinel to unblock queue.get()
        except queue.Full:
            pass

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _worker_loop(self) -> None:
        """Main loop executed on the daemon thread."""
        logger.debug("[BrokerWorker:%s] loop starting", self.broker_name)
        while not self._stop.is_set():
            try:
                task = self._task_queue.get(timeout=1.0)
            except queue.Empty:
                continue
            if task is None:  # stop sentinel
                break

            self._busy.set()
            t0 = time.monotonic()
            try:
                result = self._execute_with_timeout(task)
            except Exception as _loop_err:
                elapsed = time.monotonic() - t0
                logger.warning(
                    "[BrokerWorker:%s] unexpected worker error: %s",
                    self.broker_name,
                    _loop_err,
                    exc_info=False,
                )
                result = BrokerScanResult(
                    broker_name=self.broker_name,
                    success=False,
                    elapsed_s=elapsed,
                    error=str(_loop_err),
                )
            finally:
                self._busy.clear()

            result.elapsed_s = time.monotonic() - t0
            logger.info(
                "✅ [BrokerWorker:%s] scan done | success=%s timed_out=%s "
                "elapsed=%.2fs entries=%d exits=%d scored=%d",
                self.broker_name,
                result.success,
                result.timed_out,
                result.elapsed_s,
                result.entries_taken,
                result.exits_taken,
                result.symbols_scored,
            )
            print(
                f"[NIJA-PRINT] BROKER_SCAN_DONE broker={self.broker_name} "
                f"success={result.success} timed_out={result.timed_out} "
                f"elapsed={result.elapsed_s:.2f}s entries={result.entries_taken} "
                f"exits={result.exits_taken}",
                flush=True,
            )
            if self._result_callback is not None:
                try:
                    self._result_callback(result)
                except Exception as _cb_err:
                    logger.debug(
                        "[BrokerWorker:%s] result_callback error: %s",
                        self.broker_name,
                        _cb_err,
                    )

        logger.debug("[BrokerWorker:%s] loop exiting", self.broker_name)

    def _execute_with_timeout(self, task: BrokerScanTask) -> BrokerScanResult:
        """Run scan_fn in a fresh daemon thread; abandon it after timeout."""
        result_holder: "queue.Queue[tuple[str, Any]]" = queue.Queue(maxsize=1)

        def _run() -> None:
            try:
                core_result = self._scan_fn(
                    broker=task.broker,
                    balance=task.balance,
                    symbols=task.symbols,
                    open_positions_count=task.open_positions_count,
                    user_mode=task.user_mode,
                )
                result_holder.put(("ok", core_result))
            except Exception as _scan_err:
                result_holder.put(("error", _scan_err))

        scan_thread = threading.Thread(
            target=_run,
            name=f"BrokerScan-{self.broker_name}",
            daemon=True,
        )
        scan_thread.start()

        try:
            kind, payload = result_holder.get(timeout=self._scan_timeout_s)
        except queue.Empty:
            # Hard timeout reached — leave the scan_thread running as a daemon;
            # it will be garbage-collected when the process exits or the next
            # timeout reclaims thread resources.
            logger.warning(
                "⏰ [BrokerWorker:%s] scan TIMED OUT after %.1fs — abandoning. "
                "Broker available for next cycle.",
                self.broker_name,
                self._scan_timeout_s,
            )
            print(
                f"[NIJA-PRINT] BROKER_SCAN_TIMEOUT broker={self.broker_name} "
                f"timeout={self._scan_timeout_s:.1f}s cycle_id={task.cycle_id}",
                flush=True,
            )
            return BrokerScanResult(
                broker_name=self.broker_name,
                success=False,
                elapsed_s=self._scan_timeout_s,
                timed_out=True,
            )

        if kind == "error":
            err = payload
            logger.warning(
                "[BrokerWorker:%s] scan raised exception: %s",
                self.broker_name,
                err,
            )
            return BrokerScanResult(
                broker_name=self.broker_name,
                success=False,
                elapsed_s=0.0,
                error=str(err),
            )

        # kind == "ok"
        core_result = payload
        return BrokerScanResult(
            broker_name=self.broker_name,
            success=True,
            elapsed_s=0.0,
            entries_taken=int(getattr(core_result, "entries_taken", 0) or 0),
            exits_taken=int(getattr(core_result, "exits_taken", 0) or 0),
            symbols_scored=int(getattr(core_result, "symbols_scored", 0) or 0),
        )


# ---------------------------------------------------------------------------
# Pool (manages all per-broker workers)
# ---------------------------------------------------------------------------

class BrokerWorkerPool:
    """Manages a collection of :class:`BrokerScanWorker` instances.

    Workers are created lazily when first submitted a task and kept alive for
    the process lifetime.  A dead worker thread (crashed) is automatically
    replaced on the next ``submit_all`` call.

    Parameters
    ----------
    scan_fn:
        The scan callable shared by all workers.  Each call receives a
        different ``broker`` argument so parallel execution is naturally
        broker-isolated.
    scan_timeout_s:
        Hard timeout applied to each worker's scan_fn call.
    """

    def __init__(
        self,
        scan_fn: Callable[..., Any],
        scan_timeout_s: float = _DEFAULT_SCAN_TIMEOUT_S,
    ) -> None:
        self._scan_fn = scan_fn
        self._scan_timeout_s = max(2.0, float(scan_timeout_s))
        self._workers: Dict[str, BrokerScanWorker] = {}
        self._lock = threading.Lock()
        logger.info(
            "[BrokerWorkerPool] Pool created (scan_timeout=%.1fs)",
            self._scan_timeout_s,
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def submit_all(self, tasks: List[BrokerScanTask]) -> Dict[str, bool]:
        """Dispatch all tasks to their respective broker workers.

        This method **always returns immediately** without waiting for any
        worker to complete.  The returned dict maps broker_name → accepted
        (``True``) or dropped (``False``).
        """
        accepted: Dict[str, bool] = {}
        for task in tasks:
            worker = self._get_or_create_worker(task.broker_name)
            accepted[task.broker_name] = worker.submit(task)
        return accepted

    def worker_names(self) -> List[str]:
        """Return names of all currently registered workers."""
        with self._lock:
            return list(self._workers.keys())

    def stop_all(self) -> None:
        """Signal all workers to exit.  Non-blocking."""
        with self._lock:
            workers = list(self._workers.values())
        for w in workers:
            try:
                w.stop()
            except Exception:
                pass

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _get_or_create_worker(self, broker_name: str) -> BrokerScanWorker:
        with self._lock:
            worker = self._workers.get(broker_name)
            if worker is None or not worker.is_alive:
                if worker is not None:
                    logger.warning(
                        "[BrokerWorkerPool] worker for %s is dead — replacing",
                        broker_name,
                    )
                worker = BrokerScanWorker(
                    broker_name=broker_name,
                    scan_fn=self._scan_fn,
                    scan_timeout_s=self._scan_timeout_s,
                )
                self._workers[broker_name] = worker
            return worker


# ---------------------------------------------------------------------------
# Module-level singleton helpers
# ---------------------------------------------------------------------------

_pool_instance: Optional[BrokerWorkerPool] = None
_pool_lock = threading.Lock()


def get_broker_worker_pool(scan_fn: Callable[..., Any]) -> Optional[BrokerWorkerPool]:
    """Return the process-global :class:`BrokerWorkerPool`.

    Returns ``None`` when ``NIJA_BROKER_WORKER_POOL_ENABLED=false``.
    The pool is created lazily on first call and reused thereafter.

    Parameters
    ----------
    scan_fn:
        The scan callable to use.  Only used when creating the pool for
        the first time; subsequent calls ignore this argument.
    """
    if not _truthy("NIJA_BROKER_WORKER_POOL_ENABLED", "true"):
        return None

    global _pool_instance
    if _pool_instance is not None:
        return _pool_instance

    with _pool_lock:
        if _pool_instance is None:
            timeout_s = _float_env("NIJA_BROKER_SCAN_TIMEOUT_S", 5.0, lo=2.0, hi=60.0)
            _pool_instance = BrokerWorkerPool(
                scan_fn=scan_fn,
                scan_timeout_s=timeout_s,
            )
            logger.info(
                "[BrokerWorkerPool] Singleton pool initialised (timeout=%.1fs)",
                timeout_s,
            )
    return _pool_instance
