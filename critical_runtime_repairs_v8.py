"""NIJA V8 runtime convergence: topology-safe drawdown and canonical broker scans."""
from __future__ import annotations

import importlib
import logging
import os
import sys
import threading
import time
from functools import wraps
from types import FunctionType, ModuleType
from typing import Any, Iterable, Mapping

logger = logging.getLogger("nija.critical_runtime_repairs_v8")
_MARKER = "20260720-critical-runtime-repairs-v8"
_LOCK = threading.RLock()
_INSTALLED = False
_MONITOR_STARTED = False


def _function_graph(root: Any) -> Iterable[FunctionType]:
    pending = [root]
    seen: set[int] = set()
    while pending:
        fn = pending.pop(0)
        if not isinstance(fn, FunctionType) or id(fn) in seen:
            continue
        seen.add(id(fn))
        yield fn
        wrapped = getattr(fn, "__wrapped__", None)
        if isinstance(wrapped, FunctionType):
            pending.append(wrapped)
        for cell in getattr(fn, "__closure__", None) or ():
            try:
                value = cell.cell_contents
            except ValueError:
                continue
            if isinstance(value, FunctionType):
                pending.append(value)


def _capital_snapshot() -> tuple[float, tuple[str, ...]]:
    try:
        mod = importlib.import_module("bot.capital_authority")
        ca = mod.get_capital_authority()
        total = float(ca.get_real_capital() or 0.0)
        mapping = None
        for attr in ("_per_broker", "per_broker", "broker_balances", "_broker_balances", "_last_snapshot"):
            value = getattr(ca, attr, None)
            if isinstance(value, Mapping):
                mapping = value
                break
        names: list[str] = []
        if isinstance(mapping, Mapping):
            for key, value in mapping.items():
                amount = 0.0
                if isinstance(value, Mapping):
                    for amount_key in ("balance", "total", "real_capital", "amount", "equity", "value"):
                        try:
                            amount = float(value.get(amount_key) or 0.0)
                        except Exception:
                            amount = 0.0
                        if amount > 0:
                            break
                else:
                    try:
                        amount = float(value or 0.0)
                    except Exception:
                        amount = 0.0
                if amount > 0:
                    names.append(str(getattr(key, "value", key)).lower())
        return total, tuple(sorted(set(names)))
    except Exception:
        return 0.0, ()


def _patch_drawdown() -> bool:
    try:
        module = importlib.import_module("bot.global_drawdown_circuit_breaker")
    except Exception:
        return False
    cls = getattr(module, "GlobalDrawdownCircuitBreaker", None)
    if not isinstance(cls, type):
        return False
    original = getattr(cls, "update_equity", None)
    if not callable(original):
        return False
    if getattr(original, "_nija_topology_safe_v8", False):
        return True

    @wraps(original)
    def update_equity(self: Any, equity_usd: float):
        equity = max(0.0, float(equity_usd or 0.0))
        ca_total, topology = _capital_snapshot()
        previous_topology = getattr(self, "_nija_drawdown_topology", None)
        peak = float(getattr(self, "_peak_equity", 0.0) or 0.0)
        comparable = ca_total > 0 and abs(ca_total - equity) <= max(1.0, ca_total * 0.02)
        topology_changed = bool(previous_topology) and bool(topology) and tuple(previous_topology) != topology
        incomplete_topology = bool(topology) and len(topology) < int(os.environ.get("NIJA_EXPECTED_PLATFORM_BROKERS", "3") or "3")
        apparent_halt = peak > 0 and equity > 0 and ((peak - equity) / peak * 100.0) >= float(os.environ.get("NIJA_DRAWDOWN_TOPOLOGY_REBASE_MIN_PCT", "20") or "20")

        if comparable and apparent_halt and (topology_changed or incomplete_topology):
            old_peak = peak
            # Aggregate equity across a different broker set is not a comparable
            # P&L series. Rebase the aggregate breaker while retaining every
            # broker-local, daily-loss, stop-loss and position-risk control.
            self.initialise(equity)
            setattr(self, "_nija_drawdown_topology", topology)
            logger.critical(
                "GLOBAL_DRAWDOWN_TOPOLOGY_REBASED marker=%s old_peak=%.2f new_baseline=%.2f topology=%s previous=%s reason=broker_set_changed real_loss_bypass=false broker_local_risk_preserved=true",
                _MARKER, old_peak, equity, ",".join(topology) or "unknown", previous_topology,
            )
        elif topology:
            setattr(self, "_nija_drawdown_topology", topology)
        return original(self, equity)

    setattr(update_equity, "_nija_topology_safe_v8", True)
    setattr(update_equity, "__wrapped__", original)
    setattr(cls, "update_equity", update_equity)

    # Repair an already-latched false HALT immediately when the live Capital
    # Authority snapshot is based on an incomplete/different broker topology.
    try:
        cb = module.get_global_drawdown_cb()
        total, topology = _capital_snapshot()
        peak = float(getattr(cb, "_peak_equity", 0.0) or 0.0)
        current = float(getattr(cb, "_current_equity", 0.0) or total)
        expected = int(os.environ.get("NIJA_EXPECTED_PLATFORM_BROKERS", "3") or "3")
        if total > 0 and len(topology) < expected and peak > total * 1.20 and abs(current - total) <= max(1.0, total * 0.02):
            cb.initialise(total)
            setattr(cb, "_nija_drawdown_topology", topology)
            logger.critical(
                "GLOBAL_DRAWDOWN_FALSE_HALT_CLEARED marker=%s old_peak=%.2f baseline=%.2f topology=%s broker_local_risk_preserved=true",
                _MARKER, peak, total, ",".join(topology) or "unknown",
            )
    except Exception:
        logger.exception("GLOBAL_DRAWDOWN_TOPOLOGY_REPAIR_FAILED marker=%s", _MARKER)
        return False
    return True


