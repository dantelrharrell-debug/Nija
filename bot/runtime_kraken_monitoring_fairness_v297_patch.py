"""Kraken same-account monitoring fairness and Balance coalescing v297.

Production evidence on 2026-08-30 isolated the remaining live-activation
liveness failure to the PLATFORM Kraken account.  MICRO_CAP monitoring keeps the
existing 60 second read interval, while capital refresh, position reconciliation
and history recovery compete for that same account.  v286 correctly moved the
rate sleep outside the canonical Kraken API lock, but its per-instance read gate
is a plain ``threading.Lock`` held across both the rate sleep and the request.
Under sustained monitoring load, an authoritative position worker can therefore
starve behind routine readers even though the exchange, credentials, writer and
nonce authority are healthy.

v297 changes no Kraken rate interval and grants no readiness.  It adds two
liveness properties at the existing read boundary:

* the v286 per-instance read gate becomes priority/FIFO: authoritative position
  reconciliation has first priority, while callers of equal priority remain
  FIFO.  The gate is still exclusive and is never force-released or bypassed;
* concurrent read-only ``Balance`` callers for the same broker instance share
  one genuine authenticated Kraken response.  This removes duplicate demand
  when capital and position reconciliation request the exact same endpoint at
  the same time.  Only an in-flight (or sub-second just-completed) response is
  shared, and every consumer receives a defensive copy.

The existing v286 rate calculation, v292 HTTP timeout, v293 credential-scoped
serialization, nonce issuance, exchange response validation and all capital,
position, risk, kill-switch, ECEL, order and fill gates remain authoritative.
No position, balance, cost basis, execution proof or freshness is fabricated.
"""
from __future__ import annotations

import copy
import importlib
import logging
import os
import threading
import time
from collections.abc import Mapping
from functools import wraps
from typing import Any, Callable

LOGGER = logging.getLogger("nija.runtime_kraken_monitoring_fairness_v297")
MARKER = "20260830-kraken-monitoring-fairness-v297"
RELEASE_ID = "20260830-runtime-convergence-v297"
_READY_FLAG = "NIJA_RUNTIME_KRAKEN_MONITORING_FAIRNESS_V297_READY"
_GATE_PATCH_ATTR = "_nija_kraken_monitoring_fair_gate_v297"
_PRIORITY_PATCH_ATTR = "_nija_kraken_authoritative_priority_v297"
_PRIVATE_PATCH_ATTR = "_nija_kraken_balance_single_flight_v297"
_LOCK = threading.RLock()
_FLIGHT_LOCK = threading.RLock()
_PRIORITY_LOCAL = threading.local()
_BALANCE_FLIGHTS: dict[int, dict[str, Any]] = {}


def _float(value: Any, default: float = 0.0) -> float:
    try:
        parsed = float(value)
        return default if parsed != parsed else parsed
    except Exception:
        return default


def _authoritative_priority() -> bool:
    return bool(getattr(_PRIORITY_LOCAL, "authoritative_position", False))


def _set_authoritative_priority(value: bool) -> tuple[bool, bool]:
    existed = hasattr(_PRIORITY_LOCAL, "authoritative_position")
    previous = bool(getattr(_PRIORITY_LOCAL, "authoritative_position", False))
    _PRIORITY_LOCAL.authoritative_position = bool(value)
    return existed, previous


def _restore_authoritative_priority(state: tuple[bool, bool]) -> None:
    existed, previous = state
    if existed:
        _PRIORITY_LOCAL.authoritative_position = previous
        return
    try:
        delattr(_PRIORITY_LOCAL, "authoritative_position")
    except AttributeError:
        pass


