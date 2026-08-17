"""Start the canonical TradingStrategy without blocking core startup on symbol I/O.

Production v125 proves writer, broker, balance, capital, risk, nonce and position
sync readiness, and the terminal import bypass is healthy, yet bootstrap remains
in THREADS_STARTING with strategy_ready=false/core_registered=false.  The
remaining synchronous publication path constructs TradingStrategy, whose
``__init__`` performs symbol-universe discovery before bot_main can start and
register the core thread.  Even with per-call v124 bounds, multiple venue/catalog
reads can consume the complete publication deadline.

v126 keeps the real TradingStrategy constructor and the real connected broker,
but suppresses only constructor-time symbol discovery.  Discovery is deferred
to a daemon worker after the strategy object has been published so bot_main can
immediately start/register the core.  No readiness, execution authority, risk,
nonce, capital, writer, kill-switch, or bootstrap proof is fabricated.
"""
from __future__ import annotations

import importlib
import logging
import os
import sys
import threading
import time
from functools import wraps
from types import ModuleType
from typing import Any

LOGGER = logging.getLogger("nija.canonical_strategy_fast_start_v126")
MARKER = "20260816-canonical-strategy-fast-start-v126"
RELEASE_ID = "20260816-runtime-convergence-v126"
_FLAG = "NIJA_CANONICAL_STRATEGY_FAST_START_V126_INSTALLED"
_PATCH_ATTR = "_nija_canonical_strategy_fast_start_v126"
_LOCK = threading.RLock()
_CONSTRUCT_LOCK = threading.RLock()
_INSTALLED = False


def _canonical_import(name: str) -> ModuleType:
    existing = sys.modules.get(name)
    if isinstance(existing, ModuleType):
        return existing
    bootstrap = getattr(importlib, "_bootstrap", None)
    gcd_import = getattr(bootstrap, "_gcd_import", None) if bootstrap is not None else None
    if not callable(gcd_import):
        raise RuntimeError("canonical_import_primitive_unavailable")
    module = gcd_import(name)
    if not isinstance(module, ModuleType):
        raise RuntimeError(f"canonical_import_invalid_module:{name}")
    return module


def _deferred_symbol_hydration(strategy: Any, original_populate: Any) -> None:
    """Populate symbols after publication without delaying the core handoff."""
    # Give bot_main a clean scheduling window to enter start_trading_engine and
    # register the core thread before any market-catalog reads begin.
    delay_s = max(0.25, min(10.0, float(os.environ.get("NIJA_V126_SYMBOL_DEFER_S", "2") or 2.0)))
    time.sleep(delay_s)
    try:
        original_populate(strategy)
        LOGGER.critical(
            "CANONICAL_STRATEGY_V126_SYMBOL_HYDRATION_COMPLETE marker=%s symbols=%d deferred=true",
            MARKER,
            len(getattr(strategy, "symbols", []) or []),
        )
    except Exception as exc:
        LOGGER.warning(
            "CANONICAL_STRATEGY_V126_SYMBOL_HYDRATION_FAILED marker=%s err=%s:%s deferred=true core_start_unblocked=true",
            MARKER,
            type(exc).__name__,
            exc,
        )


