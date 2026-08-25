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
reconciliation, capital, order, fill, or activation gates. At most one worker per
broker/method may be in flight.

The 2026-08-25 flight-retirement hardening closes a liveness gap found in
production. Previously, the outer 12-second timeout returned to the heartbeat
scheduler while the daemon worker could remain parked behind Kraken's global API
lock. The worker stayed in ``_FLIGHTS`` forever, so every later heartbeat attempt
failed with ``heartbeat auth probe still in flight``. The hardened path:

* reasserts v121's bounded Kraken read-lock and HTTP timeout wrappers immediately
  before every Kraken heartbeat auth read;
* marks a timed-out flight cancelled so any late result is discarded and can
  never become a heartbeat success;
* retires the exact flight from ``_FLIGHTS`` in the worker's ``finally`` block as
  soon as the underlying read exits, including error paths;
* never starts a replacement while the prior worker is still executing, thereby
  preserving the single-private-read/no-duplicate contract.

Python cannot safely terminate a thread that is already inside third-party HTTP
code, so this patch does not pretend to kill it. Instead v121 makes the underlying
Kraken read itself bounded. A process deployment also terminates any worker that
predates this fix. If a bounded worker still outlives the heartbeat timeout, the
next heartbeat remains fail-closed until that exact worker retires; no duplicate
private read is launched.

