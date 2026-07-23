"""Runtime patch-churn and fail-closed safety repair.

This module hardens NIJA's dynamically installed runtime patches without
relaxing any trading gate. It prevents competing wrappers from repeatedly
stacking on the same methods, makes repeated installers process-idempotent,
keeps kill-switch probes fail-closed, requires complete distributed writer
lineage, and suppresses only byte-for-byte duplicate install telemetry.
"""

from __future__ import annotations

import builtins
import importlib
import logging
import os
import threading
from collections import deque
from types import ModuleType
from typing import Any, Callable, Iterable, Optional

logger = logging.getLogger("nija.runtime_patch_churn_safety")
_MARKER = "20260722-runtime-patch-churn-safety-v1"
_TRUE = {"1", "true", "yes", "on", "enabled", "y"}
_INSTALL_LOCK = threading.RLock()
_PATCHED = False


def _truthy(name: str) -> bool:
    return str(os.environ.get(name, "")).strip().lower() in _TRUE


def _callable_children(value: Any) -> Iterable[Callable[..., Any]]:
    for attr in ("__wrapped__", "_nija_original", "_original", "original"):
        child = getattr(value, attr, None)
        if callable(child):
            yield child
    closure = getattr(value, "__closure__", None)
    if closure:
        for cell in closure:
            try:
                child = cell.cell_contents
            except ValueError:
                continue
            if callable(child):
                yield child


def _walk_callable_chain(value: Any, limit: int = 64) -> Iterable[Callable[..., Any]]:
    queue: deque[Callable[..., Any]] = deque()
    if callable(value):
        queue.append(value)
    seen: set[int] = set()
    while queue and len(seen) < max(1, limit):
        current = queue.popleft()
        ident = id(current)
        if ident in seen:
            continue
        seen.add(ident)
        yield current
        for child in _callable_children(current):
            if id(child) not in seen:
                queue.append(child)


def _chain_has_attr(value: Any, attr: str) -> bool:
    return any(bool(getattr(item, attr, False)) for item in _walk_callable_chain(value))


def _set_wrapped(new_value: Any, previous: Any) -> None:
    if not callable(new_value) or not callable(previous) or new_value is previous:
        return
    if getattr(new_value, "__wrapped__", None) is None:
        try:
            setattr(new_value, "__wrapped__", previous)
        except Exception:
            pass


def _strict_kill_switch_clear() -> bool:
    """Fail closed when kill-switch state cannot be proven clear."""

    try:
        try:
            module = importlib.import_module("bot.kill_switch")
        except Exception:
            module = importlib.import_module("kill_switch")
        getter = getattr(module, "get_kill_switch", None)
        if not callable(getter):
            logger.error("RUNTIME_PATCH_SAFETY_KILL_SWITCH_UNAVAILABLE marker=%s", _MARKER)
            return False
        switch = getter()
        checker = getattr(switch, "is_active", None)
        if not callable(checker):
            logger.error("RUNTIME_PATCH_SAFETY_KILL_SWITCH_PROBE_MISSING marker=%s", _MARKER)
            return False
        return not bool(checker())
    except Exception as exc:
        logger.error(
            "RUNTIME_PATCH_SAFETY_KILL_SWITCH_PROBE_FAILED marker=%s err=%s",
            _MARKER,
            exc,
        )
        return False


def _strict_writer_authority_ready() -> bool:
    """Require the complete distributed writer lineage and live heartbeat."""

    token = str(os.environ.get("NIJA_WRITER_FENCING_TOKEN", "")).strip()
    generation = str(os.environ.get("NIJA_WRITER_LEASE_GENERATION", "")).strip()
    lease = _truthy("NIJA_WRITER_LEASE_ACQUIRED") or _truthy("NIJA_LOCK_ACQUIRED")
    heartbeat = _truthy("NIJA_WRITER_HEARTBEAT_ACTIVE")
    return bool(token and generation and lease and heartbeat)


def _number(value: Any, default: float = 0.0) -> float:
    try:
        result = float(value or 0.0)
        return result if result == result else default
    except Exception:
        return default


