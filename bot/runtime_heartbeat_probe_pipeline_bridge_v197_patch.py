"""Bridge whitelisted heartbeat startup probes through ExecutionPipeline v197.

Production on 2026-08-23 exposed a real startup-verification deadlock after v169
correctly separated writer liveness from genuine ORDER/FILL execution proof.
TradingStrategy already scopes verification orders with
``startup_execution_probe_scope`` and the broker layer already honors
``can_execute_startup_probe()``.  ExecutionPipeline, however, rejected the same
probe earlier at two ordinary-runtime gates: its runtime-authority snapshot and
``assert_execution_dispatch_permitted()``.  As a result the heartbeat order
could not reach the broker to create the proof ordinary ``can_execute`` awaited.

v197 bridges only the existing whitelisted HEARTBEAT_TRADE and
HEARTBEAT_TRADE_CLOSE contexts.  Every bridge decision re-runs
``can_execute_startup_probe()``, which verifies startup write authority.  Normal
orders still require ordinary runtime authority.  Writer, nonce, kill-switch,
risk, broker-health, throttling, sizing, min-notional, and exchange order gates
remain unchanged.

v200 aligned the scheduler when ``HEARTBEAT_REQUIRED_FIRST_ACTIVATION`` was
explicitly enabled.  Production then exposed the remaining contract mismatch:
canonical ``execution_authority_context.can_execute()`` always requires a fresh,
stage-sufficient heartbeat execution marker in LIVE mode, while both legacy
heartbeat scheduler flags can legitimately be unset.  In that configuration the
mandatory proof could never be created and post-core convergence exhausted its
budget while remaining fail-closed.

v201 aligns scheduling with the canonical LIVE execution contract itself.  When
the centralized runtime-mode resolver says this process is genuinely live,
v201 arms the existing heartbeat verification scheduler before TradingStrategy
construction.  Dry-run, paper, monitor, conflicting, or unresolved modes never
cause a live verification order to be scheduled.  v201 does not grant execution
authority, mark a heartbeat as successful, fabricate ORDER/FILL proof, or bypass
writer, nonce, kill-switch, risk, broker-health, sizing, min-notional, exchange
order, fill-verification, reconciliation, or capital gates.

v208 bounds only heartbeat-thread market discovery.  Production on 2026-08-24
showed an existing HeartbeatTrade thread remain alive for minutes after Coinbase
AUTH_VERIFY while never emitting ``market_discovery_count`` or reaching the BUY.
``TradingStrategy`` explicitly defines market discovery as best-effort, but the
call itself was synchronous and therefore could hang before the existing
exception fallback ran.  v208 wraps broker market-discovery methods only when
called by the HeartbeatTrade thread, uses a bounded daemon worker, and returns an
empty market list on timeout so the existing configured-symbol fallback can
continue.  Normal market discovery is untouched, only one timed-out discovery
worker per broker/method may remain in flight, and no execution proof/readiness/
authority state is manufactured.
"""
from __future__ import annotations

import builtins
import importlib
import logging
import os
import queue
import sys
import threading
from functools import wraps
from types import ModuleType, SimpleNamespace
from typing import Any, Callable

LOGGER = logging.getLogger("nija.runtime_heartbeat_probe_pipeline_bridge_v197")
MARKER = "20260823-heartbeat-probe-pipeline-bridge-v197"
V200_MARKER = "20260823-heartbeat-required-scheduler-v200"
V201_MARKER = "20260823-live-execution-heartbeat-scheduler-v201"
V208_MARKER = "20260824-heartbeat-market-discovery-bound-v208"
_READY_FLAG = "NIJA_RUNTIME_HEARTBEAT_PROBE_PIPELINE_BRIDGE_V197_READY"
_V200_READY_FLAG = "NIJA_HEARTBEAT_REQUIRED_SCHEDULER_V200_READY"
_V201_READY_FLAG = "NIJA_LIVE_EXECUTION_HEARTBEAT_SCHEDULER_V201_READY"
_V208_READY_FLAG = "NIJA_HEARTBEAT_MARKET_DISCOVERY_BOUND_V208_READY"
_PATCH_ATTR = "_nija_runtime_heartbeat_probe_pipeline_bridge_v197"
_SNAPSHOT_PATCH_ATTR = "_nija_runtime_heartbeat_probe_snapshot_bridge_v197"
_MARKET_DISCOVERY_PATCH_ATTR = "_nija_heartbeat_market_discovery_bound_v208"
_IMPORT_HOOK_ATTR = "_NIJA_RUNTIME_HEARTBEAT_PROBE_PIPELINE_BRIDGE_V197_IMPORT_HOOK"
_LOCK = threading.RLock()
_MARKET_DISCOVERY_LOCK = threading.RLock()
_MARKET_DISCOVERY_FLIGHTS: dict[tuple[int, str], threading.Thread] = {}
_TRUE = {"1", "true", "yes", "enabled", "on", "y"}

