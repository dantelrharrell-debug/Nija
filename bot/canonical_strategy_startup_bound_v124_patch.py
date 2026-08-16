"""Bound canonical strategy publication work before the core thread starts.

Production release v123 reached broker/capital/nonce/position readiness but
remained in BootstrapState.THREADS_STARTING for many minutes with
strategy_ready=false. The canonical bot_main path publishes TradingStrategy
synchronously before start_trading_engine(). Several operations on that path
could block indefinitely.

v124 adds three conservative bounds:

* broker market-catalog reads used by TradingStrategy._populate_symbols;
* APEX/CoreLoop wiring hydration (removing its unbounded synchronous first try);
* the complete publish_canonical_strategy handoff, with late publication
  suppressed after its deadline.

No strategy, execution, broker, capital, nonce, position, writer, risk,
kill-switch, or bootstrap readiness is fabricated. No import hook is added.
"""
from __future__ import annotations

import logging
import os
import queue
import sys
import threading
from functools import wraps
from types import ModuleType
from typing import Any

LOGGER = logging.getLogger("nija.canonical_strategy_startup_bound_v124")
MARKER = "20260816-canonical-strategy-startup-bound-v124"
RELEASE_ID = "20260816-runtime-convergence-v124"
_FLAG = "NIJA_CANONICAL_STRATEGY_STARTUP_BOUND_V124_INSTALLED"
_DISCOVERY_PATCH_ATTR = "_nija_canonical_strategy_startup_bound_v124"
_WIRING_PATCH_ATTR = "_nija_canonical_strategy_wiring_bound_v124"
_PUBLICATION_PATCH_ATTR = "_nija_canonical_strategy_publication_bound_v124"
_PUBLISH_GUARD_ATTR = "_nija_canonical_strategy_publish_guard_v124"
_INSTALLED = False
_LOCK = threading.RLock()
_CANCELLED_PUBLICATION_THREADS: set[int] = set()
_CANCEL_LOCK = threading.RLock()


def _float_env(name: str, default: float, minimum: float = 0.1, maximum: float = 90.0) -> float:
    try:
        value = float(os.environ.get(name, default) or default)
    except (TypeError, ValueError):
        value = default
    return max(minimum, min(maximum, value))


def _symbol_timeout_s() -> float:
    return _float_env("NIJA_SYMBOL_DISCOVERY_TIMEOUT_S", 8.0, 0.1, 30.0)


def _wiring_timeout_s() -> float:
    return _float_env("NIJA_TRADING_STRATEGY_WIRING_TIMEOUT_S", 20.0, 0.1, 60.0)


def _publication_timeout_s() -> float:
    return _float_env("NIJA_CANONICAL_STRATEGY_PUBLICATION_TIMEOUT_S", 45.0, 1.0, 90.0)


def _patch_symbol_discovery(strategy_module: ModuleType) -> bool:
    cls = getattr(strategy_module, "TradingStrategy", None)
    call_with_timeout = getattr(strategy_module, "call_with_timeout", None)
    if not isinstance(cls, type) or not callable(call_with_timeout):
        return False

    current = getattr(cls, "_discover_broker_symbols", None)
    if not callable(current):
        return False
    if getattr(current, _DISCOVERY_PATCH_ATTR, False):
        return True

    @wraps(current)
    def _discover_broker_symbols_v124(self: Any, broker: Any):
        broker_name = "unknown"
        try:
            broker_name = str(self._broker_key_from_obj(broker) or "unknown")
        except Exception:
            broker_name = type(broker).__name__.replace("Broker", "").lower() or "unknown"

        timeout_s = _symbol_timeout_s()
        for method_name in ("get_available_markets", "get_all_products"):
            method = getattr(broker, method_name, None)
            if not callable(method):
                continue
            try:
                products, error = call_with_timeout(method, timeout_seconds=timeout_s)
            except BaseException as exc:
                products, error = None, exc

            if error is not None:
                LOGGER.warning(
                    "CANONICAL_STRATEGY_V124_SYMBOL_DISCOVERY_FAILED marker=%s broker=%s method=%s timeout_s=%.2f error=%s:%s fallback=true trading_fail_closed_unchanged=true",
                    MARKER,
                    broker_name,
                    method_name,
                    timeout_s,
                    type(error).__name__,
                    error,
                )
                continue
            if isinstance(products, list):
                try:
                    discovered = self._dedupe_symbols(products)
                except Exception:
                    discovered = [str(item).strip() for item in products if str(item).strip()]
                if discovered:
                    return discovered
        return []

    setattr(_discover_broker_symbols_v124, _DISCOVERY_PATCH_ATTR, True)
    setattr(_discover_broker_symbols_v124, "__wrapped__", current)
    setattr(cls, "_discover_broker_symbols", _discover_broker_symbols_v124)
    LOGGER.critical(
        "CANONICAL_STRATEGY_V124_SYMBOL_DISCOVERY_PATCHED marker=%s timeout_s=%.2f read_only=true fallback_preserved=true",
        MARKER,
        _symbol_timeout_s(),
    )
    return True


