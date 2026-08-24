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

v197 is installed as a mandatory companion from this already-required runtime
path. It repairs only the pre-existing whitelisted heartbeat verification probe
handoff through ExecutionPipeline; ordinary trade authority remains unchanged.
v202 is installed immediately after v197 and changes only heartbeat retry
*liveness*: when authoritative position sync changes from false to true while a
failed heartbeat probe is sleeping, that sleep wakes so the unchanged verifier
can retry before the bounded post-core startup window expires. No gate is
bypassed and ordinary retry cadence is unchanged.
v207 is installed before v203 and narrows v203's install-time strategy lookup to
already-loaded pointers only. This prevents the pre-core heartbeat companion
chain from triggering broad strategy discovery imports while generation is 0 /
BOOT_INIT; canonical bot_main Step 2.5 remains the sole strategy publisher.
v203 is installed after v207 and repairs one additional liveness gap: when the
canonical strategy publisher reuses an already-created TradingStrategy instead
of re-running its constructor, the existing heartbeat scheduler is re-armed if
policy requires it and its verifier thread is absent/dead. v203 does not write
proof, grant authority, or bypass any execution gate.
v204 is installed after v203 and repairs stale import-time pipeline bindings in
the canonical order submitter. If an early circular/import-order failure cached
``PipelineRequest`` or ``get_execution_pipeline`` as unavailable, v204 rebinds
those symbols lazily from the canonical execution pipeline at real order time.
If the pipeline is still unavailable the existing fail-closed rejection remains.
v206 is installed after v204 and repairs only Kraken legacy REST pair identity
before ECEL contract lookup (for example XETHZUSD -> ETH-USD and XXBTZUSD ->
XBT-USD). Existing ECEL contract rules and minimums remain authoritative and all
writer/nonce/risk/kill-switch/capital/position/order/fill gates remain unchanged.
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
_V197_READY_FLAG = "NIJA_RUNTIME_HEARTBEAT_PROBE_PIPELINE_BRIDGE_V197_READY"
_V202_READY_FLAG = "NIJA_HEARTBEAT_POSITION_SYNC_WAKEUP_V202_READY"
_V207_READY_FLAG = "NIJA_PRECORE_STRATEGY_LOOKUP_V207_READY"
_V203_READY_FLAG = "NIJA_EXISTING_STRATEGY_HEARTBEAT_REARM_V203_READY"
_V204_READY_FLAG = "NIJA_EXECUTION_PIPELINE_LATE_BINDING_V204_READY"
_V206_READY_FLAG = "NIJA_KRAKEN_ECEL_SYMBOL_CANONICALIZATION_V206_READY"
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


def _install_v197() -> bool:
    """Install heartbeat bridge plus v202/v207/v203/v204/v206 repairs."""
    try:
        module = importlib.import_module("bot.runtime_heartbeat_probe_pipeline_bridge_v197_patch")
        installer = getattr(module, "install", None) or getattr(module, "install_import_hook", None)
        if not callable(installer):
            return False
        v197_ready = bool(installer()) and os.environ.get(_V197_READY_FLAG, "0").strip() == "1"
        if not v197_ready:
            return False

        wakeup = importlib.import_module("bot.runtime_heartbeat_position_sync_wakeup_v202_patch")
        wakeup_installer = getattr(wakeup, "install", None) or getattr(wakeup, "install_import_hook", None)
        if not callable(wakeup_installer):
            return False
        v202_ready = bool(wakeup_installer()) and os.environ.get(_V202_READY_FLAG, "0").strip() == "1"
        if not v202_ready:
            return False

        nonblocking_lookup = importlib.import_module("bot.runtime_precore_strategy_lookup_v207_patch")
        nonblocking_installer = getattr(nonblocking_lookup, "install", None) or getattr(nonblocking_lookup, "install_import_hook", None)
        if not callable(nonblocking_installer):
            return False
        v207_ready = bool(nonblocking_installer()) and os.environ.get(_V207_READY_FLAG, "0").strip() == "1"
        if not v207_ready:
            return False

        rearm = importlib.import_module("bot.runtime_existing_strategy_heartbeat_rearm_v203_patch")
        rearm_installer = getattr(rearm, "install", None) or getattr(rearm, "install_import_hook", None)
        if not callable(rearm_installer):
            return False
        v203_ready = bool(rearm_installer()) and os.environ.get(_V203_READY_FLAG, "0").strip() == "1"
        if not v203_ready:
            return False

        late_bind = importlib.import_module("bot.runtime_execution_pipeline_late_binding_v204_patch")
        late_bind_installer = getattr(late_bind, "install", None) or getattr(late_bind, "install_import_hook", None)
        if not callable(late_bind_installer):
            return False
        v204_ready = bool(late_bind_installer()) and os.environ.get(_V204_READY_FLAG, "0").strip() == "1"
        if not v204_ready:
            return False

        ecel_symbols = importlib.import_module("bot.runtime_kraken_ecel_symbol_canonicalization_v206_patch")
        ecel_installer = getattr(ecel_symbols, "install", None) or getattr(ecel_symbols, "install_import_hook", None)
        if not callable(ecel_installer):
            return False
        return bool(ecel_installer()) and os.environ.get(_V206_READY_FLAG, "0").strip() == "1"
    except Exception as exc:
        LOGGER.critical(
            "RUNTIME_PHASE3_EXECUTION_FRAME_HANDOFF_V196_HEARTBEAT_CHAIN_FAILED marker=%s "
            "error=%s:%s trading_fail_closed=true",
            MARKER,
            type(exc).__name__,
            exc,
        )
        return False


def install() -> bool:
    """Reassert v196 cache admission and mandatory heartbeat startup-probe chain."""
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
        cache_ready = bool(callable(installed) and getattr(installed, _PATCH_ATTR, False))
        heartbeat_chain_ready = _install_v197() if cache_ready else False
        ready = bool(cache_ready and heartbeat_chain_ready)
        os.environ[_READY_FLAG] = "1" if ready else "0"
        if not ready:
            LOGGER.critical(
                "RUNTIME_PHASE3_EXECUTION_FRAME_HANDOFF_V196_FAILED marker=%s "
                "cache_ready=%s heartbeat_probe_chain=%s v197=%s v202=%s v207=%s v203=%s v204=%s v206=%s "
                "trading_fail_closed=true",
                MARKER,
                str(cache_ready).lower(),
                str(heartbeat_chain_ready).lower(),
                os.environ.get(_V197_READY_FLAG, "0"),
                os.environ.get(_V202_READY_FLAG, "0"),
                os.environ.get(_V207_READY_FLAG, "0"),
                os.environ.get(_V203_READY_FLAG, "0"),
                os.environ.get(_V204_READY_FLAG, "0"),
                os.environ.get(_V206_READY_FLAG, "0"),
            )
            return False

        LOGGER.critical(
            "RUNTIME_PHASE3_EXECUTION_FRAME_HANDOFF_V196 marker=%s ready=true "
            "same_cycle_only=true min_rows=%d ohlcv_required=true "
            "heartbeat_probe_pipeline_bridge_v197=true heartbeat_position_sync_wakeup_v202=true "
            "precore_strategy_lookup_v207=true existing_strategy_heartbeat_rearm_v203=true "
            "execution_pipeline_late_binding_v204=true kraken_ecel_symbol_canonicalization_v206=true "
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
