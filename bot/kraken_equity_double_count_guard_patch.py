"""Final Kraken equity guard that excludes held-value double counting.

Kraken asset balances already include assets tied to open orders.  Adding a
separate ``held`` amount to the same crypto holdings inflated Tania's $93.26
exchange equity to $104.32 and inflated the platform total similarly.  The
canonical total is now exchange equity or cash plus dynamically priced assets;
held value is telemetry only and is never added a second time.
"""

from __future__ import annotations

import builtins
import logging
import sys
import threading
from functools import wraps
from types import ModuleType
from typing import Any, Mapping

logger = logging.getLogger("nija.kraken_equity_double_count_guard")
_MARKER = "20260713-kraken-equity-double-count-v1"
_PATCH_ATTR = "_nija_kraken_equity_double_count_v1"
_ORIGINAL_IMPORT = None
_LOCK = threading.RLock()
_PATCHED: set[tuple[str, int]] = set()


def _f(value: Any) -> float:
    try:
        parsed = float(value or 0.0)
        return parsed if parsed == parsed else 0.0
    except Exception:
        return 0.0


def _exchange_equity(payload: Mapping[str, Any]) -> float:
    values = []
    for key in ("eb", "e", "equivalent_balance", "exchange_equity"):
        values.append(_f(payload.get(key)))
    result = payload.get("result")
    if isinstance(result, Mapping):
        for key in ("eb", "e", "equivalent_balance", "exchange_equity"):
            values.append(_f(result.get(key)))
    return max([0.0] + values)


def _value_from_result(value: Any) -> float:
    if isinstance(value, Mapping):
        for key in ("total_funds", "total_balance", "total_equity", "equity", "available_balance", "balance"):
            parsed = _f(value.get(key))
            if parsed > 0:
                return parsed
        return 0.0
    return _f(value)


def _canonical(instance: Any, fallback: float) -> tuple[float, float, float, float]:
    try:
        from bot import kraken_equity_runtime_patch as equity
    except ImportError:
        import kraken_equity_runtime_patch as equity  # type: ignore[import]

    payload = equity._call_balance_payload(instance, allow_live_probe=False)
    raw_assets = equity._extract_raw_balances(payload)
    positions = equity._build_positions(instance, raw_assets)
    cash = equity._cash_from_payload(payload)
    crypto = sum(_f(row.get("size_usd")) for row in positions)
    exchange = _exchange_equity(payload)
    computed = cash + crypto

    if exchange > 0 and computed > 0:
        total = max(exchange, computed)
    elif exchange > 0:
        total = exchange
    elif computed > 0:
        total = computed
    else:
        total = fallback
    return total, exchange, cash, crypto


def _patch_class(cls: type) -> bool:
    current = getattr(cls, "get_account_balance", None)
    if not callable(current) or getattr(current, _PATCH_ATTR, False):
        return False
    original = current

    @wraps(original)
    def get_account_balance(self: Any, *args: Any, **kwargs: Any):
        value = original(self, *args, **kwargs)
        fallback = _value_from_result(value)
        canonical, exchange, cash, crypto = _canonical(self, fallback)
        held = 0.0
        try:
            from bot import kraken_equity_runtime_patch as equity
            payload = equity._call_balance_payload(self, allow_live_probe=False)
            held = max(_f(payload.get("usd_held")), _f(payload.get("total_held")))
        except Exception:
            pass
        try:
            self._last_known_balance = canonical
            payload = getattr(self, "_last_raw_balances", None)
            if isinstance(payload, dict):
                payload["total_funds"] = canonical
                payload["canonical_equity"] = canonical
                payload["held_excluded_from_equity_sum"] = held
        except Exception:
            pass
        logger.critical(
            "KRAKEN_EQUITY_DOUBLE_COUNT_PREVENTED marker=%s account=%s fallback=$%.2f "
            "exchange=$%.2f cash=$%.2f crypto=$%.2f held_not_added=$%.2f canonical=$%.2f",
            _MARKER,
            getattr(self, "account_identifier", getattr(self, "account_id", "unknown")),
            fallback,
            exchange,
            cash,
            crypto,
            held,
            canonical,
        )
        if isinstance(value, Mapping):
            result = dict(value)
            result["total_balance"] = canonical
            result["total_funds"] = canonical
            result["canonical_equity"] = canonical
            return result
        return canonical

    setattr(get_account_balance, _PATCH_ATTR, True)
    setattr(get_account_balance, "__wrapped__", original)
    setattr(cls, "get_account_balance", get_account_balance)
    logger.warning("KRAKEN_EQUITY_DOUBLE_COUNT_GUARD_PATCHED marker=%s class=%s", _MARKER, cls.__name__)
    return True


def _patch_module(module: ModuleType) -> bool:
    key = (str(getattr(module, "__name__", "")), id(module))
    if key in _PATCHED:
        return True
    changed = False
    for name in dir(module):
        cls = getattr(module, name, None)
        if isinstance(cls, type) and "kraken" in name.lower():
            changed = _patch_class(cls) or changed
    if changed:
        _PATCHED.add(key)
    return changed


def _patch_loaded() -> None:
    for module in tuple(sys.modules.values()):
        if isinstance(module, ModuleType) and str(getattr(module, "__name__", "")).endswith(("broker_manager", "broker_integration", "kraken_broker")):
            try:
                _patch_module(module)
            except Exception:
                continue


def install_import_hook() -> None:
    global _ORIGINAL_IMPORT
    _patch_loaded()
    with _LOCK:
        if _ORIGINAL_IMPORT is not None:
            return
        _ORIGINAL_IMPORT = builtins.__import__
        local = threading.local()

        def guarded_import(name: str, globals=None, locals=None, fromlist=(), level: int = 0):
            module = _ORIGINAL_IMPORT(name, globals, locals, fromlist, level)  # type: ignore[misc]
            if getattr(local, "active", False):
                return module
            local.active = True
            try:
                _patch_loaded()
            finally:
                local.active = False
            return module

        builtins.__import__ = guarded_import  # type: ignore[assignment]
    _patch_loaded()
    logger.critical("KRAKEN_EQUITY_DOUBLE_COUNT_GUARD_INSTALLED marker=%s", _MARKER)


__all__ = ["install_import_hook", "_exchange_equity", "_canonical", "_patch_class"]