def _patch_wiring_bound(wiring_module: ModuleType) -> bool:
    current = getattr(wiring_module, "_bounded_hydrate_strategy_wiring", None)
    hydrate = getattr(wiring_module, "_hydrate_strategy_wiring", None)
    needs = getattr(wiring_module, "_needs_hydration", None)
    if not callable(current) or not callable(hydrate) or not callable(needs):
        return False
    if getattr(current, _WIRING_PATCH_ATTR, False):
        return True

    def _bounded_hydrate_v124(strategy: Any, broker: Any = None, reason: str = "runtime") -> bool:
        if not needs(strategy):
            return True

        timeout_s = _wiring_timeout_s()
        result_q: "queue.Queue[tuple[str, Any]]" = queue.Queue(maxsize=1)

        def _runner() -> None:
            try:
                result_q.put(("result", hydrate(strategy, broker=broker, reason=f"{reason}:v124")))
            except BaseException as exc:
                try:
                    result_q.put(("error", exc))
                except Exception:
                    pass

        worker = threading.Thread(
            target=_runner,
            name="canonical-strategy-wiring-v124",
            daemon=True,
        )
        worker.start()
        try:
            kind, payload = result_q.get(timeout=timeout_s)
        except queue.Empty:
            LOGGER.critical(
                "CANONICAL_STRATEGY_V124_WIRING_TIMEOUT marker=%s reason=%s timeout_s=%.2f worker_alive=%s strategy_ready=false execution_authority_unchanged=true",
                MARKER,
                reason,
                timeout_s,
                worker.is_alive(),
            )
            return not bool(needs(strategy))

        if kind == "error":
            LOGGER.warning(
                "CANONICAL_STRATEGY_V124_WIRING_ERROR marker=%s reason=%s error=%s:%s",
                MARKER,
                reason,
                type(payload).__name__,
                payload,
            )
            return False
        return bool(payload) and not bool(needs(strategy))

    setattr(_bounded_hydrate_v124, _WIRING_PATCH_ATTR, True)
    setattr(_bounded_hydrate_v124, "__wrapped__", current)
    setattr(wiring_module, "_bounded_hydrate_strategy_wiring", _bounded_hydrate_v124)
    LOGGER.critical(
        "CANONICAL_STRATEGY_V124_WIRING_BOUND_PATCHED marker=%s timeout_s=%.2f synchronous_unbounded_attempt=false import_hook_added=false",
        MARKER,
        _wiring_timeout_s(),
    )
    return True


