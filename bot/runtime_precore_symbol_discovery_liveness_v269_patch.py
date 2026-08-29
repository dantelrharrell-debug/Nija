"""Bound pre-core market-symbol discovery so startup can reach core registration.

Production runtime b02a2238 reached TradingStrategy construction but an earlier
cycle remained without a registered core until the writer's 600 second terminal
startup deadline. TradingStrategy._populate_symbols() performs synchronous,
read-only get_available_markets()/get_all_products() calls before bot_main can
start and register the canonical core thread. A broker read that never returns
can therefore pin the only pre-core startup path indefinitely.

v269 bounds only those read-only discovery calls and keeps at most one in-flight
worker for each broker/method. A timeout does not mark the broker healthy,
does not publish strategy or execution readiness, and does not mutate capital,
nonce, kill-switch, risk, order, fill, or trading state. TradingStrategy's
existing broker-safe fallback symbol universe remains authoritative whenever
live discovery is unavailable.
"""
from __future__ import annotations

import importlib
import logging
import os
import queue
import threading
from functools import wraps
from typing import Any

LOGGER = logging.getLogger("nija.runtime_precore_symbol_discovery_liveness_v269")
MARKER = "20260828-precore-symbol-discovery-liveness-v269"
RELEASE_ID = "20260828-runtime-convergence-v269"
_READY_FLAG = "NIJA_RUNTIME_PRECORE_SYMBOL_DISCOVERY_LIVENESS_V269_READY"
_PATCH_ATTR = "_nija_runtime_precore_symbol_discovery_liveness_v269"
_LOCK = threading.RLock()
_FLIGHT_LOCK = threading.RLock()
_FLIGHTS: dict[tuple[int, str], threading.Thread] = {}


def _timeout_s() -> float:
    try:
        value = float(os.environ.get("NIJA_PRECORE_SYMBOL_DISCOVERY_TIMEOUT_S", "5") or 5.0)
    except (TypeError, ValueError):
        value = 5.0
    return max(0.5, min(15.0, value))


def _bounded_read(broker: Any, method_name: str) -> Any:
    """Execute one read-only discovery call with a per-method single-flight."""
    method = getattr(broker, method_name, None)
    if not callable(method):
        raise AttributeError(method_name)

    key = (id(broker), method_name)
    result_queue: "queue.Queue[tuple[str, Any]]" = queue.Queue(maxsize=1)

    with _FLIGHT_LOCK:
        existing = _FLIGHTS.get(key)
        if existing is not None and existing.is_alive():
            raise TimeoutError(f"precore_symbol_discovery_inflight:{method_name}")
        _FLIGHTS.pop(key, None)
        worker_ref: dict[str, threading.Thread] = {}

        def _runner() -> None:
            try:
                result_queue.put_nowait(("result", method()))
            except BaseException as exc:
                try:
                    result_queue.put_nowait(("error", exc))
                except queue.Full:
                    pass
            finally:
                worker = worker_ref.get("worker")
                with _FLIGHT_LOCK:
                    if worker is not None and _FLIGHTS.get(key) is worker:
                        _FLIGHTS.pop(key, None)

        worker = threading.Thread(
            target=_runner,
            name=f"PrecoreSymbolDiscovery-{type(broker).__name__}-{method_name}",
            daemon=True,
        )
        worker_ref["worker"] = worker
        _FLIGHTS[key] = worker
        worker.start()

    timeout = _timeout_s()
    try:
        kind, payload = result_queue.get(timeout=timeout)
    except queue.Empty as exc:
        raise TimeoutError(
            f"precore_symbol_discovery_timeout:{method_name}:{timeout:.2f}s"
        ) from exc
    if kind == "error":
        raise payload
    return payload


