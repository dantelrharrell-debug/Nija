"""Bounded Phase 3 market-data concurrency repair v171.

Production showed Phase 3 exhausting its 24-second scan budget because each
symbol fetch waited synchronously for its own OHLC request.  The broker's OHLC
worker pool is bounded, but the scanner used it serially, so the pool could not
improve scan liveness.

v171 prefetches the already-selected Phase 3 symbol window with a separate,
bounded scan executor, stores only strong frames in the existing same-cycle
cache, and then lets the original scanner consume those frames through the
existing _fetch_df wrapper.  The original scoring, liquidity, profitability,
risk, order, writer, nonce, kill-switch, and execution-authority gates are
unchanged.

The prefetch deadline is strictly bounded by the existing Phase 3 deadline.
Unfinished work is ignored/cancelled where possible; no entry is created from
missing or weak data.  This is a liveness repair, not a signal-threshold repair.
"""
from __future__ import annotations

import importlib
import logging
import os
import threading
import time
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from functools import wraps
from typing import Any

LOGGER = logging.getLogger("nija.runtime_market_data_concurrency_v171")
MARKER = "20260820-runtime-market-data-concurrency-v171"
_READY_FLAG = "NIJA_RUNTIME_MARKET_DATA_CONCURRENCY_V171_READY"
_PATCH_ATTR = "_nija_runtime_market_data_concurrency_v171"
_LOCK = threading.RLock()


def _int_env(name: str, default: int) -> int:
    try:
        return max(1, int(float(os.environ.get(name, str(default)) or default)))
    except (TypeError, ValueError):
        return default


def _float_env(name: str, default: float) -> float:
    try:
        return max(0.05, float(os.environ.get(name, str(default)) or default))
    except (TypeError, ValueError):
        return default


def _cacheable(df: Any) -> bool:
    try:
        guard = importlib.import_module("bot.phase3_scan_stall_guard_patch")
        return bool(guard._cacheable_df(df))
    except Exception:
        try:
            return df is not None and len(df) >= 50
        except Exception:
            return False


def _symbol_key(symbol: Any) -> str:
    return str(symbol or "unknown")


def _prefetch_window(
    owner: Any,
    broker: Any,
    symbols: list[Any],
    fetch_fn: Any,
    deadline_ts: float,
) -> dict[str, Any]:
    """Fetch selected symbols concurrently inside the existing Phase 3 deadline."""
    if not symbols or not callable(fetch_fn):
        return {}

    max_workers = min(
        len(symbols),
        _int_env("NIJA_PHASE3_PREFETCH_WORKERS", 6),
        _int_env("NIJA_MAX_OHLC_WORKERS", 8),
    )
    if max_workers <= 1:
        return {}

    started = time.monotonic()
    results: dict[str, Any] = {}
    futures: dict[Future[Any], str] = {}

    executor = ThreadPoolExecutor(
        max_workers=max_workers,
        thread_name_prefix="nija-phase3-prefetch",
    )
    try:
        for symbol in symbols:
            if time.monotonic() >= deadline_ts:
                break
            key = _symbol_key(symbol)
            try:
                future = executor.submit(fetch_fn, owner, broker, symbol)
            except RuntimeError:
                break
            futures[future] = key

        pending = set(futures)
        while pending:
            remaining = max(0.0, deadline_ts - time.monotonic())
            if remaining <= 0.0:
                break
            done, pending = wait(
                pending,
                timeout=min(0.25, remaining),
                return_when=FIRST_COMPLETED,
            )
            for future in done:
                key = futures[future]
                try:
                    frame = future.result(timeout=0)
                except Exception:
                    frame = None
                if _cacheable(frame):
                    results[key] = frame

        for future in pending:
            future.cancel()
    finally:
        # Never wait for slow network calls after Phase 3's own deadline.
        executor.shutdown(wait=False, cancel_futures=True)

    LOGGER.info(
        "PHASE3_PREFETCH_V171_COMPLETE marker=%s selected=%d submitted=%d cached=%d "
        "workers=%d elapsed_s=%.3f deadline_remaining_s=%.3f",
        MARKER,
        len(symbols),
        len(futures),
        len(results),
        max_workers,
        time.monotonic() - started,
        max(0.0, deadline_ts - time.monotonic()),
    )
    return results