_AUTHORITY_MODULE_NAMES = (
    "bot.execution_authority_context",
    "execution_authority_context",
)
_PIPELINE_MODULE_NAMES = (
    "bot.execution_pipeline",
    "execution_pipeline",
)
_BROKER_MODULE_NAMES = (
    "bot.broker_manager",
    "broker_manager",
)
_TARGET_IMPORT_SUFFIXES = (
    "execution_authority_context",
    "execution_pipeline",
    "broker_manager",
)


def _env_truthy(name: str) -> bool:
    return str(os.environ.get(name, "") or "").strip().lower() in _TRUE


def _resolved_runtime_mode() -> tuple[bool, str, str]:
    """Return (resolved, mode, source) from NIJA's centralized mode resolver."""
    try:
        runtime_mode = importlib.import_module("bot.runtime_mode")
        resolver = getattr(runtime_mode, "resolve_runtime_mode_safe", None)
        if not callable(resolver):
            return False, "unresolved", "resolver_unavailable"
        resolved = resolver(LOGGER)
        if resolved is None:
            return False, "unresolved", "resolver_returned_none"
        mode = str(getattr(resolved, "mode", "") or "").strip().lower()
        source = str(getattr(resolved, "source", "") or "").strip() or "unknown"
        conflicts = tuple(getattr(resolved, "conflicts", ()) or ())
        if conflicts:
            return False, mode or "unresolved", "conflict:" + ",".join(str(item) for item in conflicts)
        if mode not in {"live", "dry_run", "paper", "monitor"}:
            return False, mode or "unresolved", "invalid_mode"
        return True, mode, source
    except Exception as exc:
        return False, "unresolved", f"resolver_error:{type(exc).__name__}:{exc}"


def _align_required_heartbeat_scheduler_policy() -> bool:
    """Ensure canonical LIVE execution proof has an existing scheduler path.

    ``execution_authority_context.can_execute()`` treats heartbeat freshness and
    stage sufficiency as mandatory LIVE pre-trade gates.  Therefore a LIVE
    runtime must have a way to create genuine ORDER/FILL proof even when legacy
    opt-in scheduler flags are unset.  This function only arms the already
    existing TradingStrategy heartbeat verifier; it does not execute an order by
    itself and it never runs the scheduler in dry-run, paper, or monitor mode.
    """
    required_first = _env_truthy("HEARTBEAT_REQUIRED_FIRST_ACTIVATION")
    heartbeat_trade_before = _env_truthy("HEARTBEAT_TRADE")
    mode_resolved, mode, mode_source = _resolved_runtime_mode()
    live_mode = bool(mode_resolved and mode == "live")
    aligned_v200 = False
    aligned_v201 = False

    # Preserve v200 behavior for explicitly configured first-activation proof.
    if required_first and not heartbeat_trade_before:
        os.environ["HEARTBEAT_TRADE"] = "true"
        aligned_v200 = True

    heartbeat_trade = _env_truthy("HEARTBEAT_TRADE")

    # v201: canonical can_execute always requires a genuine stage-sufficient
    # heartbeat marker in LIVE mode.  Arm the existing verifier so that proof can
    # actually be produced.  Non-live and unresolved/conflicting modes do not
    # schedule a live verification order.
    if live_mode and not heartbeat_trade:
        os.environ["HEARTBEAT_TRADE"] = "true"
        heartbeat_trade = True
        aligned_v201 = True

    os.environ[_V200_READY_FLAG] = "1"
    os.environ[_V201_READY_FLAG] = "1" if mode_resolved else "0"

    LOGGER.critical(
        "HEARTBEAT_REQUIRED_SCHEDULER_V200_READY marker=%s "
        "required_first=%s heartbeat_trade=%s aligned=%s "
        "existing_probe_scheduler_only=true execution_authority_granted=false "
        "writer_nonce_risk_killswitch_order_fill_gates_unchanged=true "
        "forced_activation=false safety_gates_bypassed=false",
        V200_MARKER,
        str(required_first).lower(),
        str(heartbeat_trade).lower(),
        str(aligned_v200).lower(),
    )
    LOGGER.critical(
        "LIVE_EXECUTION_HEARTBEAT_SCHEDULER_V201_READY marker=%s "
        "mode_resolved=%s mode=%s mode_source=%s live_mode=%s "
        "heartbeat_trade_before=%s heartbeat_trade_after=%s aligned=%s "
        "canonical_can_execute_heartbeat_gate_preserved=true "
        "dry_run_paper_monitor_probe_suppressed=true existing_probe_scheduler_only=true "
        "execution_authority_granted=false proof_fabricated=false "
        "writer_nonce_risk_killswitch_reconciliation_capital_order_fill_gates_unchanged=true "
        "forced_activation=false safety_gates_bypassed=false",
        V201_MARKER,
        str(mode_resolved).lower(),
        mode,
        mode_source,
        str(live_mode).lower(),
        str(heartbeat_trade_before).lower(),
        str(heartbeat_trade).lower(),
        str(aligned_v201).lower(),
    )
    return bool(mode_resolved)


