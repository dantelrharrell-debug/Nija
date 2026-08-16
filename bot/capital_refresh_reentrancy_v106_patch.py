"""Prevent same-thread recursive capital refresh during startup.

Production logs on 2026-08-16 show CapitalAuthority refresh succeeding and then
startup callbacks re-entering MultiAccountBrokerManager.refresh_capital_authority()
until RecursionError.  v105 guarded one callback (_on_platform_ready), but the
same refresh method is also reached from BootstrapContract, runtime convergence,
Kraken recovery, and self-healing startup paths.

v106 installs the guard at the shared refresh choke point.  A same-thread
recursive call never starts another refresh.  It may report only capital state
that was already authoritatively published by CapitalAuthority; otherwise it
returns a conservative pending/not-ready result.  It never fabricates balances,
connectivity, readiness, execution authority, nonce state, positions, or writer
ownership, and it does not weaken any activation/risk/kill-switch gate.
"""
from __future__ import annotations

import importlib
import logging
import os
import sys
import threading
from functools import wraps
from types import ModuleType
from typing import Any, Dict

LOGGER = logging.getLogger("nija.capital_refresh_reentrancy_v106")
MARKER = "20260816-capital-refresh-reentrancy-v106"
_LOCK = threading.RLock()
_LOCAL = threading.local()
_INSTALLED = False


def _authoritative_snapshot(module: ModuleType, manager: Any) -> Dict[str, float]:
    """Return only already-published CapitalAuthority truth.

    The helper intentionally does not call broker balance APIs and does not
    invoke refresh.  If the exact authoritative shape cannot be proven, return
    pending/not-ready so downstream startup remains fail closed.
    """
    ca = None
    getter = getattr(module, "get_capital_authority", None)
    if callable(getter):
        try:
            ca = getter()
        except Exception:
            ca = None

    ready = False
    total = 0.0
    valid = 0.0
    kraken = 0.0

    if ca is not None:
        for attr in ("is_hydrated", "hydrated", "_hydrated"):
            value = getattr(ca, attr, None)
            try:
                ready = bool(value() if callable(value) else value)
            except Exception:
                ready = False
            if ready:
                break

        for attr in ("total_capital", "real_capital", "total", "_total_capital", "_real_capital"):
            value = getattr(ca, attr, None)
            try:
                value = value() if callable(value) else value
                if value is not None:
                    total = float(value)
                    if total > 0.0:
                        break
            except Exception:
                continue

        snapshot = getattr(ca, "snapshot", None) or getattr(ca, "_snapshot", None)
        try:
            if snapshot is not None:
                if total <= 0.0:
                    for attr in ("total_capital", "real_capital", "total_usd", "total"):
                        value = getattr(snapshot, attr, None)
                        if value is not None:
                            total = float(value)
                            if total > 0.0:
                                break
                balances = getattr(snapshot, "broker_balances", None)
                if isinstance(balances, dict):
                    valid = float(sum(1 for v in balances.values() if float(v or 0.0) > 0.0))
                    kraken = float(balances.get("kraken", 0.0) or 0.0)
        except Exception:
            pass

    if total <= 0.0:
        ready = False

    return {
        "ready": 1.0 if ready else 0.0,
        "total_capital": max(0.0, total),
        "valid_brokers": max(0.0, valid),
        "kraken_capital": max(0.0, kraken),
        "pending": 0.0 if ready else 1.0,
        "reentrant": 1.0,
    }


def _patch_module(module: ModuleType) -> bool:
    cls = getattr(module, "MultiAccountBrokerManager", None)
    if not isinstance(cls, type):
        return False

    original = getattr(cls, "refresh_capital_authority", None)
    if not callable(original):
        return False
    if getattr(original, "_nija_v106_wrapped", False):
        return True

    @wraps(original)
    def _guarded(self: Any, trigger: str = "manual", *args: Any, **kwargs: Any) -> Any:
        depth = int(getattr(_LOCAL, "capital_refresh_depth", 0) or 0)
        if depth > 0:
            snapshot = _authoritative_snapshot(module, self)
            LOGGER.warning(
                "CAPITAL_REFRESH_V106_REENTRANT_SUPPRESSED marker=%s trigger=%s depth=%d authoritative_ready=%s total=%.2f valid_brokers=%d trading_fail_closed=%s",
                MARKER,
                trigger,
                depth,
                bool(snapshot.get("ready", 0.0)),
                float(snapshot.get("total_capital", 0.0)),
                int(snapshot.get("valid_brokers", 0.0)),
                str(not bool(snapshot.get("ready", 0.0))).lower(),
            )
            return snapshot

        _LOCAL.capital_refresh_depth = depth + 1
        try:
            return original(self, trigger, *args, **kwargs)
        finally:
            _LOCAL.capital_refresh_depth = depth

    setattr(_guarded, "_nija_v106_wrapped", True)
    setattr(_guarded, "_nija_v106_original", original)
    cls.refresh_capital_authority = _guarded  # type: ignore[assignment]
    LOGGER.critical(
        "CAPITAL_REFRESH_REENTRANCY_V106_PATCHED marker=%s module=%s method=MultiAccountBrokerManager.refresh_capital_authority same_thread_recursive_refresh_blocked=true authoritative_snapshot_only=true safety_gates_unchanged=true",
        MARKER,
        module.__name__,
    )
    return True


def _patch_loaded() -> bool:
    patched = False
    seen = set()
    for name in ("bot.multi_account_broker_manager", "multi_account_broker_manager"):
        module = sys.modules.get(name)
        if not isinstance(module, ModuleType) or id(module) in seen:
            continue
        seen.add(id(module))
        patched = _patch_module(module) or patched
    return patched


def install() -> bool:
    global _INSTALLED
    with _LOCK:
        if _INSTALLED:
            _patch_loaded()
            return True

        _patch_loaded()

        # If MABM is not loaded yet, add a narrow import hook so the exact class
        # method is patched immediately after its module finishes importing.
        import builtins
        current_import = builtins.__import__
        if not getattr(current_import, "_nija_v106_import_hook", False):
            @wraps(current_import)
            def _import(name: str, globals: Any = None, locals: Any = None, fromlist: Any = (), level: int = 0) -> Any:
                result = current_import(name, globals, locals, fromlist, level)
                if name in {"bot.multi_account_broker_manager", "multi_account_broker_manager"} or _patch_loaded():
                    _patch_loaded()
                return result

            setattr(_import, "_nija_v106_import_hook", True)
            setattr(_import, "_nija_v106_original", current_import)
            builtins.__import__ = _import

        os.environ["NIJA_CAPITAL_REFRESH_REENTRANCY_V106_INSTALLED"] = "1"
        _INSTALLED = True
        LOGGER.critical(
            "CAPITAL_REFRESH_REENTRANCY_V106_INSTALLED marker=%s shared_refresh_choke_guard=true authoritative_snapshot_only=true readiness_bypass=false execution_bypass=false position_fabrication=false",
            MARKER,
        )
        return True


def install_import_hook() -> bool:
    return install()


__all__ = ["MARKER", "install", "install_import_hook"]