def _patch_publication_bound(publication_module: ModuleType) -> bool:
    current_publish = getattr(publication_module, "_publish", None)
    current_entry = getattr(publication_module, "publish_canonical_strategy", None)
    if not callable(current_publish) or not callable(current_entry):
        return False
    if getattr(current_entry, _PUBLICATION_PATCH_ATTR, False):
        return True

    if not getattr(current_publish, _PUBLISH_GUARD_ATTR, False):
        @wraps(current_publish)
        def _guarded_publish_v124(strategy: Any) -> None:
            ident = threading.get_ident()
            with _CANCEL_LOCK:
                cancelled = ident in _CANCELLED_PUBLICATION_THREADS
            if cancelled:
                LOGGER.critical(
                    "CANONICAL_STRATEGY_V124_LATE_PUBLICATION_SUPPRESSED marker=%s thread_ident=%s strategy_ready=false execution_ready=false trading_fail_closed=true",
                    MARKER,
                    ident,
                )
                return None
            return current_publish(strategy)

        setattr(_guarded_publish_v124, _PUBLISH_GUARD_ATTR, True)
        setattr(_guarded_publish_v124, "__wrapped__", current_publish)
        setattr(publication_module, "_publish", _guarded_publish_v124)

    @wraps(current_entry)
    def _bounded_publish_canonical_strategy_v124(*args: Any, **kwargs: Any):
        timeout_s = _publication_timeout_s()
        result_q: "queue.Queue[tuple[str, Any, int]]" = queue.Queue(maxsize=1)
        started = threading.Event()
        worker_ident = [0]

        def _runner() -> None:
            ident = threading.get_ident()
            worker_ident[0] = ident
            started.set()
            try:
                result_q.put(("result", current_entry(*args, **kwargs), ident))
            except BaseException as exc:
                try:
                    result_q.put(("error", exc, ident))
                except Exception:
                    pass
            finally:
                with _CANCEL_LOCK:
                    _CANCELLED_PUBLICATION_THREADS.discard(ident)

        worker = threading.Thread(
            target=_runner,
            name="canonical-strategy-publication-v124",
            daemon=True,
        )
        worker.start()
        started.wait(timeout=min(1.0, timeout_s))
        try:
            kind, payload, ident = result_q.get(timeout=timeout_s)
        except queue.Empty:
            ident = worker_ident[0]
            if ident:
                with _CANCEL_LOCK:
                    _CANCELLED_PUBLICATION_THREADS.add(ident)
            LOGGER.critical(
                "CANONICAL_STRATEGY_V124_PUBLICATION_TIMEOUT marker=%s timeout_s=%.2f worker_alive=%s strategy_ready=false execution_ready=false runtime_execution_authority_unchanged=true trading_fail_closed=true",
                MARKER,
                timeout_s,
                worker.is_alive(),
            )
            return None, "publication_timeout_v124"

        if kind == "error":
            LOGGER.critical(
                "CANONICAL_STRATEGY_V124_PUBLICATION_ERROR marker=%s error=%s:%s trading_fail_closed=true",
                MARKER,
                type(payload).__name__,
                payload,
                exc_info=(type(payload), payload, payload.__traceback__),
            )
            return None, f"publication_error_v124:{type(payload).__name__}"
        return payload

    setattr(_bounded_publish_canonical_strategy_v124, _PUBLICATION_PATCH_ATTR, True)
    setattr(_bounded_publish_canonical_strategy_v124, "__wrapped__", current_entry)
    setattr(publication_module, "publish_canonical_strategy", _bounded_publish_canonical_strategy_v124)
    LOGGER.critical(
        "CANONICAL_STRATEGY_V124_PUBLICATION_BOUND_PATCHED marker=%s timeout_s=%.2f late_publication_suppressed=true fail_closed=true",
        MARKER,
        _publication_timeout_s(),
    )
    return True


def _patch_release_manifest() -> bool:
    manifest = sys.modules.get("bot.runtime_release_manifest_patch") or sys.modules.get(
        "runtime_release_manifest_patch"
    )
    if not isinstance(manifest, ModuleType):
        try:
            import bot.runtime_release_manifest_patch as manifest  # type: ignore[no-redef]
        except Exception:
            return False
    required = getattr(manifest, "_REQUIRED_FLAGS", None)
    if not isinstance(required, dict):
        return False
    required["canonical_strategy_startup_bound_v124"] = _FLAG
    manifest.RELEASE_ID = RELEASE_ID
    return True


def install() -> bool:
    global _INSTALLED
    with _LOCK:
        if _INSTALLED and os.environ.get(_FLAG) == "1":
            return True
        try:
            from bot import trading_strategy as strategy_module
            from bot import trading_strategy_apex_wiring_patch as wiring_module
            from bot import strategy_publication_patch as publication_module
        except Exception as exc:
            LOGGER.critical(
                "CANONICAL_STRATEGY_V124_IMPORT_FAILED marker=%s error=%s:%s trading_fail_closed=true",
                MARKER,
                type(exc).__name__,
                exc,
            )
            return False

        if not _patch_symbol_discovery(strategy_module):
            return False
        if not _patch_wiring_bound(wiring_module):
            return False
        if not _patch_publication_bound(publication_module):
            return False

        os.environ[_FLAG] = "1"
        if not _patch_release_manifest():
            os.environ.pop(_FLAG, None)
            return False
        _INSTALLED = True
        LOGGER.critical(
            "CANONICAL_STRATEGY_STARTUP_BOUND_V124_INSTALLED marker=%s symbol_timeout_s=%.2f wiring_timeout_s=%.2f publication_timeout_s=%.2f late_publication_suppressed=true strategy_readiness_synthetic=false execution_readiness_synthetic=false broker_io_read_only=true import_hook_added=false safety_gates_unchanged=true",
            MARKER,
            _symbol_timeout_s(),
            _wiring_timeout_s(),
            _publication_timeout_s(),
        )
        return True


def install_import_hook() -> bool:
    """Compatibility installer name; v124 deliberately adds no import hook."""
    return install()


__all__ = [
    "MARKER",
    "RELEASE_ID",
    "install",
    "install_import_hook",
    "_symbol_timeout_s",
    "_wiring_timeout_s",
    "_publication_timeout_s",
    "_patch_symbol_discovery",
    "_patch_wiring_bound",
    "_patch_publication_bound",
]