def _heartbeat_market_discovery_timeout_s() -> float:
    try:
        value = float(os.environ.get("NIJA_HEARTBEAT_MARKET_DISCOVERY_TIMEOUT_S", "5") or 5.0)
    except (TypeError, ValueError):
        value = 5.0
    return max(0.5, min(30.0, value))


def _wrap_heartbeat_market_discovery_method(
    current: Callable[..., Any],
    *,
    broker_class_name: str,
    method_name: str,
) -> Callable[..., Any]:
    """Bound market discovery only for the dedicated HeartbeatTrade thread."""
    if bool(getattr(current, _MARKET_DISCOVERY_PATCH_ATTR, False)):
        return current

    @wraps(current)
    def bounded_market_discovery(self: Any, *args: Any, **kwargs: Any) -> Any:
        if not threading.current_thread().name.startswith("HeartbeatTrade"):
            return current(self, *args, **kwargs)

        key = (id(self), method_name)
        with _MARKET_DISCOVERY_LOCK:
            existing = _MARKET_DISCOVERY_FLIGHTS.get(key)
            if existing is not None and existing.is_alive():
                LOGGER.warning(
                    "HEARTBEAT_MARKET_DISCOVERY_V208_INFLIGHT marker=%s broker=%s method=%s "
                    "action=fallback_empty_markets duplicate_worker=false normal_market_discovery_unchanged=true",
                    V208_MARKER,
                    broker_class_name,
                    method_name,
                )
                return []

            result_queue: "queue.Queue[tuple[str, Any]]" = queue.Queue(maxsize=1)

            def _runner() -> None:
                try:
                    result_queue.put(("result", current(self, *args, **kwargs)))
                except BaseException as exc:
                    result_queue.put(("error", exc))

            worker = threading.Thread(
                target=_runner,
                name=f"HeartbeatMarketDiscovery-v208-{broker_class_name}-{method_name}",
                daemon=True,
            )
            _MARKET_DISCOVERY_FLIGHTS[key] = worker
            worker.start()

        timeout_s = _heartbeat_market_discovery_timeout_s()
        try:
            kind, payload = result_queue.get(timeout=timeout_s)
        except queue.Empty:
            LOGGER.warning(
                "HEARTBEAT_MARKET_DISCOVERY_V208_TIMEOUT marker=%s broker=%s method=%s timeout_s=%.2f "
                "action=fallback_empty_markets worker_daemon=true duplicate_worker=false "
                "configured_symbol_fallback_preserved=true normal_market_discovery_unchanged=true "
                "execution_authority_granted=false proof_fabricated=false safety_gates_bypassed=false",
                V208_MARKER,
                broker_class_name,
                method_name,
                timeout_s,
            )
            return []
        if kind == "error":
            raise payload
        return payload

    setattr(bounded_market_discovery, _MARKET_DISCOVERY_PATCH_ATTR, True)
    setattr(bounded_market_discovery, "__wrapped__", current)
    return bounded_market_discovery