def _patch_phase3_guard() -> bool:
    try:
        guard = importlib.import_module("bot.phase3_scan_stall_guard_patch")
        core = importlib.import_module("bot.nija_core_loop")
    except Exception:
        return False

    cls = getattr(core, "NijaCoreLoop", None)
    if not isinstance(cls, type):
        return False
    current = getattr(cls, "_phase3_scan_and_enter", None)
    if not callable(current):
        return False
    if bool(getattr(current, _PATCH_ATTR, False)):
        return True

    # Locate the deepest original _fetch_df so prefetch does not immediately
    # hit the same-cycle cache wrapper recursively.
    fetch_current = getattr(cls, "_fetch_df", None)
    if not callable(fetch_current):
        return False
    raw_fetch = fetch_current
    seen: set[int] = set()
    while callable(getattr(raw_fetch, "__wrapped__", None)) and id(raw_fetch) not in seen:
        seen.add(id(raw_fetch))
        raw_fetch = getattr(raw_fetch, "__wrapped__")

    @wraps(current)
    def phase3_v171(
        self: Any,
        broker: Any,
        snapshot: Any,
        symbols: Any,
        available_slots: int,
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        selected = list(symbols or [])
        deadline_ts = float(
            getattr(self, "_nija_phase3_deadline_ts_20260709an", 0.0) or 0.0
        )
        if deadline_ts <= time.monotonic():
            timeout_s = max(5.0, _float_env("NIJA_PHASE3_SCAN_DEADLINE_S", 24.0))
            deadline_ts = time.monotonic() + timeout_s
            setattr(self, "_nija_phase3_deadline_ts_20260709an", deadline_ts)

        cache = getattr(self, "_nija_phase3_market_data_cache_20260709an", None)
        if not isinstance(cache, dict):
            cache = {}
            setattr(self, "_nija_phase3_market_data_cache_20260709an", cache)
        setattr(self, "_nija_phase3_market_data_cache_active_20260709an", True)

        prefetched = _prefetch_window(self, broker, selected, raw_fetch, deadline_ts)
        if prefetched:
            cache.update(prefetched)
        return current(self, broker, snapshot, selected, available_slots, *args, **kwargs)

    setattr(phase3_v171, _PATCH_ATTR, True)
    setattr(phase3_v171, "__wrapped__", current)
    cls._phase3_scan_and_enter = phase3_v171

    # Re-run the existing guard installer so any late wrappers observe v171.
    try:
        installer = getattr(guard, "install_import_hook", None) or getattr(guard, "install", None)
        if callable(installer):
            installer()
    except Exception:
        pass
    return True


def _reassert_market_data_stability() -> bool:
    try:
        module = importlib.import_module("bot.market_data_stability_runtime_patch")
        installer = getattr(module, "_install_kraken_market_data_patch", None)
        if not callable(installer):
            return False
        installer()
        return True
    except Exception:
        return False


def _patch_release_manifest() -> bool:
    try:
        manifest = importlib.import_module("bot.runtime_release_manifest_patch")
        required = getattr(manifest, "_REQUIRED_FLAGS", None)
        if not isinstance(required, dict):
            return False
        required["runtime_market_data_concurrency_v171"] = _READY_FLAG
        return True
    except Exception:
        return False


def install() -> bool:
    with _LOCK:
        # Preserve v157's fail-closed deadline behavior.
        os.environ.setdefault("NIJA_PHASE3_FETCH_DEADLINE_SKIP_ENABLED", "true")
        os.environ.setdefault("NIJA_PHASE3_SCAN_DEADLINE_S", "24")
        os.environ.setdefault("NIJA_PHASE3_PREFETCH_WORKERS", "6")

        stability_ok = _reassert_market_data_stability()
        phase3_ok = _patch_phase3_guard()
        manifest_ok = _patch_release_manifest()
        ready = bool(stability_ok and phase3_ok and manifest_ok)
        os.environ[_READY_FLAG] = "1" if ready else "0"
        if not ready:
            LOGGER.critical(
                "RUNTIME_MARKET_DATA_CONCURRENCY_V171_FAILED marker=%s stability=%s phase3=%s "
                "manifest=%s trading_fail_closed=true",
                MARKER,
                str(stability_ok).lower(),
                str(phase3_ok).lower(),
                str(manifest_ok).lower(),
            )
            return False
        LOGGER.critical(
            "RUNTIME_MARKET_DATA_CONCURRENCY_V171 marker=%s ready=true bounded_prefetch=true "
            "phase3_deadline_preserved=true same_cycle_cache_reuse=true market_data_stability_reasserted=true "
            "signal_thresholds_unchanged=true forced_trade=false safety_gates_bypassed=false",
            MARKER,
        )
        return True


def install_import_hook() -> bool:
    return install()


__all__ = [
    "MARKER",
    "install",
    "install_import_hook",
    "_prefetch_window",
    "_patch_phase3_guard",
]
