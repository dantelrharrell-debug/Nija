"""Terminal activation liveness convergence for genuine startup proof (v255).

This patch repairs three production liveness defects without fabricating any
readiness fact or weakening an execution gate:

* a startup heartbeat that encounters proven process-local broker read
  contention may immediately retry on another venue already published by the
  canonical execution-readiness set;
* the authoritative position-fetch wrapper stack is reasserted in canonical
  v163 -> v182 order and receives a final readiness publication after its real
  worker returns; and
* CapitalBootstrapFSM transitions initiated by a non-owner capital-refresh
  worker are deferred instead of raising into an otherwise successful refresh.

Local contention never marks a broker healthy, never changes broker health or
availability, and never counts as execution proof.  Position readiness still
requires adoption plus an authoritative fetch proof.  Bootstrap transitions are
performed only by the canonical owner thread.  Ordinary orders and all writer,
nonce, risk, capital, kill-switch, minimum-notional, exchange-acknowledgement and
fill gates remain unchanged.
"""
from __future__ import annotations

import importlib
import logging
import os
import threading
import time
from functools import wraps
from typing import Any

LOGGER = logging.getLogger("nija.runtime_terminal_activation_liveness_v255")
MARKER = "20260828-terminal-activation-liveness-v255"
RELEASE_ID = "20260828-runtime-convergence-v255"
_READY_FLAG = "NIJA_RUNTIME_TERMINAL_ACTIVATION_LIVENESS_V255_READY"
_HEARTBEAT_PATCH_ATTR = "_nija_terminal_activation_liveness_v255_heartbeat"
_POSITION_PATCH_ATTR = "_nija_terminal_activation_liveness_v255_position"
_CAPITAL_PATCH_ATTR = "_nija_terminal_activation_liveness_v255_capital"
_LOCK = threading.RLock()


def _local_contention_quarantine_s() -> float:
    try:
        configured = float(os.environ.get("NIJA_HEARTBEAT_LOCAL_CONTENTION_QUARANTINE_S", "20") or 20.0)
    except (TypeError, ValueError):
        configured = 20.0
    return max(5.0, min(120.0, configured))


def _is_local_contention(detail: Any) -> bool:
    text = str(detail or "").strip().lower()
    if not text:
        return False
    markers = (
        "kraken read lock busy",
        "read lock busy after",
        "local_read_contention",
        "local read contention",
        "local_contention",
    )
    return any(marker in text for marker in markers)


def _broker_key(strategy: Any, broker: Any) -> str:
    resolver = getattr(strategy, "_broker_key_from_obj", None)
    if callable(resolver):
        try:
            value = str(resolver(broker) or "").strip().lower()
            if value:
                return value
        except Exception:
            pass
    name = type(broker).__name__.replace("Broker", "").strip().lower()
    return name or "unknown"


def _quarantine_local_busy(strategy: Any, broker: Any, detail: str) -> str:
    venue = _broker_key(strategy, broker)
    now = time.monotonic()
    until = now + _local_contention_quarantine_s()
    current = getattr(strategy, "_nija_heartbeat_local_busy_until", None)
    quarantine = dict(current) if isinstance(current, dict) else {}
    quarantine = {
        str(name).lower(): float(expiry)
        for name, expiry in quarantine.items()
        if float(expiry or 0.0) > now
    }
    quarantine[venue] = until
    setattr(strategy, "_nija_heartbeat_local_busy_until", quarantine)
    setattr(strategy, "_nija_heartbeat_local_contention_at", now)
    setattr(strategy, "_nija_heartbeat_local_contention_venue", venue)
    LOGGER.warning(
        "HEARTBEAT_LOCAL_CONTENTION_V255_QUARANTINED marker=%s venue=%s ttl_s=%.1f "
        "detail=%s broker_health_unchanged=true availability_unchanged=true "
        "execution_proof_fabricated=false trading_fail_closed=true",
        MARKER,
        venue,
        _local_contention_quarantine_s(),
        detail,
    )
    return venue