def _patch_build_strategy(publication: ModuleType, strategy_module: ModuleType) -> bool:
    current = getattr(publication, "_build_strategy", None)
    best_broker = getattr(publication, "_best_broker_from_results", None)
    sync_broker = getattr(publication, "_sync_broker_into_strategy", None)
    cls = getattr(strategy_module, "TradingStrategy", None)
    if not callable(current) or not callable(best_broker) or not isinstance(cls, type):
        return False
    if bool(getattr(current, _PATCH_ATTR, False)):
        return True

    @wraps(current)
    def _build_strategy_v126(strategy_cls: type, brokers: dict[Any, dict[str, Any]]):
        if strategy_cls is not cls:
            return current(strategy_cls, brokers)

        broker = best_broker(brokers)
        if broker is None or not bool(getattr(broker, "connected", False)):
            LOGGER.critical(
                "CANONICAL_STRATEGY_V126_FAST_START_BLOCKED marker=%s reason=no_connected_entry_broker trading_fail_closed=true",
                MARKER,
            )
            return current(strategy_cls, brokers)

        with _CONSTRUCT_LOCK:
            original_populate = getattr(strategy_cls, "_populate_symbols", None)
            if not callable(original_populate):
                return current(strategy_cls, brokers)

            @wraps(original_populate)
            def _skip_constructor_symbol_discovery(self: Any) -> None:
                # Preserve the state shape expected by run_cycle while avoiding
                # all exchange catalog I/O on the pre-core critical path.
                ensure = getattr(self, "_ensure_symbol_universe_state", None)
                if callable(ensure):
                    ensure()
                if getattr(self, "symbols", None) is None:
                    self.symbols = []
                LOGGER.critical(
                    "CANONICAL_STRATEGY_V126_SYMBOL_DISCOVERY_DEFERRED marker=%s broker=%s constructor_path=true",
                    MARKER,
                    type(broker).__name__,
                )

            setattr(strategy_cls, "_populate_symbols", _skip_constructor_symbol_discovery)
            heartbeat_before = os.environ.get("HEARTBEAT_TRADE")
            os.environ["HEARTBEAT_TRADE"] = "false"
            try:
                strategy = strategy_cls(broker_results=brokers)
            finally:
                setattr(strategy_cls, "_populate_symbols", original_populate)
                if heartbeat_before is None:
                    os.environ.pop("HEARTBEAT_TRADE", None)
                else:
                    os.environ["HEARTBEAT_TRADE"] = heartbeat_before

        if getattr(strategy, "broker", None) is None and callable(sync_broker):
            sync_broker(strategy, broker)
        if getattr(strategy, "broker", None) is None:
            raise RuntimeError("v126_strategy_broker_missing_after_construct")
        if not callable(getattr(strategy, "run_cycle", None)):
            raise RuntimeError("v126_strategy_run_cycle_missing")

        worker = threading.Thread(
            target=_deferred_symbol_hydration,
            args=(strategy, original_populate),
            name="canonical-strategy-symbol-hydration-v126",
            daemon=True,
        )
        worker.start()
        LOGGER.critical(
            "CANONICAL_STRATEGY_V126_FAST_START_READY marker=%s strategy=%s broker=%s symbol_discovery_deferred=true heartbeat_startup_suppressed=true execution_authority_unchanged=true",
            MARKER,
            type(strategy).__name__,
            type(getattr(strategy, "broker", None)).__name__,
        )
        return strategy

    setattr(_build_strategy_v126, _PATCH_ATTR, True)
    setattr(_build_strategy_v126, "__wrapped__", current)
    publication._build_strategy = _build_strategy_v126
    return True


def _patch_release_manifest() -> bool:
    manifest = _canonical_import("bot.runtime_release_manifest_patch")
    required = getattr(manifest, "_REQUIRED_FLAGS", None)
    if not isinstance(required, dict):
        return False
    required["canonical_strategy_fast_start_v126"] = _FLAG
    manifest.RELEASE_ID = RELEASE_ID
    return True


def install() -> bool:
    global _INSTALLED
    with _LOCK:
        if _INSTALLED and os.environ.get(_FLAG) == "1":
            return True
        try:
            publication = _canonical_import("bot.strategy_publication_patch")
            strategy_module = _canonical_import("bot.trading_strategy")
            patch_ok = _patch_build_strategy(publication, strategy_module)
            manifest_ok = _patch_release_manifest()
        except Exception as exc:
            os.environ.pop(_FLAG, None)
            LOGGER.critical(
                "CANONICAL_STRATEGY_FAST_START_V126_INSTALL_FAILED marker=%s err=%s:%s trading_fail_closed=true",
                MARKER,
                type(exc).__name__,
                exc,
                exc_info=True,
            )
            return False
        if not (patch_ok and manifest_ok):
            os.environ.pop(_FLAG, None)
            return False
        os.environ[_FLAG] = "1"
        _INSTALLED = True
        LOGGER.critical(
            "CANONICAL_STRATEGY_FAST_START_V126_INSTALLED marker=%s release=%s symbol_io_precore=false real_strategy_constructor=true real_connected_broker_required=true readiness_synthetic=false execution_authority_unchanged=true",
            MARKER,
            RELEASE_ID,
        )
        return True


def install_import_hook() -> bool:
    return install()


__all__ = [
    "MARKER",
    "RELEASE_ID",
    "install",
    "install_import_hook",
    "_patch_build_strategy",
    "_deferred_symbol_hydration",
]