def _strict_capital_ready() -> bool:
    """Require fresh, broker-backed capital rather than the operator flag alone."""

    if not _truthy("LIVE_CAPITAL_VERIFIED"):
        return False
    if _truthy("DRY_RUN_MODE") or _truthy("PAPER_MODE"):
        return False
    try:
        try:
            module = importlib.import_module("bot.capital_authority")
        except Exception:
            module = importlib.import_module("capital_authority")
        getter = getattr(module, "get_capital_authority", None)
        if not callable(getter):
            return False
        authority = getter()
        hydrated = bool(getattr(authority, "is_hydrated", False))
        real = 0.0
        usable = 0.0
        valid_brokers = 0
        for attr in ("total_capital", "real_capital", "available_capital"):
            real = max(real, _number(getattr(authority, attr, 0.0)))
        for attr in ("usable_capital", "risk_capital", "available_capital"):
            usable = max(usable, _number(getattr(authority, attr, 0.0)))
        for method_name, target in (
            ("get_real_capital", "real"),
            ("get_total_capital", "real"),
            ("get_usable_capital", "usable"),
        ):
            method = getattr(authority, method_name, None)
            if not callable(method):
                continue
            try:
                value = _number(method())
            except Exception:
                continue
            if target == "real":
                real = max(real, value)
            else:
                usable = max(usable, value)
        for attr in ("valid_broker_count", "registered_broker_count", "ca_valid_brokers"):
            try:
                valid_brokers = max(valid_brokers, int(getattr(authority, attr, 0) or 0))
            except Exception:
                pass
        for attr in ("broker_balances", "_broker_balances", "broker_values", "values"):
            mapping = getattr(authority, attr, None)
            if isinstance(mapping, dict):
                valid_brokers = max(
                    valid_brokers,
                    sum(
                        1
                        for value in mapping.values()
                        if value is not None and _number(value) > 0.0
                    ),
                )
        fresh = True
        fresh_method = getattr(authority, "is_fresh", None)
        if callable(fresh_method):
            try:
                fresh = bool(fresh_method(ttl_s=180.0))
            except TypeError:
                fresh = bool(fresh_method())
            except Exception:
                fresh = False
        if usable <= 0.0:
            usable = real
        return bool(
            hydrated
            and real > 0.0
            and usable > 0.0
            and valid_brokers > 0
            and fresh
        )
    except Exception as exc:
        logger.warning(
            "RUNTIME_PATCH_SAFETY_CAPITAL_PROBE_FAILED marker=%s err=%s",
            _MARKER,
            exc,
        )
        return False


def _guard_module_installer(
    module: ModuleType,
    *,
    installer_name: str,
    class_name: str,
    method_name: str,
    marker_attr: str,
    patched_flag: str,
    pre_hook: Optional[Callable[[ModuleType], Any]] = None,
) -> bool:
    installer = getattr(module, installer_name, None)
    guard_attr = f"_nija_chain_guard_{installer_name}_{marker_attr}"
    if not callable(installer) or getattr(installer, guard_attr, False):
        return False

    def guarded(target_module: ModuleType) -> bool:
        if callable(pre_hook):
            try:
                pre_hook(target_module)
            except Exception as exc:
                logger.debug(
                    "RUNTIME_PATCH_SAFETY_PRE_HOOK_FAILED marker=%s installer=%s err=%s",
                    _MARKER,
                    installer_name,
                    exc,
                )
        cls = getattr(target_module, class_name, None)
        current = getattr(cls, method_name, None) if isinstance(cls, type) else None
        if callable(current) and _chain_has_attr(current, marker_attr):
            try:
                setattr(module, patched_flag, True)
            except Exception:
                pass
            return True

        previous = current
        result = bool(installer(target_module))
        cls_after = getattr(target_module, class_name, None)
        after = getattr(cls_after, method_name, None) if isinstance(cls_after, type) else None
        _set_wrapped(after, previous)
        return result

    setattr(guarded, guard_attr, True)
    setattr(guarded, "__wrapped__", installer)
    setattr(module, installer_name, guarded)
    return True


def _quiet_repeated_installer(
    module: ModuleType,
    *,
    process_key: str,
    installed_probes: tuple[str, ...],
) -> bool:
    installer = getattr(module, "install_import_hook", None)
    if not callable(installer) or getattr(
        installer, "_nija_runtime_patch_quiet_installer", False
    ):
        return False

    already_installed = any(bool(getattr(module, name, None)) for name in installed_probes)
    if already_installed:
        setattr(builtins, process_key, True)

    def guarded_install() -> Any:
        with _INSTALL_LOCK:
            if bool(getattr(builtins, process_key, False)):
                for helper_name in ("_try_patch_loaded", "_patch_loaded_modules"):
                    helper = getattr(module, helper_name, None)
                    if callable(helper):
                        try:
                            helper()
                        except Exception:
                            pass
                starter = getattr(module, "_start_monitor", None)
                if callable(starter):
                    try:
                        starter()
                    except Exception:
                        pass
                return None
            result = installer()
            setattr(builtins, process_key, True)
            return result

    setattr(guarded_install, "_nija_runtime_patch_quiet_installer", True)
    setattr(guarded_install, "__wrapped__", installer)
    setattr(module, "install_import_hook", guarded_install)
    return True


