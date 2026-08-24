"""Bound heartbeat-only authenticated broker reads before execution proof (v210).

Production on 2026-08-24 showed the live ``HeartbeatTrade`` thread remaining
alive while the canonical heartbeat marker stayed missing after capital and
position sync had recovered. v208 already bounds heartbeat market discovery,
but ``TradingStrategy._heartbeat_auth_verify`` invokes broker auth/read methods
synchronously before market discovery. A slow or hung exchange read can
therefore strand the only heartbeat scheduler before it reaches the canonical
ExecutionPipeline and creates genuine ORDER/FILL proof.

v210 bounds only read-only broker methods when they are invoked by the dedicated
``HeartbeatTrade`` thread. Normal broker reads are unchanged. A timed-out
heartbeat read raises ``TimeoutError`` so the existing heartbeat logic fails
closed and retries; it never returns fabricated balances/accounts, never grants
execution authority, and never alters writer, nonce, risk, kill-switch,
reconciliation, capital, order, fill, or activation gates. At most one timed-out
worker per broker/method may remain in flight.
"""
from __future__ import annotations

import importlib
import logging
import os
import queue
import sys
import threading
from functools import wraps
from types import ModuleType
from typing import Any, Callable

LOGGER = logging.getLogger("nija.runtime_heartbeat_auth_probe_bound_v210")
MARKER = "20260824-heartbeat-auth-probe-bound-v210"
_READY_FLAG = "NIJA_HEARTBEAT_AUTH_PROBE_BOUND_V210_READY"
_PATCH_ATTR = "_nija_heartbeat_auth_probe_bound_v210"
_LOCK = threading.RLock()
_FLIGHTS: dict[tuple[int, str], threading.Thread] = {}

_BROKER_MODULE_NAMES = (
    "bot.broker_manager",
    "broker_manager",
)
_BROKER_CLASS_NAMES = (
    "CoinbaseBroker",
    "KrakenBroker",
    "OKXBroker",
    "AlpacaBroker",
)
_AUTH_READ_METHODS = (
    "get_account_balance",
    "get_balance",
    "get_accounts",
    "get_portfolio",
)


def _timeout_s() -> float:
    try:
        value = float(os.environ.get("NIJA_HEARTBEAT_AUTH_PROBE_TIMEOUT_S", "12") or 12.0)
    except (TypeError, ValueError):
        value = 12.0
    return max(1.0, min(30.0, value))


def _wrap_heartbeat_auth_method(
    current: Callable[..., Any],
    *,
    broker_class_name: str,
    method_name: str,
) -> Callable[..., Any]:
    """Bound a read only when called by the dedicated heartbeat scheduler."""
    if bool(getattr(current, _PATCH_ATTR, False)):
        return current

    @wraps(current)
    def bounded_auth_read(self: Any, *args: Any, **kwargs: Any) -> Any:
        if not threading.current_thread().name.startswith("HeartbeatTrade"):
            return current(self, *args, **kwargs)

        key = (id(self), method_name)
        with _LOCK:
            existing = _FLIGHTS.get(key)
            if existing is not None and existing.is_alive():
                LOGGER.warning(
                    "HEARTBEAT_AUTH_PROBE_V210_INFLIGHT marker=%s broker=%s method=%s "
                    "action=fail_closed_retry duplicate_worker=false normal_broker_reads_unchanged=true",
                    MARKER,
                    broker_class_name,
                    method_name,
                )
                raise TimeoutError(
                    f"heartbeat auth probe still in flight: {broker_class_name}.{method_name}"
                )

            result_queue: "queue.Queue[tuple[str, Any]]" = queue.Queue(maxsize=1)

            def _runner() -> None:
                try:
                    result_queue.put(("result", current(self, *args, **kwargs)))
                except BaseException as exc:
                    result_queue.put(("error", exc))

            worker = threading.Thread(
                target=_runner,
                name=f"HeartbeatAuthProbe-v210-{broker_class_name}-{method_name}",
                daemon=True,
            )
            _FLIGHTS[key] = worker
            worker.start()

        timeout = _timeout_s()
        try:
            kind, payload = result_queue.get(timeout=timeout)
        except queue.Empty:
            LOGGER.warning(
                "HEARTBEAT_AUTH_PROBE_V210_TIMEOUT marker=%s broker=%s method=%s timeout_s=%.2f "
                "action=fail_closed_retry worker_daemon=true duplicate_worker=false "
                "normal_broker_reads_unchanged=true balance_fabricated=false auth_fabricated=false "
                "execution_authority_granted=false proof_fabricated=false forced_trade=false "
                "safety_gates_bypassed=false",
                MARKER,
                broker_class_name,
                method_name,
                timeout,
            )
            raise TimeoutError(
                f"heartbeat auth probe timed out after {timeout:.2f}s: "
                f"{broker_class_name}.{method_name}"
            )

        if kind == "error":
            raise payload
        return payload

    setattr(bounded_auth_read, _PATCH_ATTR, True)
    setattr(bounded_auth_read, "__wrapped__", current)
    return bounded_auth_read