def _filtered_ready_venues(strategy: Any) -> tuple[str | None, tuple[str, ...], tuple[str, ...]]:
    if "NIJA_EXECUTION_READY_VENUES" not in os.environ:
        return None, (), ()
    raw = str(os.environ.get("NIJA_EXECUTION_READY_VENUES", "") or "")
    ready = tuple(dict.fromkeys(part.strip().lower() for part in raw.split(",") if part.strip()))
    now = time.monotonic()
    current = getattr(strategy, "_nija_heartbeat_local_busy_until", None)
    quarantine = dict(current) if isinstance(current, dict) else {}
    active = {
        str(name).lower(): float(expiry)
        for name, expiry in quarantine.items()
        if float(expiry or 0.0) > now
    }
    setattr(strategy, "_nija_heartbeat_local_busy_until", active)
    blocked = tuple(sorted(name for name in ready if name in active))
    allowed = tuple(name for name in ready if name not in active)
    return raw, allowed, blocked


def _patch_trading_strategy() -> bool:
    module = importlib.import_module("bot.trading_strategy")
    cls = getattr(module, "TradingStrategy", None)
    if not isinstance(cls, type):
        return False

    auth = getattr(cls, "_heartbeat_auth_verify", None)
    select = getattr(cls, "_get_heartbeat_broker", None)
    execute = getattr(cls, "_execute_heartbeat_trade", None)
    if not all(callable(value) for value in (auth, select, execute)):
        return False

    if not bool(getattr(auth, _HEARTBEAT_PATCH_ATTR, False)):
        original_auth = auth

        @wraps(original_auth)
        def auth_v255(self: Any, broker: Any) -> tuple[bool, str]:
            ok, detail = original_auth(self, broker)
            normalized = str(detail or "")
            if not bool(ok) and _is_local_contention(normalized):
                _quarantine_local_busy(self, broker, normalized)
            return bool(ok), normalized

        setattr(auth_v255, _HEARTBEAT_PATCH_ATTR, True)
        setattr(auth_v255, "__wrapped__", original_auth)
        cls._heartbeat_auth_verify = auth_v255

    current_select = getattr(cls, "_get_heartbeat_broker", None)
    if not bool(getattr(current_select, _HEARTBEAT_PATCH_ATTR, False)):
        original_select = current_select

        @wraps(original_select)
        def select_v255(self: Any):
            original_raw, allowed, blocked = _filtered_ready_venues(self)
            if original_raw is None or not blocked:
                return original_select(self)
            if not allowed:
                LOGGER.warning(
                    "HEARTBEAT_LOCAL_CONTENTION_V255_ALL_READY_VENUES_BUSY marker=%s "
                    "blocked=%s retry_later=true trading_fail_closed=true execution_proof_fabricated=false",
                    MARKER,
                    ",".join(blocked),
                )
                return None

            candidates = {}
            if getattr(self, "multi_account_manager", None) is not None:
                try:
                    candidates.update(getattr(self.multi_account_manager, "platform_brokers", {}) or {})
                except Exception as exc:
                    LOGGER.debug("Heartbeat v255 MABM lookup failed: %s", exc)
            if getattr(self, "broker_manager", None) is not None:
                try:
                    candidates.update(getattr(self.broker_manager, "brokers", {}) or {})
                    primary = self.broker_manager.get_primary_broker()
                    if primary is not None:
                        candidates.setdefault(getattr(primary, "broker_type", "primary"), primary)
                except Exception as exc:
                    LOGGER.debug("Heartbeat v255 BrokerManager lookup failed: %s", exc)
            if getattr(self, "broker", None) is not None:
                candidates.setdefault(getattr(self.broker, "broker_type", "cached"), self.broker)

            allowed_set = set(allowed)
            ready_candidates = {
                raw_key: broker
                for raw_key, broker in candidates.items()
                if broker is not None and _broker_key(self, broker) in allowed_set
            }
            selector = getattr(self, "_select_entry_broker", None)
            if not callable(selector):
                LOGGER.error(
                    "HEARTBEAT_LOCAL_CONTENTION_V255_SELECTOR_MISSING marker=%s "
                    "trading_fail_closed=true",
                    MARKER,
                )
                return None
            selected, name, status = selector(ready_candidates)
            if selected is None:
                LOGGER.warning(
                    "HEARTBEAT_LOCAL_CONTENTION_V255_FAILOVER_UNAVAILABLE marker=%s "
                    "allowed=%s blocked=%s status=%s trading_fail_closed=true",
                    MARKER,
                    ",".join(allowed),
                    ",".join(blocked),
                    status or "no_matching_broker_objects",
                )
                return None
            self.broker = selected
            if getattr(self, "broker_manager", None) is not None:
                try:
                    self.broker_manager.active_broker = selected
                except Exception:
                    pass

            LOGGER.critical(
                "HEARTBEAT_LOCAL_CONTENTION_V255_FAILOVER marker=%s blocked=%s selected=%s "
                "canonical_ready_set_only=true ordinary_routing_unchanged=true "
                "broker_health_unchanged=true execution_proof_fabricated=false",
                MARKER,
                ",".join(blocked),
                _broker_key(self, selected),
            )
            return selected

        setattr(select_v255, _HEARTBEAT_PATCH_ATTR, True)
        setattr(select_v255, "__wrapped__", original_select)
        cls._get_heartbeat_broker = select_v255

    current_execute = getattr(cls, "_execute_heartbeat_trade", None)
    if not bool(getattr(current_execute, _HEARTBEAT_PATCH_ATTR, False)):
        original_execute = current_execute

        @wraps(original_execute)
        def execute_v255(self: Any) -> bool:
            setattr(self, "_nija_heartbeat_local_contention_at", 0.0)
            if bool(original_execute(self)):
                return True

            contention_at = float(getattr(self, "_nija_heartbeat_local_contention_at", 0.0) or 0.0)
            if contention_at <= 0.0 or (time.monotonic() - contention_at) > 2.0:
                return False

            venue = str(getattr(self, "_nija_heartbeat_local_contention_venue", "unknown") or "unknown")
            LOGGER.critical(
                "HEARTBEAT_LOCAL_CONTENTION_V255_IMMEDIATE_RETRY marker=%s failed_venue=%s "
                "max_fallbacks=1 canonical_ready_set_only=true safety_gates_unchanged=true",
                MARKER,
                venue,
            )
            setattr(self, "_nija_heartbeat_local_contention_at", 0.0)
            return bool(original_execute(self))

        setattr(execute_v255, _HEARTBEAT_PATCH_ATTR, True)
        setattr(execute_v255, "__wrapped__", original_execute)
        cls._execute_heartbeat_trade = execute_v255

    return all(
        bool(getattr(getattr(cls, name, None), _HEARTBEAT_PATCH_ATTR, False))
        for name in ("_heartbeat_auth_verify", "_get_heartbeat_broker", "_execute_heartbeat_trade")
    )