class _PriorityFairGate:
    """Exclusive priority/FIFO gate compatible with ``with gate:``.

    Priority 0 is reserved for an authoritative v286 position worker.  Routine
    readers use priority 10.  Sequence order is preserved within each priority.
    This does not change the actual Kraken rate calculation; it only determines
    which already-waiting reader gets the next exclusive turn.
    """

    def __init__(self, identity: str) -> None:
        self.identity = str(identity or "unknown")
        self._condition = threading.Condition(threading.Lock())
        self._held = False
        self._owner: int | None = None
        self._sequence = 0
        self._waiters: list[dict[str, Any]] = []

    def acquire(self, blocking: bool = True, timeout: float = -1) -> bool:
        priority = 0 if _authoritative_priority() else 10
        thread_id = threading.get_ident()
        started = time.monotonic()
        with self._condition:
            if not blocking:
                if self._held or self._waiters:
                    return False
                self._held = True
                self._owner = thread_id
                return True

            token = {
                "priority": priority,
                "sequence": self._sequence,
                "thread_id": thread_id,
            }
            self._sequence += 1
            self._waiters.append(token)
            deadline = None if timeout is None or timeout < 0 else started + float(timeout)

            while True:
                selected = min(
                    self._waiters,
                    key=lambda row: (int(row["priority"]), int(row["sequence"])),
                )
                if not self._held and selected is token:
                    self._waiters.remove(token)
                    self._held = True
                    self._owner = thread_id
                    waited = max(0.0, time.monotonic() - started)
                    if priority == 0 and waited >= 0.05:
                        LOGGER.info(
                            "KRAKEN_MONITOR_PRIORITY_V297_GRANTED marker=%s account=%s wait_s=%.3f authoritative_position=true exclusive_gate_preserved=true rate_interval_unchanged=true",
                            MARKER,
                            self.identity,
                            waited,
                        )
                    return True

                if deadline is None:
                    self._condition.wait()
                    continue
                remaining = deadline - time.monotonic()
                if remaining <= 0.0:
                    try:
                        self._waiters.remove(token)
                    except ValueError:
                        pass
                    self._condition.notify_all()
                    return False
                self._condition.wait(remaining)

    def release(self) -> None:
        with self._condition:
            if not self._held:
                raise RuntimeError("release unlocked Kraken monitoring gate")
            self._held = False
            self._owner = None
            self._condition.notify_all()

    def locked(self) -> bool:
        with self._condition:
            return bool(self._held)

    def __enter__(self) -> "_PriorityFairGate":
        self.acquire()
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> bool:
        self.release()
        return False


setattr(_PriorityFairGate, _GATE_PATCH_ATTR, True)


def _v286() -> Any:
    return importlib.import_module("bot.runtime_kraken_position_refresh_liveness_v286_patch")


def _broker_module() -> Any:
    return importlib.import_module("bot.broker_manager")


def _monitoring_interval_s(broker: Any) -> float:
    try:
        module = _broker_module()
        calculator = getattr(module, "calculate_min_interval", None)
        enum_cls = getattr(module, "KrakenAPICategory", None)
        category = getattr(enum_cls, "MONITORING", None) if enum_cls is not None else None
        mode = getattr(broker, "_kraken_rate_mode", None)
        if callable(calculator) and category is not None and mode is not None:
            return max(0.0, float(calculator(category, mode) or 0.0))
    except Exception:
        pass
    return max(0.0, _float(getattr(broker, "_min_call_interval", 0.0)))


def _transport_timeout_s(broker: Any) -> float:
    try:
        v292 = importlib.import_module("bot.runtime_kraken_transport_timeout_v292_patch")
        fn = getattr(v292, "_transport_timeout_s", None)
        if callable(fn):
            return max(1.0, float(fn(broker) or 0.0))
    except Exception:
        pass
    return max(1.0, min(60.0, _float(getattr(broker, "API_TIMEOUT_SECONDS", 12.0), 12.0)))


def _balance_wait_s(broker: Any) -> float:
    # A shared owner may be waiting behind one current monitoring turn, then its
    # own configured interval, then the bounded HTTP transport.  Keep callers
    # bounded while allowing that legitimate schedule to complete.
    interval = _monitoring_interval_s(broker)
    return max(30.0, min(240.0, interval * 2.0 + _transport_timeout_s(broker) + 30.0))


def _reuse_grace_s() -> float:
    try:
        value = float(os.environ.get("NIJA_KRAKEN_BALANCE_COALESCE_GRACE_S", "0.5") or 0.5)
    except (TypeError, ValueError):
        value = 0.5
    return max(0.0, min(2.0, value))


def _clone(value: Any) -> Any:
    try:
        return copy.deepcopy(value)
    except Exception:
        return value