def _patch_heartbeat_market_discovery() -> bool:
    """Patch broker discovery before the live heartbeat strategy is constructed."""
    module = None
    for name in _BROKER_MODULE_NAMES:
        candidate = sys.modules.get(name)
        if isinstance(candidate, ModuleType):
            module = candidate
            break
    if module is None:
        try:
            module = importlib.import_module("bot.broker_manager")
        except Exception as exc:
            os.environ[_V208_READY_FLAG] = "0"
            LOGGER.critical(
                "HEARTBEAT_MARKET_DISCOVERY_V208_FAILED marker=%s reason=broker_module_import_failed "
                "error=%s:%s trading_fail_closed=true",
                V208_MARKER,
                type(exc).__name__,
                exc,
            )
            return False

    patched = 0
    for class_name in ("CoinbaseBroker", "KrakenBroker", "OKXBroker", "AlpacaBroker"):
        broker_cls = getattr(module, class_name, None)
        if not isinstance(broker_cls, type):
            continue
        for method_name in ("get_available_markets", "get_all_products"):
            current = getattr(broker_cls, method_name, None)
            if not callable(current):
                continue
            if not bool(getattr(current, _MARKET_DISCOVERY_PATCH_ATTR, False)):
                setattr(
                    broker_cls,
                    method_name,
                    _wrap_heartbeat_market_discovery_method(
                        current,
                        broker_class_name=class_name,
                        method_name=method_name,
                    ),
                )
            installed = getattr(broker_cls, method_name, None)
            if callable(installed) and bool(getattr(installed, _MARKET_DISCOVERY_PATCH_ATTR, False)):
                patched += 1

    ready = patched > 0
    os.environ[_V208_READY_FLAG] = "1" if ready else "0"
    if not ready:
        LOGGER.critical(
            "HEARTBEAT_MARKET_DISCOVERY_V208_FAILED marker=%s reason=no_market_discovery_surfaces "
            "trading_fail_closed=true",
            V208_MARKER,
        )
        return False

    LOGGER.critical(
        "HEARTBEAT_MARKET_DISCOVERY_V208_READY marker=%s ready=true patched_surfaces=%s timeout_s=%.2f "
        "heartbeat_thread_only=true configured_symbol_fallback_preserved=true "
        "normal_market_discovery_unchanged=true single_inflight_per_broker_method=true "
        "execution_authority_granted=false proof_fabricated=false forced_trade=false safety_gates_bypassed=false",
        V208_MARKER,
        patched,
        _heartbeat_market_discovery_timeout_s(),
    )
    return True


def _canonical_authority_module() -> ModuleType:
    for name in _AUTHORITY_MODULE_NAMES:
        module = sys.modules.get(name)
        if isinstance(module, ModuleType):
            return module
    module = importlib.import_module("bot.execution_authority_context")
    if not isinstance(module, ModuleType):
        raise RuntimeError("canonical execution authority module unavailable")
    return module


def _startup_probe_allowed(authority: ModuleType) -> tuple[bool, str]:
    checker = getattr(authority, "can_execute_startup_probe", None)
    if not callable(checker):
        return False, "startup_probe_checker_unavailable"
    try:
        allowed, reason = checker()
    except Exception as exc:
        return False, f"startup_probe_authority_error:{type(exc).__name__}:{exc}"
    return bool(allowed), str(reason or "")


def _patch_authority_dispatch(authority: ModuleType) -> Callable[[], None] | None:
    """Allow a verified whitelisted startup probe through the dispatch assertion."""
    current = getattr(authority, "assert_execution_dispatch_permitted", None)
    if not callable(current):
        return None
    if bool(getattr(current, _PATCH_ATTR, False)):
        return current

    execution_blocked = getattr(authority, "ExecutionBlocked", RuntimeError)
    if not isinstance(execution_blocked, type):
        return None

    @wraps(current)
    def assert_dispatch_v197() -> None:
        try:
            current()
            return None
        except execution_blocked as original_exc:
            allowed, reason = _startup_probe_allowed(authority)
            if not allowed:
                raise original_exc
            LOGGER.critical(
                "HEARTBEAT_PROBE_PIPELINE_BRIDGE_V197_ALLOWED marker=%s "
                "surface=dispatch_assertion probe_reason=%s whitelisted_startup_probe=true "
                "startup_authority_reverified=true ordinary_can_execute_unchanged=true "
                "downstream_risk_order_gates_unchanged=true forced_trade=false",
                MARKER,
                reason or "startup_probe_authorized",
            )
            return None

    setattr(assert_dispatch_v197, _PATCH_ATTR, True)
    setattr(assert_dispatch_v197, "__wrapped__", current)
    authority.assert_execution_dispatch_permitted = assert_dispatch_v197
    return assert_dispatch_v197


