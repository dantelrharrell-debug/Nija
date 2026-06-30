"""Synchronize latest hydrated broker balances into capital refresh caches.

Logging showed Kraken hydrating a newer enriched equity value after startup while
capital refresh still read an older cached balance. This module only propagates
newer broker balance values into common in-memory cache fields before/after
capital refresh methods run. It does not submit, cancel, or modify orders.
"""

from __future__ import annotations

import builtins
import logging
import time
from functools import wraps
from typing import Any

logger = logging.getLogger("nija.capital_balance_propagation")
_PATCHED_ATTR = "__nija_capital_balance_propagation_patch__"


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value or 0.0)
    except Exception:
        return default


def _name(obj: Any) -> str:
    return str(getattr(obj, "name", None) or getattr(obj, "broker_name", None) or obj.__class__.__name__).lower()


def _latest_balance(obj: Any) -> float:
    values = []
    for attr in ("_last_known_balance", "last_known_balance", "_hydrated_balance", "hydrated_balance", "_capital_balance", "capital_balance"):
        values.append(_safe_float(getattr(obj, attr, 0.0)))
    for attr in ("_last_raw_balances", "last_raw_balances", "_balance_payload", "balance_payload"):
        payload = getattr(obj, attr, None)
        if isinstance(payload, dict):
            for key in ("total_funds", "equity", "total_equity", "trading_balance"):
                values.append(_safe_float(payload.get(key)))
    return max(values or [0.0])


def _stamp(obj: Any, value: float, source: str) -> None:
    if value <= 0:
        return
    for attr in ("_last_known_balance", "last_known_balance", "_hydrated_balance", "hydrated_balance", "_capital_balance", "capital_balance"):
        try:
            if value >= _safe_float(getattr(obj, attr, 0.0)):
                setattr(obj, attr, value)
        except Exception:
            pass
    try:
        setattr(obj, "_last_balance_source", source)
        setattr(obj, "_last_balance_update_ts", time.time())
    except Exception:
        pass


def _iter_brokers(owner: Any):
    seen = set()
    for attr in ("brokers", "platform_brokers", "broker_instances", "_brokers", "_platform_brokers", "connected_brokers", "user_brokers"):
        group = getattr(owner, attr, None)
        items = group.values() if isinstance(group, dict) else group if isinstance(group, (list, tuple, set)) else []
        for item in items:
            if item is not None and id(item) not in seen:
                seen.add(id(item))
                yield item


def _sync_owner(owner: Any, label: str) -> None:
    updates = []
    for broker in _iter_brokers(owner):
        bal = _latest_balance(broker)
        if bal <= 0:
            continue
        broker_name = _name(broker)
        _stamp(broker, bal, label)
        updates.append(f"{broker_name}:{bal:.2f}")
        for attr in ("balances", "_balances", "broker_balances", "_broker_balances", "latest_balances", "_latest_balances", "capital_balances", "_capital_balances"):
            mapping = getattr(owner, attr, None)
            if isinstance(mapping, dict):
                mapping[broker_name] = max(_safe_float(mapping.get(broker_name)), bal)
                if "kraken" in broker_name:
                    mapping["kraken"] = max(_safe_float(mapping.get("kraken")), bal)
    if updates:
        logger.warning("CAPITAL_BALANCE_PROPAGATION_SYNC label=%s updates=%s", label, ",".join(updates))


def _patch_broker(cls: type) -> bool:
    if getattr(cls, _PATCHED_ATTR, False):
        return True
    patched = False
    for method_name in ("get_account_balance", "get_balance_snapshot", "refresh_balance", "fetch_balance", "connect"):
        original = getattr(cls, method_name, None)
        if not callable(original):
            continue
        @wraps(original)
        def wrapper(self: Any, *args: Any, __original=original, __method_name=method_name, **kwargs: Any):
            result = __original(self, *args, **kwargs)
            bal = _safe_float(result)
            if isinstance(result, dict):
                bal = max(_safe_float(result.get("total_funds")), _safe_float(result.get("equity")), _safe_float(result.get("total_equity")), _safe_float(result.get("trading_balance")))
            bal = max(bal, _latest_balance(self))
            if bal > 0:
                _stamp(self, bal, f"{cls.__name__}.{__method_name}")
                logger.warning("BROKER_BALANCE_PROPAGATED broker=%s method=%s balance=%.2f", _name(self), __method_name, bal)
            return result
        setattr(wrapper, _PATCHED_ATTR, True)
        setattr(cls, method_name, wrapper)
        patched = True
    if patched:
        setattr(cls, _PATCHED_ATTR, True)
        logger.warning("BROKER_BALANCE_PROPAGATION_PATCHED class=%s", cls.__name__)
    return patched


def _patch_manager(cls: type) -> bool:
    if getattr(cls, _PATCHED_ATTR, False):
        return True
    patched = False
    for method_name in ("refresh_capital_authority", "_refresh_capital_authority", "execute_refresh", "_force_minimal_capital_snapshot", "_build_capital_snapshot", "initialize"):
        original = getattr(cls, method_name, None)
        if not callable(original):
            continue
        @wraps(original)
        def wrapper(self: Any, *args: Any, __original=original, __method_name=method_name, **kwargs: Any):
            _sync_owner(self, f"before:{cls.__name__}.{__method_name}")
            result = __original(self, *args, **kwargs)
            _sync_owner(self, f"after:{cls.__name__}.{__method_name}")
            return result
        setattr(wrapper, _PATCHED_ATTR, True)
        setattr(cls, method_name, wrapper)
        patched = True
    if patched:
        setattr(cls, _PATCHED_ATTR, True)
        logger.warning("CAPITAL_MANAGER_BALANCE_PROPAGATION_PATCHED class=%s", cls.__name__)
    return patched


def _patch_module(module: Any) -> None:
    for name in dir(module):
        obj = getattr(module, name, None)
        if not isinstance(obj, type):
            continue
        lname = name.lower()
        if any(k in lname for k in ("broker", "kraken", "coinbase", "okx")):
            _patch_broker(obj)
        if any(k in lname for k in ("multi", "manager", "capital", "coordinator")):
            _patch_manager(obj)


def install_import_hook() -> None:
    import sys
    for name, module in list(sys.modules.items()):
        if name.startswith("bot."):
            try:
                _patch_module(module)
            except Exception:
                pass
    if getattr(builtins, "_NIJA_CAPITAL_BALANCE_PROPAGATION_HOOK_INSTALLED", False):
        return
    original_import = builtins.__import__
    def guarded_import(name: str, globals=None, locals=None, fromlist=(), level: int = 0):
        module = original_import(name, globals, locals, fromlist, level)
        try:
            if name.startswith("bot"):
                _patch_module(module)
        except Exception:
            pass
        return module
    builtins.__import__ = guarded_import
    setattr(builtins, "_NIJA_CAPITAL_BALANCE_PROPAGATION_HOOK_INSTALLED", True)
    logger.warning("CAPITAL_BALANCE_PROPAGATION_INSTALL_COMPLETE")