class _ExactDuplicateInstallFilter(logging.Filter):
    """Suppress only exact duplicate install/status messages; state changes still log."""

    _TOKENS = (
        "ECEL_KRAKEN_LIVE_FLOOR_PATCHED",
        "KRAKEN_EXECUTION_FLOOR_ENV_NORMALIZED",
        "LIVE_ACTIVE_EXECUTION_GATE_FINAL_PATCHED",
        "TRADING_STATE_DISPATCH_LATCH_REPAIR_PATCHED",
        "FINAL_EXECUTION_PIPELINE_CONTRACT_PATCHED",
        "OKX_LATE_BIND_COMPLETE",
    )
    _lock = threading.Lock()
    _seen: set[tuple[str, str]] = set()

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            message = record.getMessage()
        except Exception:
            return True
        if not any(token in message for token in self._TOKENS):
            return True
        key = (record.name, message)
        with self._lock:
            if key in self._seen:
                return False
            self._seen.add(key)
        return True


def _install_exact_duplicate_filters() -> None:
    for name in (
        "nija.kraken_live_order_size_repair",
        "nija.kraken_execution_floor_guard",
        "nija.live_active_execution_gate_final_patch",
        "nija.trading_state_dispatch_latch_repair",
        "nija.execution_contract_pipeline",
        "nija.venue_readiness_execution_repair",
    ):
        target = logging.getLogger(name)
        if getattr(target, "_nija_exact_duplicate_install_filter", False):
            continue
        target.addFilter(_ExactDuplicateInstallFilter())
        setattr(target, "_nija_exact_duplicate_install_filter", True)


def _guard_execution_contract_pipeline() -> bool:
    try:
        module = importlib.import_module("bot.execution_contract_pipeline")
    except Exception:
        return False
    patcher = getattr(module, "patch_pipeline", None)
    if not callable(patcher) or getattr(
        patcher, "_nija_runtime_patch_chain_guard", False
    ):
        return False

    def guarded(target_module: ModuleType) -> bool:
        cls = getattr(target_module, "ExecutionPipeline", None)
        reader = getattr(target_module, "runtime_authority_snapshot", None)
        execute = getattr(cls, "execute", None) if isinstance(cls, type) else None
        dispatch = getattr(cls, "_dispatch", None) if isinstance(cls, type) else None
        ready = bool(
            callable(reader)
            and _chain_has_attr(reader, "_nija_pin_20260710a")
            and callable(execute)
            and _chain_has_attr(execute, "_nija_contract_20260710a")
            and callable(dispatch)
            and _chain_has_attr(dispatch, "_nija_dispatch_contract_20260710a")
        )
        if ready:
            return True
        return bool(patcher(target_module))

    setattr(guarded, "_nija_runtime_patch_chain_guard", True)
    setattr(guarded, "__wrapped__", patcher)
    setattr(module, "patch_pipeline", guarded)
    return True


def _guard_ecel_patcher(
    module_name: str,
    *,
    upsert_attr: str,
    get_attr: str,
    compile_attr: str,
) -> bool:
    try:
        module = importlib.import_module(module_name)
    except Exception:
        return False
    patcher = getattr(module, "_patch_ecel", None)
    if not callable(patcher) or getattr(
        patcher, "_nija_runtime_patch_chain_guard", False
    ):
        return False

    def guarded(target_module: ModuleType) -> Any:
        schema_cls = getattr(target_module, "ContractSchemaMap", None)
        compiler_cls = getattr(target_module, "ECELExecutionCompiler", None)
        upsert = (
            getattr(schema_cls, "upsert_rule", None)
            if isinstance(schema_cls, type)
            else None
        )
        get_rule = (
            getattr(schema_cls, "get_rule", None)
            if isinstance(schema_cls, type)
            else None
        )
        compile_fn = (
            getattr(compiler_cls, "compile", None)
            if isinstance(compiler_cls, type)
            else None
        )
        if (
            callable(upsert)
            and _chain_has_attr(upsert, upsert_attr)
            and callable(get_rule)
            and _chain_has_attr(get_rule, get_attr)
            and callable(compile_fn)
            and _chain_has_attr(compile_fn, compile_attr)
        ):
            return None
        before = (upsert, get_rule, compile_fn)
        result = patcher(target_module)
        after = (
            getattr(schema_cls, "upsert_rule", None)
            if isinstance(schema_cls, type)
            else None,
            getattr(schema_cls, "get_rule", None)
            if isinstance(schema_cls, type)
            else None,
            getattr(compiler_cls, "compile", None)
            if isinstance(compiler_cls, type)
            else None,
        )
        for new_value, previous in zip(after, before):
            _set_wrapped(new_value, previous)
        return result

    setattr(guarded, "_nija_runtime_patch_chain_guard", True)
    setattr(guarded, "__wrapped__", patcher)
    setattr(module, "_patch_ecel", guarded)
    return True