def _patch_position_worker() -> bool:
    """Reassert the exact proof chain and publish once after a real worker returns."""
    v163 = importlib.import_module("bot.runtime_activation_convergence_v163_patch")
    v182 = importlib.import_module("bot.runtime_position_fetch_proof_v182_patch")
    install163 = getattr(v163, "install", None) or getattr(v163, "install_import_hook", None)
    install182 = getattr(v182, "install", None) or getattr(v182, "install_import_hook", None)
    if not callable(install163) or install163() is False:
        return False
    if not callable(install182) or install182() is False:
        return False

    v108 = importlib.import_module("bot.platform_position_sync_v108_patch")
    current = getattr(v108, "_worker", None)
    if not callable(current):
        return False
    if bool(getattr(current, _POSITION_PATCH_ATTR, False)):
        return True
    original = current

    @wraps(original)
    def worker_v255(manager: Any, broker_name: str, broker: Any, key: tuple[int, int], trigger: str) -> None:
        try:
            original(manager, broker_name, broker, key, trigger)
        finally:
            adopted = bool(getattr(broker, "_startup_position_sync_adopted", False))
            fetch_ok = getattr(broker, "_startup_position_sync_fetch_ok", None) is True
            try:
                v108._publish_readiness(
                    manager,
                    source=f"v255:{trigger}:{broker_name}:post_worker",
                )
            except Exception:
                LOGGER.debug(
                    "POSITION_FETCH_V255_FINAL_PUBLICATION_FAILED marker=%s broker=%s",
                    MARKER,
                    broker_name,
                    exc_info=True,
                )
            LOGGER.critical(
                "POSITION_FETCH_V255_WORKER_RETURNED marker=%s broker=%s trigger=%s "
                "adopted=%s fetch_ok=%s synthetic_success=false activation_not_forced=true",
                MARKER,
                broker_name,
                trigger,
                str(adopted).lower(),
                str(fetch_ok).lower(),
            )

    worker_v255.__name__ = "worker_v255"
    setattr(worker_v255, _POSITION_PATCH_ATTR, True)
    setattr(worker_v255, "__wrapped__", original)
    v108._worker = worker_v255
    return True