def _snapshot_proxy(snapshot: Any) -> Any:
    try:
        data = dict(getattr(snapshot, "__dict__", {}) or {})
    except Exception:
        data = {}
    for attr in (
        "authority_ready", "nonce_ready", "dispatch_health_ready", "dispatch_enabled",
        "kill_switch_active", "coordinator_state", "runtime_state", "reason", "lifecycle_phase",
    ):
        if attr not in data and hasattr(snapshot, attr):
            data[attr] = getattr(snapshot, attr)
    data["ready"] = True
    data["reason"] = "startup_probe_authorized:" + str(data.get("reason") or "runtime_not_fully_executing")
    return SimpleNamespace(**data)


def _pipeline_snapshot_wrapper(authority: ModuleType, original_snapshot: Callable[[], Any]) -> Callable[[], Any]:
    if bool(getattr(original_snapshot, _SNAPSHOT_PATCH_ATTR, False)):
        return original_snapshot

    @wraps(original_snapshot)
    def snapshot_v197() -> Any:
        snapshot = original_snapshot()
        if bool(getattr(snapshot, "ready", False)):
            return snapshot
        allowed, reason = _startup_probe_allowed(authority)
        if not allowed:
            return snapshot
        LOGGER.critical(
            "HEARTBEAT_PROBE_PIPELINE_BRIDGE_V197_ALLOWED marker=%s "
            "surface=runtime_snapshot probe_reason=%s whitelisted_startup_probe=true "
            "startup_authority_reverified=true ordinary_runtime_snapshot_unchanged=true "
            "downstream_risk_order_gates_unchanged=true forced_trade=false",
            MARKER,
            reason or "startup_probe_authorized",
        )
        return _snapshot_proxy(snapshot)

    setattr(snapshot_v197, _SNAPSHOT_PATCH_ATTR, True)
    setattr(snapshot_v197, "__wrapped__", original_snapshot)
    return snapshot_v197


def _bind_pipeline_surfaces(authority: ModuleType, dispatch_wrapper: Callable[[], None]) -> bool:
    """Bind both early Pipeline authority gates without mutating canonical snapshot truth."""
    bound_any = False
    for name in _PIPELINE_MODULE_NAMES:
        module = sys.modules.get(name)
        if not isinstance(module, ModuleType):
            continue
        current_dispatch = getattr(module, "assert_execution_dispatch_permitted", None)
        current_snapshot = getattr(module, "runtime_authority_snapshot", None)
        if not callable(current_dispatch) or not callable(current_snapshot):
            continue
        module.assert_execution_dispatch_permitted = dispatch_wrapper
        if not bool(getattr(current_snapshot, _SNAPSHOT_PATCH_ATTR, False)):
            module.runtime_authority_snapshot = _pipeline_snapshot_wrapper(authority, current_snapshot)
        bound_any = bool(
            getattr(module, "assert_execution_dispatch_permitted", None) is dispatch_wrapper
            and callable(getattr(module, "runtime_authority_snapshot", None))
            and getattr(module.runtime_authority_snapshot, _SNAPSHOT_PATCH_ATTR, False)
        ) or bound_any
    return bound_any


def _apply() -> bool:
    authority = _canonical_authority_module()
    dispatch_wrapper = _patch_authority_dispatch(authority)
    if not callable(dispatch_wrapper):
        return False
    try:
        importlib.import_module("bot.execution_pipeline")
    except Exception as exc:
        LOGGER.warning(
            "HEARTBEAT_PROBE_PIPELINE_BRIDGE_V197_PIPELINE_IMPORT_DEFERRED marker=%s error=%s:%s",
            MARKER,
            type(exc).__name__,
            exc,
        )
    bound = _bind_pipeline_surfaces(authority, dispatch_wrapper)
    present = any(isinstance(sys.modules.get(name), ModuleType) for name in _PIPELINE_MODULE_NAMES)
    return bool(bound or not present)