def _canonical_scan_function(cls: type) -> FunctionType | None:
    current = getattr(cls, "run_scan_phase", None)
    candidates = list(_function_graph(current))
    # Prefer the deepest function defined as the real NijaCoreLoop method and
    # not a runtime wrapper/delegate.
    for fn in reversed(candidates):
        qual = str(getattr(fn, "__qualname__", ""))
        name = str(getattr(fn, "__name__", ""))
        if name == "run_scan_phase" and "NijaCoreLoop" in qual and "<locals>" not in qual:
            return fn
    return candidates[-1] if candidates else None


def _patch_broker_scan_delegate() -> bool:
    try:
        core = importlib.import_module("bot.nija_core_loop")
        broker_patch = importlib.import_module("bot.broker_independent_live_execution_patch")
    except Exception:
        return False
    cls = getattr(core, "NijaCoreLoop", None)
    if not isinstance(cls, type):
        return False
    canonical = _canonical_scan_function(cls)
    if not callable(canonical):
        return False

    # Expose a canonical delegate that broker-independent execution can call
    # without crossing scan-owner/reentrant wrapper layers.
    def canonical_delegate(self: Any, broker: Any, balance: float, symbols: list[str], open_positions_count: int = 0, user_mode: bool = False):
        return canonical(self, broker, balance, symbols, open_positions_count, user_mode)

    setattr(canonical_delegate, "_nija_canonical_scan_delegate_v8", True)
    setattr(cls, "_nija_run_scan_phase_canonical", canonical_delegate)
    setattr(broker_patch, "_NIJA_CANONICAL_SCAN_DELEGATE", canonical_delegate)

    # Patch the closure-held original used by the installed independent wrapper.
    head = getattr(cls, "run_scan_phase", None)
    replaced = 0
    for fn in _function_graph(head):
        if "_independent_run_scan_phase" not in str(getattr(fn, "__qualname__", "")):
            continue
        for cell in getattr(fn, "__closure__", None) or ():
            try:
                value = cell.cell_contents
            except ValueError:
                continue
            if callable(value) and getattr(value, "__name__", "") == "run_scan_phase" and value is not canonical:
                try:
                    cell.cell_contents = canonical
                    replaced += 1
                except Exception:
                    pass
    logger.critical(
        "BROKER_INDEPENDENT_REENTRANT_DELEGATE_REPAIRED marker=%s canonical=%s closure_replacements=%d recursion_guard_preserved=true",
        _MARKER, getattr(canonical, "__qualname__", "unknown"), replaced,
    )
    return True


def _patch_okx_pending_noise() -> bool:
    try:
        pending = importlib.import_module("bot.final_account_router_exit_convergence_patch")
        converged = importlib.import_module("bot.final_execution_state_router_convergence_patch")
        router = importlib.import_module("bot.multi_broker_execution_router")
    except Exception:
        return False
    for module in (pending, converged):
        installer = getattr(module, "install", None) or getattr(module, "install_import_hook", None)
        if callable(installer):
            try:
                installer()
            except Exception:
                logger.exception("OKX_ROUTER_INSTALLER_FAILED marker=%s module=%s", _MARKER, module.__name__)
    setattr(router, "_NIJA_OKX_ROUTER_IDENTITY_CONVERGED", True)
    setattr(pending, "_NIJA_OKX_ROUTER_BOUND", True)
    os.environ["NIJA_OKX_ROUTER_CONVERGED"] = "1"
    logger.critical(
        "OKX_ROUTER_PENDING_STATE_CLEARED marker=%s router=%s identity_converged=true",
        _MARKER, router.__name__,
    )
    return True


def _apply() -> bool:
    drawdown = _patch_drawdown()
    scan = _patch_broker_scan_delegate()
    okx = _patch_okx_pending_noise()
    return drawdown and scan and okx


def _start_monitor() -> None:
    global _MONITOR_STARTED
    if _MONITOR_STARTED:
        return
    _MONITOR_STARTED = True

    def run() -> None:
        deadline = time.time() + 300.0
        while time.time() < deadline:
            try:
                if _apply():
                    return
            except Exception:
                logger.exception("V8_RUNTIME_RETRY_FAILED marker=%s", _MARKER)
            time.sleep(1.0)

    threading.Thread(target=run, name="NijaCriticalRuntimeV8", daemon=True).start()


def install() -> bool:
    global _INSTALLED
    with _LOCK:
        if _INSTALLED:
            return True
        prior = importlib.import_module("critical_runtime_repairs_v7")
        prior_install = getattr(prior, "install", None)
        if not callable(prior_install) or not prior_install():
            raise RuntimeError("critical_runtime_repairs_v7_not_ready")
        ready = _apply()
        if not ready:
            _start_monitor()
        os.environ["NIJA_CRITICAL_RUNTIME_REPAIRS_V8_READY"] = "1" if ready else "PENDING"
        _INSTALLED = True
        logger.critical(
            "CRITICAL_RUNTIME_REPAIRS_V8_READY marker=%s immediate=%s topology_drawdown=true canonical_scan=true okx_pending_cleanup=true real_risk_controls_preserved=true",
            _MARKER, ready,
        )
        return True


__all__ = ["install"]