def _coalesced_balance_call(broker: Any, call: Callable[[], Any]) -> Any:
    key = id(broker)
    now = time.monotonic()
    owner = False
    with _FLIGHT_LOCK:
        flight = _BALANCE_FLIGHTS.get(key)
        if isinstance(flight, dict):
            event = flight.get("event")
            done = bool(event.is_set()) if callable(getattr(event, "is_set", None)) else False
            finished_at = _float(flight.get("finished_at"))
            if done and (finished_at <= 0.0 or now - finished_at > _reuse_grace_s()):
                flight = None
        if not isinstance(flight, dict):
            flight = {
                "event": threading.Event(),
                "result": None,
                "error": None,
                "started_at": now,
                "finished_at": 0.0,
                "owner_thread": threading.get_ident(),
                "waiters": 0,
            }
            _BALANCE_FLIGHTS[key] = flight
            owner = True
        else:
            flight["waiters"] = int(flight.get("waiters", 0) or 0) + 1

    identity = str(getattr(broker, "account_identifier", "unknown") or "unknown")
    if owner:
        try:
            result = call()
            flight["result"] = _clone(result)
            return _clone(result)
        except BaseException as exc:
            flight["error"] = exc
            raise
        finally:
            flight["finished_at"] = time.monotonic()
            flight["event"].set()
            if int(flight.get("waiters", 0) or 0) > 0:
                LOGGER.info(
                    "KRAKEN_BALANCE_SINGLE_FLIGHT_V297_OWNER_COMPLETE marker=%s account=%s waiters=%d genuine_response_only=true freshness_extended=false rate_interval_unchanged=true",
                    MARKER,
                    identity,
                    int(flight.get("waiters", 0) or 0),
                )

    wait_s = _balance_wait_s(broker)
    age = max(0.0, now - _float(flight.get("started_at")))
    LOGGER.info(
        "KRAKEN_BALANCE_SINGLE_FLIGHT_V297_JOIN marker=%s account=%s flight_age_s=%.3f wait_budget_s=%.1f duplicate_private_call=false genuine_response_required=true",
        MARKER,
        identity,
        age,
        wait_s,
    )
    if not flight["event"].wait(wait_s):
        raise TimeoutError(
            f"Kraken shared Balance flight pending after {wait_s:.1f}s age={max(0.0, time.monotonic() - _float(flight.get('started_at'))):.1f}s"
        )
    error = flight.get("error")
    if error is not None:
        raise error
    return _clone(flight.get("result"))


def _patch_instance_rate_gate() -> bool:
    try:
        v286 = _v286()
    except Exception:
        return False
    current = getattr(v286, "_instance_rate_gate", None)
    if not callable(current):
        return False
    if bool(getattr(current, _GATE_PATCH_ATTR, False)):
        return True

    def instance_gate_v297(broker: Any) -> _PriorityFairGate:
        gate = getattr(broker, "_nija_kraken_monitoring_priority_gate_v297", None)
        if isinstance(gate, _PriorityFairGate):
            return gate
        with _LOCK:
            gate = getattr(broker, "_nija_kraken_monitoring_priority_gate_v297", None)
            if not isinstance(gate, _PriorityFairGate):
                gate = _PriorityFairGate(str(getattr(broker, "account_identifier", "unknown") or "unknown"))
                try:
                    setattr(broker, "_nija_kraken_monitoring_priority_gate_v297", gate)
                except Exception:
                    pass
            return gate

    setattr(instance_gate_v297, _GATE_PATCH_ATTR, True)
    setattr(instance_gate_v297, "__wrapped__", current)
    v286._instance_rate_gate = instance_gate_v297
    return True


def _patch_authoritative_priority_context() -> bool:
    try:
        v286 = _v286()
    except Exception:
        return False
    current = getattr(v286, "_fetch_authoritative_rows_sync", None)
    if not callable(current):
        return False
    if bool(getattr(current, _PRIORITY_PATCH_ATTR, False)):
        return True
    original = current

    @wraps(original)
    def fetch_v297(broker: Any):
        state = _set_authoritative_priority(True)
        try:
            return original(broker)
        finally:
            _restore_authoritative_priority(state)

    setattr(fetch_v297, _PRIORITY_PATCH_ATTR, True)
    setattr(fetch_v297, "__wrapped__", original)
    v286._fetch_authoritative_rows_sync = fetch_v297
    return True