def _install_import_reassertion_hook() -> bool:
    if bool(getattr(builtins, _IMPORT_HOOK_ATTR, False)):
        return True
    original_import = builtins.__import__

    def guarded_import(name: str, globals: Any = None, locals: Any = None, fromlist: Any = (), level: int = 0) -> Any:
        module = original_import(name, globals, locals, fromlist, level)
        imported_name = str(name or "")
        if imported_name.endswith(("execution_authority_context", "execution_pipeline")):
            try:
                authority = _canonical_authority_module()
                dispatch_wrapper = _patch_authority_dispatch(authority)
                if callable(dispatch_wrapper):
                    _bind_pipeline_surfaces(authority, dispatch_wrapper)
            except Exception as exc:
                LOGGER.error(
                    "HEARTBEAT_PROBE_PIPELINE_BRIDGE_V197_REASSERT_FAILED marker=%s imported=%s "
                    "error=%s:%s trading_fail_closed=true",
                    MARKER,
                    name,
                    type(exc).__name__,
                    exc,
                )
        if imported_name.endswith("broker_manager"):
            try:
                _patch_heartbeat_market_discovery()
            except Exception as exc:
                os.environ[_V208_READY_FLAG] = "0"
                LOGGER.error(
                    "HEARTBEAT_MARKET_DISCOVERY_V208_REASSERT_FAILED marker=%s imported=%s "
                    "error=%s:%s trading_fail_closed=true",
                    V208_MARKER,
                    name,
                    type(exc).__name__,
                    exc,
                )
        return module

    builtins.__import__ = guarded_import
    setattr(builtins, _IMPORT_HOOK_ATTR, True)
    return True


def _patch_release_manifest() -> bool:
    try:
        manifest = importlib.import_module("bot.runtime_release_manifest_patch")
        required = getattr(manifest, "_REQUIRED_FLAGS", None)
        if not isinstance(required, dict):
            return False
        required["runtime_heartbeat_probe_pipeline_bridge_v197"] = _READY_FLAG
        required["runtime_heartbeat_required_scheduler_v200"] = _V200_READY_FLAG
        required["runtime_live_execution_heartbeat_scheduler_v201"] = _V201_READY_FLAG
        required["heartbeat_market_discovery_bound_v208"] = _V208_READY_FLAG
        return True
    except Exception:
        return False


def install() -> bool:
    with _LOCK:
        policy_ok = _align_required_heartbeat_scheduler_policy()
        market_discovery_ok = _patch_heartbeat_market_discovery()
        apply_ok = _apply()
        hook_ok = _install_import_reassertion_hook()
        manifest_ok = _patch_release_manifest()
        ready = bool(policy_ok and market_discovery_ok and apply_ok and hook_ok and manifest_ok)
        os.environ[_READY_FLAG] = "1" if ready else "0"
        if not ready:
            LOGGER.critical(
                "RUNTIME_HEARTBEAT_PROBE_PIPELINE_BRIDGE_V197_FAILED marker=%s "
                "policy=%s market_discovery=%s apply=%s hook=%s manifest=%s trading_fail_closed=true",
                MARKER,
                str(policy_ok).lower(),
                str(market_discovery_ok).lower(),
                str(apply_ok).lower(),
                str(hook_ok).lower(),
                str(manifest_ok).lower(),
            )
            return False
        LOGGER.critical(
            "RUNTIME_HEARTBEAT_PROBE_PIPELINE_BRIDGE_V197 marker=%s ready=true "
            "heartbeat_required_scheduler_v200=true live_execution_heartbeat_scheduler_v201=true "
            "heartbeat_market_discovery_bound_v208=true pipeline_snapshot_bridge=true pipeline_dispatch_bridge=true "
            "probe_reasons=HEARTBEAT_TRADE,HEARTBEAT_TRADE_CLOSE "
            "ordinary_can_execute_unchanged=true canonical_runtime_snapshot_unchanged=true "
            "startup_authority_reverified=true writer_nonce_risk_killswitch_order_gates_unchanged=true "
            "forced_trade=false safety_gates_bypassed=false",
            MARKER,
        )
        return True


def install_import_hook() -> bool:
    return install()


__all__ = [
    "MARKER",
    "V200_MARKER",
    "V201_MARKER",
    "V208_MARKER",
    "install",
    "install_import_hook",
    "_align_required_heartbeat_scheduler_policy",
    "_resolved_runtime_mode",
    "_heartbeat_market_discovery_timeout_s",
    "_wrap_heartbeat_market_discovery_method",
    "_patch_heartbeat_market_discovery",
    "_patch_authority_dispatch",
    "_bind_pipeline_surfaces",
]