def _broker_module() -> ModuleType:
    for name in _BROKER_MODULE_NAMES:
        module = sys.modules.get(name)
        if isinstance(module, ModuleType):
            return module
    module = importlib.import_module("bot.broker_manager")
    if not isinstance(module, ModuleType):
        raise RuntimeError("broker_manager_module_unavailable")
    return module


def _patch_broker_auth_reads() -> int:
    module = _broker_module()
    patched = 0
    for class_name in _BROKER_CLASS_NAMES:
        broker_cls = getattr(module, class_name, None)
        if not isinstance(broker_cls, type):
            continue
        for method_name in _AUTH_READ_METHODS:
            current = getattr(broker_cls, method_name, None)
            if not callable(current):
                continue
            if not bool(getattr(current, _PATCH_ATTR, False)):
                setattr(
                    broker_cls,
                    method_name,
                    _wrap_heartbeat_auth_method(
                        current,
                        broker_class_name=class_name,
                        method_name=method_name,
                    ),
                )
            installed = getattr(broker_cls, method_name, None)
            if callable(installed) and bool(getattr(installed, _PATCH_ATTR, False)):
                patched += 1
    return patched


def _patch_release_manifest() -> bool:
    try:
        manifest = importlib.import_module("bot.runtime_release_manifest_patch")
        required = getattr(manifest, "_REQUIRED_FLAGS", None)
        if not isinstance(required, dict):
            return False
        required["heartbeat_auth_probe_bound_v210"] = _READY_FLAG
        return True
    except Exception:
        return False


def install() -> bool:
    try:
        patched = _patch_broker_auth_reads()
        manifest_ok = _patch_release_manifest()
    except Exception as exc:
        os.environ[_READY_FLAG] = "0"
        LOGGER.critical(
            "HEARTBEAT_AUTH_PROBE_V210_FAILED marker=%s error=%s:%s trading_fail_closed=true",
            MARKER,
            type(exc).__name__,
            exc,
        )
        return False

    ready = bool(patched > 0 and manifest_ok)
    os.environ[_READY_FLAG] = "1" if ready else "0"
    if not ready:
        LOGGER.critical(
            "HEARTBEAT_AUTH_PROBE_V210_FAILED marker=%s patched_surfaces=%s manifest=%s "
            "trading_fail_closed=true",
            MARKER,
            patched,
            str(manifest_ok).lower(),
        )
        return False

    LOGGER.critical(
        "HEARTBEAT_AUTH_PROBE_V210_READY marker=%s ready=true patched_surfaces=%s timeout_s=%.2f "
        "heartbeat_thread_only=true read_only=true normal_broker_reads_unchanged=true "
        "single_inflight_per_broker_method=true balance_fabricated=false auth_fabricated=false "
        "execution_authority_granted=false proof_fabricated=false forced_trade=false "
        "writer_nonce_risk_killswitch_reconciliation_capital_order_fill_gates_unchanged=true "
        "safety_gates_bypassed=false",
        MARKER,
        patched,
        _timeout_s(),
    )
    return True


def install_import_hook() -> bool:
    return install()


__all__ = [
    "MARKER",
    "install",
    "install_import_hook",
    "_timeout_s",
    "_wrap_heartbeat_auth_method",
    "_patch_broker_auth_reads",
]