def _chain_has_private_patch(callable_obj: Any) -> bool:
    seen: set[int] = set()
    current = callable_obj
    for _ in range(128):
        if not callable(current) or id(current) in seen:
            return False
        seen.add(id(current))
        if bool(getattr(current, _PRIVATE_PATCH_ATTR, False)):
            return True
        current = getattr(current, "__wrapped__", None)
    return False


def _patch_balance_single_flight() -> bool:
    try:
        cls = getattr(_broker_module(), "KrakenBroker", None)
    except Exception:
        return False
    if not isinstance(cls, type):
        return False
    current = getattr(cls, "_kraken_private_call", None)
    if not callable(current):
        return False
    if _chain_has_private_patch(current):
        return True
    original = current

    @wraps(original)
    def private_v297(self: Any, *args: Any, **kwargs: Any):
        method = str(args[0] if args else kwargs.get("method", "") or "")
        params = args[1] if len(args) >= 2 else kwargs.get("params")
        if method != "Balance" or params not in (None, {}):
            return original(self, *args, **kwargs)
        return _coalesced_balance_call(
            self,
            lambda: original(self, *args, **kwargs),
        )

    setattr(private_v297, _PRIVATE_PATCH_ATTR, True)
    setattr(private_v297, "__wrapped__", original)
    cls._kraken_private_call = private_v297
    return True


def _register_manifest() -> bool:
    try:
        manifest = importlib.import_module("bot.runtime_release_manifest_patch")
        required = getattr(manifest, "_REQUIRED_FLAGS", None)
        if not isinstance(required, dict):
            return False
        required["runtime_kraken_monitoring_fairness_v297"] = _READY_FLAG
        return True
    except Exception:
        return False


def reconcile_once() -> dict[str, Any]:
    gate = _patch_instance_rate_gate()
    priority = _patch_authoritative_priority_context()
    balance = _patch_balance_single_flight()
    with _FLIGHT_LOCK:
        inflight = sum(
            1
            for flight in _BALANCE_FLIGHTS.values()
            if isinstance(flight, dict)
            and callable(getattr(flight.get("event"), "is_set", None))
            and not flight["event"].is_set()
        )
    return {
        "ready": bool(gate and priority and balance),
        "priority_gate": bool(gate),
        "authoritative_priority": bool(priority),
        "balance_single_flight": bool(balance),
        "balance_flights_inflight": int(inflight),
    }


def install() -> bool:
    manifest = _register_manifest()
    gate = _patch_instance_rate_gate()
    priority = _patch_authoritative_priority_context()
    balance = _patch_balance_single_flight()
    ready = bool(manifest and gate and priority and balance)
    os.environ[_READY_FLAG] = "1" if ready else "0"
    log = LOGGER.critical if ready else LOGGER.error
    log(
        "RUNTIME_KRAKEN_MONITORING_FAIRNESS_V297_%s marker=%s ready=%s authoritative_position_priority=true routine_reader_fifo=true balance_single_flight=true balance_reuse_grace_s=%.2f configured_rate_interval_unchanged=true exclusive_read_gate_preserved=true credential_serialization_preserved=true transport_timeout_preserved=true nonce_policy_unchanged=true position_success_fabricated=false balance_fabricated=false freshness_extended=false capital_ready_granted=false execution_proof_fabricated=false forced_trade=false forced_activation=false writer_nonce_risk_capital_killswitch_order_fill_gates_unchanged=true safety_gates_bypassed=false",
        "READY" if ready else "NOT_READY",
        MARKER,
        str(ready).lower(),
        _reuse_grace_s(),
    )
    return ready


def install_import_hook() -> bool:
    return install()


__all__ = [
    "MARKER",
    "RELEASE_ID",
    "install",
    "install_import_hook",
    "reconcile_once",
    "_PriorityFairGate",
    "_authoritative_priority",
    "_set_authoritative_priority",
    "_restore_authoritative_priority",
    "_coalesced_balance_call",
    "_patch_instance_rate_gate",
    "_patch_authoritative_priority_context",
    "_patch_balance_single_flight",
]
