from __future__ import annotations

import builtins
import logging
import os
import sys
import threading
from functools import wraps
from types import ModuleType
from typing import Any

logger = logging.getLogger("nija.broker_scoped_hardening_repair")
_MARKER = "20260709at"
_HOOK = "_NIJA_BROKER_SCOPED_HARDENING_HOOK_20260709AT"
_VALIDATE = "_nija_broker_scoped_validation_20260709at"
_GETTER = "_nija_broker_scoped_getter_20260709at"
_TRUE = {"1", "true", "yes", "on", "enabled", "y"}


def _truthy(name: str, default: str = "false") -> bool:
    return str(os.environ.get(name, default)).strip().lower() in _TRUE


def _num(value: Any) -> float:
    try:
        result = float(value)
        return result if result == result else 0.0
    except Exception:
        return 0.0


def _broker(value: Any) -> str:
    text = str(getattr(value, "value", value) or "").lower().strip().split(":", 1)[0]
    compact = text.replace("_", "").replace("-", "").replace(" ", "")
    for name in ("coinbase", "kraken", "okx", "alpaca", "binance"):
        if name in compact:
            return name
    return text


def _authority() -> Any:
    for name in ("bot.capital_authority", "capital_authority"):
        try:
            module = sys.modules.get(name) or __import__(name, fromlist=["*"])
            getter = getattr(module, "get_capital_authority", None)
            if callable(getter):
                return getter()
        except Exception:
            pass
    return None


def _registered_count() -> int:
    authority = _authority()
    if authority is None:
        return 0
    for attr in ("registered_broker_count", "valid_broker_count"):
        count = int(_num(getattr(authority, attr, 0)))
        if count:
            return count
    return 0


def _broker_equity(name: str) -> float:
    authority = _authority()
    reader = getattr(authority, "get_per_broker", None) if authority is not None else None
    if callable(reader):
        for key in (name, name.upper()):
            try:
                value = _num(reader(key))
                if value > 0:
                    return value
            except Exception:
                pass
    return 0.0


def _position_broker(position: Any) -> str:
    if not isinstance(position, dict):
        return ""
    for key in ("broker", "broker_name", "exchange", "venue", "selected_broker", "execution_broker", "source_broker"):
        name = _broker(position.get(key))
        if name:
            return name
    source = str(position.get("position_source") or "").lower()
    for name in ("coinbase", "kraken", "okx", "alpaca", "binance"):
        if name in source:
            return name
    return ""


def _scope_positions(positions: Any, broker_name: str) -> list[Any]:
    raw = list(positions or [])
    include_unscoped = _truthy("NIJA_POSITION_CAP_INCLUDE_UNSCOPED", "false") or _registered_count() <= 1
    return [
        position
        for position in raw
        if _position_broker(position) == broker_name
        or (not _position_broker(position) and include_unscoped)
    ]


def _patch(module: ModuleType) -> bool:
    cls = getattr(module, "ExecutionLayerHardening", None)
    if not isinstance(cls, type):
        return False
    changed = False
    original_validate = getattr(cls, "validate_order_hardening", None)
    if callable(original_validate) and not getattr(original_validate, _VALIDATE, False):
        @wraps(original_validate)
        def validate(self: Any, symbol: str, side: str, position_size_usd: float, balance: float,
                     current_positions: Any, user_id: Any = None, force_liquidate: bool = False):
            broker_name = _broker(getattr(self, "broker_type", "")) or "coinbase"
            raw = list(current_positions or [])
            scoped = _scope_positions(raw, broker_name)
            cash = _num(balance)
            equity = _broker_equity(broker_name)
            tier_balance = max(cash, equity)
            result = original_validate(
                self,
                symbol=symbol,
                side=side,
                position_size_usd=position_size_usd,
                balance=tier_balance,
                current_positions=scoped,
                user_id=user_id,
                force_liquidate=force_liquidate,
            )
            try:
                passed, reason, details = result
                if isinstance(details, dict):
                    details.update({
                        "broker": broker_name,
                        "raw_position_count": len(raw),
                        "scoped_position_count": len(scoped),
                        "input_cash_balance": cash,
                        "broker_equity_for_tier": equity,
                        "effective_tier_balance": tier_balance,
                    })
                if len(raw) != len(scoped) or tier_balance != cash:
                    logger.warning(
                        "BROKER_SCOPED_HARDENING_APPLIED marker=%s broker=%s positions=%s->%s balance=$%.2f->$%.2f",
                        _MARKER, broker_name, len(raw), len(scoped), cash, tier_balance,
                    )
                return passed, reason, details
            except Exception:
                return result

        setattr(validate, _VALIDATE, True)
        setattr(cls, "validate_order_hardening", validate)
        changed = True

    original_getter = getattr(module, "get_execution_layer_hardening", None)
    if callable(original_getter) and not getattr(original_getter, _GETTER, False):
        instances: dict[tuple[Any, ...], Any] = {}
        lock = threading.Lock()

        @wraps(original_getter)
        def getter(broker_type: str = "coinbase", enable_position_cap: bool = True,
                   enable_minimum_size: bool = True, enable_average_monitor: bool = True,
                   enable_dust_prevention: bool = True):
            broker_name = _broker(broker_type) or "coinbase"
            key = (broker_name, enable_position_cap, enable_minimum_size, enable_average_monitor, enable_dust_prevention)
            with lock:
                if key not in instances:
                    instances[key] = cls(
                        broker_type=broker_name,
                        enable_position_cap=enable_position_cap,
                        enable_minimum_size=enable_minimum_size,
                        enable_average_monitor=enable_average_monitor,
                        enable_dust_prevention=enable_dust_prevention,
                    )
                module._hardening_instance = instances[key]
                module._hardening_instances_by_broker = instances
                return instances[key]

        setattr(getter, _GETTER, True)
        setattr(module, "get_execution_layer_hardening", getter)
        changed = True
    if changed:
        logger.warning("BROKER_SCOPED_HARDENING_PATCHED marker=%s module=%s", _MARKER, module.__name__)
    return changed


def _patch_loaded() -> None:
    for name in ("bot.execution_layer_hardening", "execution_layer_hardening"):
        module = sys.modules.get(name)
        if isinstance(module, ModuleType):
            _patch(module)


def install_import_hook() -> None:
    os.environ.setdefault("NIJA_POSITION_CAP_INCLUDE_UNSCOPED", "false")
    _patch_loaded()
    if getattr(builtins, _HOOK, False):
        return
    original_import = builtins.__import__

    def importing(name: str, globals=None, locals=None, fromlist=(), level: int = 0):
        module = original_import(name, globals, locals, fromlist, level)
        if "execution_layer_hardening" in str(name):
            _patch_loaded()
        return module

    builtins.__import__ = importing
    setattr(builtins, _HOOK, True)
    logger.warning("BROKER_SCOPED_HARDENING_INSTALL_COMPLETE marker=%s", _MARKER)


def install() -> None:
    install_import_hook()