def _patch_live_active_gate() -> bool:
    try:
        module = importlib.import_module("bot.live_active_execution_gate_final_patch")
    except Exception:
        return False
    module._kill_switch_clear = _strict_kill_switch_clear
    module._writer_authority_ready = _strict_writer_authority_ready
    module._capital_ready = _strict_capital_ready
    marker_attr = str(
        getattr(module, "_WRAP_ATTR", "")
        or "_nija_live_active_execution_gate_final_wrapped_v20260703q"
    )
    _guard_module_installer(
        module,
        installer_name="_install_on_module",
        class_name="TradingStateMachine",
        method_name="can_dispatch_trades",
        marker_attr=marker_attr,
        patched_flag="_PATCHED",
    )
    _quiet_repeated_installer(
        module,
        process_key="_NIJA_LIVE_ACTIVE_FINAL_INSTALL_COMPLETE_20260722",
        installed_probes=("_ORIGINAL_IMPORT_MODULE", "_PATCHED"),
    )
    return True


def _patch_dispatch_latch() -> bool:
    try:
        module = importlib.import_module("bot.trading_state_dispatch_latch_repair_patch")
    except Exception:
        return False
    module._kill_switch_clear = _strict_kill_switch_clear
    pre_hook = getattr(module, "_install_lease_generation_patch_on_module", None)
    _guard_module_installer(
        module,
        installer_name="_install_on_module",
        class_name="TradingStateMachine",
        method_name="can_dispatch_trades",
        marker_attr="_nija_trading_state_dispatch_latch_repair_wrapped",
        patched_flag="_PATCHED",
        pre_hook=pre_hook if callable(pre_hook) else None,
    )
    _quiet_repeated_installer(
        module,
        process_key="_NIJA_DISPATCH_LATCH_INSTALL_COMPLETE_20260722",
        installed_probes=("_ORIGINAL_IMPORT_MODULE", "_PATCHED"),
    )
    return True


def install_import_hook() -> None:
    global _PATCHED
    with _INSTALL_LOCK:
        _install_exact_duplicate_filters()
        results = {
            "live_active": _patch_live_active_gate(),
            "dispatch_latch": _patch_dispatch_latch(),
            "execution_contract": _guard_execution_contract_pipeline(),
            "kraken_live_ecel": _guard_ecel_patcher(
                "bot.kraken_live_order_size_repair_patch",
                upsert_attr="_nija_kraken_live_floor_wrapped",
                get_attr="_nija_kraken_live_floor_wrapped",
                compile_attr="_nija_kraken_live_floor_wrapped",
            ),
            "kraken_floor_ecel": _guard_ecel_patcher(
                "bot.kraken_execution_floor_guard_patch",
                upsert_attr="_nija_kraken_entry_final_floor",
                get_attr="_nija_kraken_entry_final_floor",
                compile_attr="_nija_kraken_entry_target",
            ),
        }
        first_install = not _PATCHED
        _PATCHED = True
        os.environ["NIJA_RUNTIME_PATCH_CHURN_SAFETY_READY"] = "1"
        if first_install:
            logger.warning(
                "RUNTIME_PATCH_CHURN_SAFETY_READY marker=%s results=%s fail_closed=true",
                _MARKER,
                results,
            )


def install() -> None:
    install_import_hook()


__all__ = [
    "install",
    "install_import_hook",
    "_chain_has_attr",
    "_strict_kill_switch_clear",
    "_strict_writer_authority_ready",
    "_strict_capital_ready",
    "_ExactDuplicateInstallFilter",
]