def _patch_trading_strategy() -> bool:
    try:
        module = importlib.import_module("bot.trading_strategy")
        cls = getattr(module, "TradingStrategy", None)
    except Exception as exc:
        LOGGER.error(
            "PRECORE_SYMBOL_DISCOVERY_V269_IMPORT_FAILED marker=%s error=%s:%s",
            MARKER,
            type(exc).__name__,
            exc,
        )
        return False
    if not isinstance(cls, type):
        return False

    current = getattr(cls, "_discover_broker_symbols", None)
    if not callable(current):
        return False
    if bool(getattr(current, _PATCH_ATTR, False)):
        return True

    original = current

    @wraps(original)
    def bounded_discovery(self: Any, broker: Any) -> list[str]:
        broker_name = "unknown"
        try:
            broker_name = str(self._broker_key_from_obj(broker) or "unknown")
        except Exception:
            broker_name = type(broker).__name__.lower()

        for method_name in ("get_available_markets", "get_all_products"):
            if not callable(getattr(broker, method_name, None)):
                continue
            try:
                products = _bounded_read(broker, method_name)
            except TimeoutError as exc:
                LOGGER.warning(
                    "PRECORE_SYMBOL_DISCOVERY_V269_TIMEOUT marker=%s broker=%s method=%s "
                    "timeout_s=%.2f detail=%s read_only=true single_flight=true "
                    "fallback_preserved=true broker_health_unchanged=true",
                    MARKER,
                    broker_name,
                    method_name,
                    _timeout_s(),
                    exc,
                )
                continue
            except Exception as exc:
                LOGGER.info(
                    "PRECORE_SYMBOL_DISCOVERY_V269_READ_FAILED marker=%s broker=%s method=%s "
                    "error=%s:%s fallback_preserved=true broker_health_unchanged=true",
                    MARKER,
                    broker_name,
                    method_name,
                    type(exc).__name__,
                    exc,
                )
                continue

            if isinstance(products, list):
                dedupe = getattr(self, "_dedupe_symbols", None)
                if callable(dedupe):
                    discovered = list(dedupe(products) or [])
                else:
                    seen: set[str] = set()
                    discovered = []
                    for raw in products:
                        symbol = str(raw or "").strip()
                        if symbol and symbol not in seen:
                            seen.add(symbol)
                            discovered.append(symbol)
                if discovered:
                    return discovered
        # Preserve the original caller contract: _populate_symbols() owns the
        # asset-class-safe fallback when discovery yields no symbols.
        return []

    setattr(bounded_discovery, _PATCH_ATTR, True)
    setattr(bounded_discovery, "__wrapped__", original)
    cls._discover_broker_symbols = bounded_discovery
    return True


def _patch_release_manifest() -> bool:
    try:
        manifest = importlib.import_module("bot.runtime_release_manifest_patch")
        required = getattr(manifest, "_REQUIRED_FLAGS", None)
        installers = getattr(manifest, "_INSTALLERS", None)
        if not isinstance(required, dict):
            return False
        required["precore_symbol_discovery_liveness_v269"] = _READY_FLAG
        own = ("bot.runtime_precore_symbol_discovery_liveness_v269_patch", "install_import_hook")
        if isinstance(installers, tuple) and own not in installers:
            manifest._INSTALLERS = tuple(installers) + (own,)
        return True
    except Exception:
        return False


def install() -> bool:
    with _LOCK:
        patched = _patch_trading_strategy()
        manifest = _patch_release_manifest()
        ready = bool(patched and manifest)
        os.environ[_READY_FLAG] = "1" if ready else "0"
        if not ready:
            LOGGER.critical(
                "RUNTIME_PRECORE_SYMBOL_DISCOVERY_LIVENESS_V269_FAILED marker=%s "
                "strategy_patch=%s manifest=%s trading_fail_closed=true",
                MARKER,
                str(patched).lower(),
                str(manifest).lower(),
            )
            return False
        LOGGER.critical(
            "RUNTIME_PRECORE_SYMBOL_DISCOVERY_LIVENESS_V269 marker=%s ready=true "
            "timeout_s=%.2f read_only_market_discovery=true single_flight=true "
            "late_result_discarded=true broker_safe_fallback_preserved=true "
            "capital_thresholds_unchanged=true freshness_extended=false "
            "nonce_policy_unchanged=true kill_switch_unchanged=true risk_gates_unchanged=true "
            "order_fill_gates_unchanged=true execution_proof_fabricated=false "
            "forced_trade=false forced_activation=false safety_gates_bypassed=false",
            MARKER,
            _timeout_s(),
        )
        return True


def install_import_hook() -> bool:
    return install()


__all__ = [
    "MARKER",
    "RELEASE_ID",
    "install",
    "install_import_hook",
    "_timeout_s",
    "_bounded_read",
    "_patch_trading_strategy",
    "_patch_release_manifest",
]
