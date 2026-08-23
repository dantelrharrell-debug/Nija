"""Bounded Phase 3 market-data concurrency attestation v171.

The actual liveness repair lives in ``phase3_scan_stall_guard_patch`` so the
prefetch and scoring body share one immutable Phase 3 deadline.  This module
reasserts the Kraken market-data stability patch, installs the updated Phase 3
guard, verifies that the bounded-prefetch and cache-first markers are present,
and publishes a release-readiness flag.

v196 additionally guarantees that any structurally valid 50+ candle OHLCV frame
accepted during the current Phase 3 cycle is eligible for the same-cycle cache.
Volume quality remains an independent downstream liquidity gate; it no longer
controls whether an already-scored frame may be reused by the execution handoff.

No signal thresholds, risk gates, execution-authority gates, broker routing,
kill switches, nonce rules, or order semantics are changed.
"""
from __future__ import annotations

import importlib
import logging
import os
import threading

LOGGER = logging.getLogger("nija.runtime_market_data_concurrency_v171")
MARKER = "20260820-runtime-market-data-concurrency-v171"
_READY_FLAG = "NIJA_RUNTIME_MARKET_DATA_CONCURRENCY_V171_READY"
_V196_READY_FLAG = "NIJA_RUNTIME_PHASE3_EXECUTION_FRAME_HANDOFF_V196_READY"
_LOCK = threading.RLock()


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


def _install_and_verify_phase3_guard() -> bool:
    try:
        guard = importlib.import_module("bot.phase3_scan_stall_guard_patch")
        installer = getattr(guard, "install_import_hook", None) or getattr(guard, "install", None)
        if not callable(installer):
            return False
        installer()

        # v196 is part of the v171 contract rather than a best-effort sidecar.
        # It changes only same-cycle cache admission; all downstream volume,
        # liquidity, min-notional, risk and execution-authority gates remain
        # authoritative and unchanged.
        handoff = importlib.import_module("bot.runtime_phase3_execution_frame_handoff_v196_patch")
        handoff_installer = getattr(handoff, "install", None) or getattr(handoff, "install_import_hook", None)
        if not callable(handoff_installer) or not bool(handoff_installer()):
            return False

        core = importlib.import_module("bot.nija_core_loop")
        cls = getattr(core, "NijaCoreLoop", None)
        if not isinstance(cls, type):
            return False
        phase3 = getattr(cls, "_phase3_scan_and_enter", None)
        fetch = getattr(cls, "_fetch_df", None)
        prefetch_attr = str(getattr(guard, "_PREFETCH_PATCH_ATTR", "") or "")
        if not prefetch_attr:
            return False
        return bool(
            callable(phase3)
            and callable(fetch)
            and getattr(phase3, prefetch_attr, False)
            and getattr(fetch, prefetch_attr, False)
            and os.environ.get(_V196_READY_FLAG, "0").strip() == "1"
        )
    except Exception:
        return False


def _patch_release_manifest() -> bool:
    try:
        manifest = importlib.import_module("bot.runtime_release_manifest_patch")
        required = getattr(manifest, "_REQUIRED_FLAGS", None)
        if not isinstance(required, dict):
            return False
        required["runtime_market_data_concurrency_v171"] = _READY_FLAG
        required["runtime_phase3_execution_frame_handoff_v196"] = _V196_READY_FLAG
        return True
    except Exception:
        return False


def install() -> bool:
    with _LOCK:
        os.environ.setdefault("NIJA_PHASE3_FETCH_DEADLINE_SKIP_ENABLED", "true")
        os.environ.setdefault("NIJA_PHASE3_SCAN_DEADLINE_S", "24")
        os.environ.setdefault("NIJA_PHASE3_PREFETCH_ENABLED", "true")
        os.environ.setdefault("NIJA_PHASE3_PREFETCH_WORKERS", "6")

        stability_ok = _reassert_market_data_stability()
        phase3_ok = _install_and_verify_phase3_guard()
        manifest_ok = _patch_release_manifest()
        ready = bool(stability_ok and phase3_ok and manifest_ok)
        os.environ[_READY_FLAG] = "1" if ready else "0"
        if not ready:
            LOGGER.critical(
                "RUNTIME_MARKET_DATA_CONCURRENCY_V171_FAILED marker=%s stability=%s phase3=%s "
                "manifest=%s v196=%s trading_fail_closed=true",
                MARKER,
                str(stability_ok).lower(),
                str(phase3_ok).lower(),
                str(manifest_ok).lower(),
                os.environ.get(_V196_READY_FLAG, "0"),
            )
            return False
        LOGGER.critical(
            "RUNTIME_MARKET_DATA_CONCURRENCY_V171 marker=%s ready=true bounded_prefetch=true "
            "single_phase3_deadline=true same_cycle_cache_first=true market_data_stability_reasserted=true "
            "execution_frame_handoff_v196=true signal_thresholds_unchanged=true forced_trade=false "
            "safety_gates_bypassed=false",
            MARKER,
        )
        return True


def install_import_hook() -> bool:
    return install()


__all__ = [
    "MARKER",
    "install",
    "install_import_hook",
    "_install_and_verify_phase3_guard",
]
