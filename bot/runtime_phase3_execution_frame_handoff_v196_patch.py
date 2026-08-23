"""Preserve validated Phase 3 candle frames through execution handoff v196.

Production evidence showed a ranked candidate could pass Phase 3 scoring with a
valid 50-candle frame and then disappear when the execution loop called
``_fetch_df`` again and the exchange returned a transient short/empty response.

v171 already owns a per-Phase-3-cycle market-data cache, but its cache-admission
predicate also required recent positive volume. Volume quality is an explicit
Phase 3 liquidity/risk gate later in the same path, so making cache admission
depend on volume could leave an already-scored frame outside the same-cycle
cache and force a redundant exchange fetch.

This repair changes cache *admission only*:
* a frame must still meet the configured candle minimum (never below 50),
* a frame must contain complete OHLCV columns,
* the cache remains the v171 same-cycle cache and is cleared after Phase 3,
* volume/liquidity/min-notional/risk/order/nonce/writer gates are unchanged,
* no stale frame is promoted across cycles and no trade is forced.
"""
from __future__ import annotations

import importlib
import logging
import os
import threading
from typing import Any

LOGGER = logging.getLogger("nija.runtime_phase3_execution_frame_handoff_v196")
MARKER = "20260823-phase3-execution-frame-handoff-v196"
_READY_FLAG = "NIJA_RUNTIME_PHASE3_EXECUTION_FRAME_HANDOFF_V196_READY"
_PATCH_ATTR = "_nija_phase3_execution_frame_handoff_v196"
_LOCK = threading.RLock()
_REQUIRED_COLUMNS = frozenset({"open", "high", "low", "close", "volume"})


def _configured_min_rows() -> int:
    try:
        return max(
            50,
            int(float(os.environ.get("NIJA_PHASE3_MARKET_DATA_CACHE_MIN_ROWS", "50") or 50)),
        )
    except (TypeError, ValueError):
        return 50


def _df_len(df: Any) -> int:
    try:
        return int(len(df))
    except Exception:
        return 0


def _column_names(df: Any) -> set[str]:
    try:
        return {str(column).strip().lower() for column in getattr(df, "columns", [])}
    except Exception:
        return set()


def _structurally_cacheable_execution_frame(df: Any) -> bool:
    """Return whether *df* is safe for v171 same-cycle reuse.

    Volume *quality* intentionally is not decided here. The existing Phase 3
    volume/liquidity gate remains authoritative and can still block the symbol.
    """

    if df is None or _df_len(df) < _configured_min_rows():
        return False
    return _REQUIRED_COLUMNS.issubset(_column_names(df))


setattr(_structurally_cacheable_execution_frame, _PATCH_ATTR, True)


def install() -> bool:
    """Reassert v196 cache admission on the active v171 guard module."""

    with _LOCK:
        try:
            guard = importlib.import_module("bot.phase3_scan_stall_guard_patch")
        except Exception as exc:
            os.environ[_READY_FLAG] = "0"
            LOGGER.critical(
                "RUNTIME_PHASE3_EXECUTION_FRAME_HANDOFF_V196_FAILED marker=%s "
                "reason=guard_import_failed error=%s:%s trading_fail_closed=true",
                MARKER,
                type(exc).__name__,
                exc,
            )
            return False

        current = getattr(guard, "_cacheable_df", None)
        if not (callable(current) and getattr(current, _PATCH_ATTR, False)):
            setattr(guard, "_nija_v196_previous_cacheable_df", current)
            setattr(guard, "_cacheable_df", _structurally_cacheable_execution_frame)

        installed = getattr(guard, "_cacheable_df", None)
        ready = bool(callable(installed) and getattr(installed, _PATCH_ATTR, False))
        os.environ[_READY_FLAG] = "1" if ready else "0"
        if not ready:
            LOGGER.critical(
                "RUNTIME_PHASE3_EXECUTION_FRAME_HANDOFF_V196_FAILED marker=%s "
                "reason=cache_admission_not_bound trading_fail_closed=true",
                MARKER,
            )
            return False

        LOGGER.critical(
            "RUNTIME_PHASE3_EXECUTION_FRAME_HANDOFF_V196 marker=%s ready=true "
            "same_cycle_only=true min_rows=%d ohlcv_required=true "
            "volume_quality_gate_unchanged=true min_notional_gate_unchanged=true "
            "risk_gates_unchanged=true order_quote_freshness_unchanged=true "
            "forced_trade=false safety_gates_bypassed=false",
            MARKER,
            _configured_min_rows(),
        )
        return True


def install_import_hook() -> bool:
    return install()


__all__ = [
    "MARKER",
    "install",
    "install_import_hook",
    "_structurally_cacheable_execution_frame",
]