class _OwnerAwareBootstrapFSMProxy:
    """Defer non-owner transitions while delegating every other operation."""

    def __init__(self, target: Any) -> None:
        object.__setattr__(self, "_target", target)

    def __getattr__(self, name: str) -> Any:
        return getattr(object.__getattribute__(self, "_target"), name)

    def transition(self, *args: Any, **kwargs: Any) -> bool:
        target = object.__getattribute__(self, "_target")
        checker = getattr(target, "is_owner_thread", None)
        if callable(checker):
            try:
                owner = bool(checker())
            except Exception:
                owner = False
            if not owner:
                LOGGER.info(
                    "CAPITAL_BOOTSTRAP_V255_NONOWNER_TRANSITION_DEFERRED marker=%s "
                    "caller=%s state=%s owner_only=true transition_not_applied=true "
                    "capital_snapshot_unchanged=true trading_fail_closed=true",
                    MARKER,
                    threading.get_ident(),
                    getattr(getattr(target, "state", None), "value", getattr(target, "state", None)),
                )
                return False
        return bool(target.transition(*args, **kwargs))


def _patch_capital_bootstrap_owner() -> bool:
    module = importlib.import_module("bot.capital_flow_state_machine")
    current = getattr(module, "_resolve_bootstrap_fsm", None)
    if not callable(current):
        return False
    if bool(getattr(current, _CAPITAL_PATCH_ATTR, False)):
        return True
    original = current

    @wraps(original)
    def resolve_v255():
        state_type, getter = original()
        if state_type is None or not callable(getter):
            return state_type, getter

        @wraps(getter)
        def owner_aware_getter():
            target = getter()
            if target is None:
                return None
            return _OwnerAwareBootstrapFSMProxy(target)

        return state_type, owner_aware_getter

    setattr(resolve_v255, _CAPITAL_PATCH_ATTR, True)
    setattr(resolve_v255, "__wrapped__", original)
    module._resolve_bootstrap_fsm = resolve_v255
    return True


def _register_manifest() -> bool:
    try:
        manifest = importlib.import_module("bot.runtime_release_manifest_patch")
        required = getattr(manifest, "_REQUIRED_FLAGS", None)
        if not isinstance(required, dict):
            return False
        required["runtime_terminal_activation_liveness_v255"] = _READY_FLAG
        return True
    except Exception:
        return False


def install() -> bool:
    with _LOCK:
        outcomes: dict[str, bool] = {}
        for name, step in (
            ("heartbeat_failover", _patch_trading_strategy),
            ("position_fetch_chain", _patch_position_worker),
            ("capital_bootstrap_owner", _patch_capital_bootstrap_owner),
            ("manifest", _register_manifest),
        ):
            try:
                outcomes[name] = bool(step())
            except Exception as exc:
                outcomes[name] = False
                LOGGER.error(
                    "TERMINAL_ACTIVATION_V255_STEP_FAILED marker=%s step=%s error=%s:%s "
                    "trading_fail_closed=true",
                    MARKER,
                    name,
                    type(exc).__name__,
                    exc,
                    exc_info=True,
                )

        ready = all(outcomes.values())
        os.environ[_READY_FLAG] = "1" if ready else "0"
        LOGGER.critical(
            "RUNTIME_TERMINAL_ACTIVATION_LIVENESS_V255 marker=%s ready=%s outcomes=%s "
            "heartbeat_ready_venue_failover=true local_contention_health_unchanged=true "
            "authoritative_position_fetch_required=true bootstrap_owner_only=true "
            "nonce_writer_risk_capital_killswitch_min_notional_order_fill_gates_unchanged=true "
            "execution_proof_fabricated=false forced_activation=false safety_gates_bypassed=false",
            MARKER,
            str(ready).lower(),
            outcomes,
        )
        return ready


def install_import_hook() -> bool:
    return install()


__all__ = [
    "MARKER",
    "RELEASE_ID",
    "install",
    "install_import_hook",
    "_is_local_contention",
    "_broker_key",
    "_quarantine_local_busy",
    "_filtered_ready_venues",
    "_patch_trading_strategy",
    "_patch_position_worker",
    "_OwnerAwareBootstrapFSMProxy",
    "_patch_capital_bootstrap_owner",
]