v211 is installed as a mandatory companion after v210. It closes the final
pipeline-local startup-probe circularity proven in production: v197 can reverify
and admit the whitelisted heartbeat probe while Pipeline._dispatch still sees
dispatch_enabled=false from the pre-LIVE canonical snapshot. v211 changes only
the pipeline-local snapshot for an already-authorized heartbeat probe; canonical
lifecycle/coordinator truth and all downstream safety/order/fill gates remain
unchanged.
"""
from __future__ import annotations

import importlib
import logging
import os
import queue
import sys
import threading
import time
from functools import wraps
from types import ModuleType
from typing import Any, Callable

LOGGER = logging.getLogger("nija.runtime_heartbeat_auth_probe_bound_v210")
MARKER = "20260824-heartbeat-auth-probe-bound-v210"
FLIGHT_RETIRE_MARKER = "20260825-heartbeat-auth-flight-retirement-v231"
_READY_FLAG = "NIJA_HEARTBEAT_AUTH_PROBE_BOUND_V210_READY"
_V211_READY_FLAG = "NIJA_HEARTBEAT_DISPATCH_SCOPE_V211_READY"
_PATCH_ATTR = "_nija_heartbeat_auth_probe_bound_v210"
_LOCK = threading.RLock()
_FLIGHTS: dict[tuple[int, str], threading.Thread] = {}
_FLIGHT_CANCEL: dict[tuple[int, str], threading.Event] = {}

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


def _retire_flight(
    key: tuple[int, str],
    worker: threading.Thread,
    *,
    broker_class_name: str,
    method_name: str,
) -> None:
    """Remove only the exact completed flight from the single-flight registry."""
    cancelled = False
    with _LOCK:
        if _FLIGHTS.get(key) is not worker:
            return
        cancel_event = _FLIGHT_CANCEL.pop(key, None)
        cancelled = bool(cancel_event is not None and cancel_event.is_set())
        _FLIGHTS.pop(key, None)
    LOGGER.info(
        "HEARTBEAT_AUTH_FLIGHT_V231_RETIRED marker=%s broker=%s method=%s "
        "cancelled=%s duplicate_worker=false late_result_admitted=false",
        FLIGHT_RETIRE_MARKER,
        broker_class_name,
        method_name,
        str(cancelled).lower(),
    )


def _reassert_kraken_read_bounds(broker: Any) -> bool:
    """Ensure v121 owns both Kraken lock admission and HTTP read timeouts.

    v121 deliberately patches ``KrakenBroker._kraken_private_call`` rather than
    heartbeat code. Runtime import/reassertion order can replace that wrapper, so
    heartbeat auth verifies it immediately before starting a private read.
    """
    try:
        v121 = importlib.import_module("bot.kraken_read_timeout_v121_patch")
        patch_broker = getattr(v121, "_patch_broker_manager", None)
        wrap_api = getattr(v121, "_wrap_api", None)
        broker_ok = bool(callable(patch_broker) and patch_broker())
        api = getattr(broker, "api", None)
        api_ok = True if api is None else bool(callable(wrap_api) and wrap_api(api))
        ready = bool(broker_ok and api_ok)
        if not ready:
            LOGGER.critical(
                "HEARTBEAT_AUTH_FLIGHT_V231_KRAKEN_BOUNDS_NOT_READY marker=%s "
                "broker_patch=%s api_patch=%s trading_fail_closed=true",
                FLIGHT_RETIRE_MARKER,
                str(broker_ok).lower(),
                str(api_ok).lower(),
            )
        return ready
    except Exception as exc:
        LOGGER.critical(
            "HEARTBEAT_AUTH_FLIGHT_V231_KRAKEN_BOUNDS_ERROR marker=%s err=%s:%s "
            "trading_fail_closed=true",
            FLIGHT_RETIRE_MARKER,
            type(exc).__name__,
            exc,
        )
        return False


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

        # Kraken has an additional process-wide private-API RLock. Reassert the
        # existing v121 bounded lock + HTTP wrappers before every heartbeat read
        # so a late runtime wrapper replacement cannot recreate an orphan flight.
        if broker_class_name == "KrakenBroker" and not _reassert_kraken_read_bounds(self):
            raise TimeoutError(
                "heartbeat auth probe blocked: Kraken bounded read protections unavailable"
            )

        key = (id(self), method_name)
        with _LOCK:
            existing = _FLIGHTS.get(key)
            if existing is not None:
                if existing.is_alive():
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
                # Defensive stale-entry cleanup. The runner normally retires its
                # own mapping in finally; this path covers an interrupted cleanup.
                _FLIGHTS.pop(key, None)
                _FLIGHT_CANCEL.pop(key, None)

            result_queue: "queue.Queue[tuple[str, Any]]" = queue.Queue(maxsize=1)
            cancel_event = threading.Event()
            worker_ref: dict[str, threading.Thread] = {}

            def _publish(kind: str, payload: Any) -> None:
                if cancel_event.is_set():
                    LOGGER.info(
                        "HEARTBEAT_AUTH_FLIGHT_V231_LATE_RESULT_DISCARDED marker=%s "
                        "broker=%s method=%s kind=%s execution_proof_fabricated=false",
                        FLIGHT_RETIRE_MARKER,
                        broker_class_name,
                        method_name,
                        kind,
                    )
                    return
                try:
                    result_queue.put_nowait((kind, payload))
                except queue.Full:
                    # The caller already has a terminal result; never overwrite it.
                    return

            def _runner() -> None:
                try:
                    if cancel_event.is_set():
                        return
                    _publish("result", current(self, *args, **kwargs))
                except BaseException as exc:
                    _publish("error", exc)
                finally:
                    worker = worker_ref.get("worker")
                    if worker is not None:
                        _retire_flight(
                            key,
                            worker,
                            broker_class_name=broker_class_name,
                            method_name=method_name,
                        )

            worker = threading.Thread(
                target=_runner,
                name=f"HeartbeatAuthProbe-v210-{broker_class_name}-{method_name}",
                daemon=True,
            )
            worker_ref["worker"] = worker
            _FLIGHTS[key] = worker
            _FLIGHT_CANCEL[key] = cancel_event
            worker.start()

        timeout = _timeout_s()
        try:
            kind, payload = result_queue.get(timeout=timeout)
        except queue.Empty:
            # Cancellation means only "do not admit a late result". It does not
            # claim that Python terminated third-party code. The exact worker
            # remains registered until its finally block runs, so a retry cannot
            # create a duplicate private request.
            cancel_event.set()
            LOGGER.warning(
                "HEARTBEAT_AUTH_PROBE_V210_TIMEOUT marker=%s retire_marker=%s "
                "broker=%s method=%s timeout_s=%.2f action=fail_closed_retry "
                "worker_cancelled_logically=true worker_retire_on_exit=true "
                "duplicate_worker=false normal_broker_reads_unchanged=true "
                "balance_fabricated=false auth_fabricated=false "
                "execution_authority_granted=false proof_fabricated=false forced_trade=false "
                "safety_gates_bypassed=false",
                MARKER,
                FLIGHT_RETIRE_MARKER,
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


def _install_v211() -> bool:
    try:
        module = importlib.import_module("bot.runtime_heartbeat_dispatch_scope_v211_patch")
        installer = getattr(module, "install", None) or getattr(module, "install_import_hook", None)
        if not callable(installer):
            return False
        return bool(installer()) and os.environ.get(_V211_READY_FLAG, "0").strip() == "1"
    except Exception as exc:
        LOGGER.critical(
            "HEARTBEAT_AUTH_PROBE_V210_V211_FAILED marker=%s error=%s:%s trading_fail_closed=true",
            MARKER,
            type(exc).__name__,
            exc,
        )
        return False


def _patch_release_manifest() -> bool:
    try:
        manifest = importlib.import_module("bot.runtime_release_manifest_patch")
        required = getattr(manifest, "_REQUIRED_FLAGS", None)
        if not isinstance(required, dict):
            return False
        required["heartbeat_auth_probe_bound_v210"] = _READY_FLAG
        required["heartbeat_dispatch_scope_v211"] = _V211_READY_FLAG
        return True
    except Exception:
        return False


def install() -> bool:
    try:
        patched = _patch_broker_auth_reads()
        manifest_ok = _patch_release_manifest()
        v211_ok = _install_v211()
    except Exception as exc:
        os.environ[_READY_FLAG] = "0"
        LOGGER.critical(
            "HEARTBEAT_AUTH_PROBE_V210_FAILED marker=%s error=%s:%s trading_fail_closed=true",
            MARKER,
            type(exc).__name__,
            exc,
        )
        return False

    ready = bool(patched > 0 and manifest_ok and v211_ok)
    os.environ[_READY_FLAG] = "1" if ready else "0"
    if not ready:
        LOGGER.critical(
            "HEARTBEAT_AUTH_PROBE_V210_FAILED marker=%s patched_surfaces=%s manifest=%s v211=%s "
            "trading_fail_closed=true",
            MARKER,
            patched,
            str(manifest_ok).lower(),
            str(v211_ok).lower(),
        )
        return False

    LOGGER.critical(
        "HEARTBEAT_AUTH_PROBE_V210_READY marker=%s retire_marker=%s ready=true patched_surfaces=%s timeout_s=%.2f "
        "heartbeat_thread_only=true read_only=true normal_broker_reads_unchanged=true "
        "single_inflight_per_broker_method=true exact_flight_retirement=true "
        "late_timeout_results_discarded=true kraken_v121_reasserted_per_read=true "
        "heartbeat_dispatch_scope_v211=true balance_fabricated=false auth_fabricated=false "
        "execution_authority_granted=false proof_fabricated=false forced_trade=false "
        "writer_nonce_risk_killswitch_reconciliation_capital_order_fill_gates_unchanged=true "
        "safety_gates_bypassed=false",
        MARKER,
        FLIGHT_RETIRE_MARKER,
        patched,
        _timeout_s(),
    )
    return True


def install_import_hook() -> bool:
    return install()


__all__ = [
    "MARKER",
    "FLIGHT_RETIRE_MARKER",
    "install",
    "install_import_hook",
    "_timeout_s",
    "_retire_flight",
    "_reassert_kraken_read_bounds",
    "_wrap_heartbeat_auth_method",
    "_patch_broker_auth_reads",
]
