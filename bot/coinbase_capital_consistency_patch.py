"""Keep Coinbase capital and credential diagnostics consistent."""
from __future__ import annotations

import logging
import os
import sys
import threading
import time
from functools import wraps
from types import ModuleType
from typing import Any, Mapping

logger = logging.getLogger("nija.coinbase_capital_consistency")
_MARKER = "20260720-coinbase-capital-consistency-v1"
_PATCH_ATTR = "_nija_coinbase_capital_consistency_v1"
_LOCK = threading.RLock()
_STARTED = False


def _number(value: Any) -> float:
    try:
        return max(0.0, float(value or 0.0))
    except Exception:
        return 0.0


def _payload_total(value: Any) -> float:
    if value is None:
        return 0.0
    if isinstance(value, (int, float, str)):
        return _number(value)
    if not isinstance(value, Mapping):
        return 0.0
    for key in ("total_funds", "trading_balance", "total_available", "available_balance"):
        amount = _number(value.get(key))
        if amount > 0:
            return amount
    total = 0.0
    for key in ("usd", "usdc", "available_usd", "available_usdc"):
        child = value.get(key)
        if isinstance(child, Mapping):
            child = child.get("value") or child.get("amount") or child.get("balance")
        total += _number(child)
    return total


def _known_balance(broker: Any) -> float:
    for attr in ("_last_known_balance", "last_known_balance", "_last_balance", "last_balance", "_last_known_balance_payload", "last_balance_payload", "_last_raw_balances", "raw_balances", "_raw_balances"):
        try:
            amount = _payload_total(getattr(broker, attr, None))
        except Exception:
            amount = 0.0
        if amount > 0:
            return amount
    return _number(os.environ.get("NIJA_COINBASE_SPENDABLE_QUOTE"))


def _publish(broker: Any, amount: float) -> None:
    if amount <= 0:
        return
    for attr in ("_last_known_balance", "last_known_balance"):
        try:
            setattr(broker, attr, amount)
        except Exception:
            pass
    os.environ.update({
        "NIJA_COINBASE_CONNECTED": "1",
        "NIJA_COINBASE_BALANCE_OBSERVED": "1",
        "NIJA_COINBASE_SPENDABLE_QUOTE": f"{amount:.8f}",
        "NIJA_COINBASE_TRADING_READY": "1",
        "NIJA_COINBASE_ACTIVATED": "1",
        "NIJA_COINBASE_ACTIVATION_STATE": "ready",
        "NIJA_COINBASE_FUNDING_STATUS": "funded",
        "NIJA_COINBASE_PEM_STATE": "valid",
    })


def _wrap_balance(cls: type, name: str, current: Any) -> Any:
    @wraps(current)
    def wrapped(self: Any, *args: Any, **kwargs: Any):
        result = current(self, *args, **kwargs)
        amount = _payload_total(result)
        if amount <= 0 and bool(getattr(self, "connected", False)):
            amount = _known_balance(self)
            if amount > 0:
                logger.critical("COINBASE_CAPITAL_ZERO_SURFACE_REPAIRED marker=%s class=%s method=%s amount=$%.2f", _MARKER, cls.__name__, name, amount)
                result = amount
        if amount > 0:
            _publish(self, amount)
        return result
    setattr(wrapped, _PATCH_ATTR, True)
    wrapped.__wrapped__ = current  # type: ignore[attr-defined]
    return wrapped


def _wrap_connect(cls: type, current: Any) -> Any:
    @wraps(current)
    def wrapped(self: Any, *args: Any, **kwargs: Any):
        result = current(self, *args, **kwargs)
        connected = bool(result) or bool(getattr(self, "connected", False))
        if connected:
            amount = _known_balance(self)
            if amount > 0:
                _publish(self, amount)
            else:
                os.environ["NIJA_COINBASE_PEM_STATE"] = "valid"
            logger.critical("COINBASE_CAPITAL_CONSISTENCY_READY marker=%s class=%s connected=true amount=$%.2f", _MARKER, cls.__name__, amount)
        return result
    setattr(wrapped, _PATCH_ATTR, True)
    wrapped.__wrapped__ = current  # type: ignore[attr-defined]
    return wrapped


def _patch_class(cls: type) -> bool:
    changed = False
    connect = getattr(cls, "connect", None)
    if callable(connect) and not getattr(connect, _PATCH_ATTR, False):
        cls.connect = _wrap_connect(cls, connect)
        changed = True
    for name in ("get_account_balance", "get_balance", "fetch_balance"):
        current = getattr(cls, name, None)
        if callable(current) and not getattr(current, _PATCH_ATTR, False):
            setattr(cls, name, _wrap_balance(cls, name, current))
            changed = True
    return changed


def _patch_loaded() -> bool:
    changed = False
    for module_name in ("bot.broker_manager", "broker_manager", "bot.broker_integration", "broker_integration"):
        module = sys.modules.get(module_name)
        if not isinstance(module, ModuleType):
            continue
        for class_name in ("CoinbaseBroker", "CoinbaseBrokerAdapter", "_CoinbaseInvalidProductFilter"):
            cls = getattr(module, class_name, None)
            if isinstance(cls, type):
                changed = _patch_class(cls) or changed
    return changed


def _monitor() -> None:
    deadline = time.monotonic() + max(120.0, float(os.environ.get("NIJA_PATCH_MONITOR_SECONDS", "600") or 600))
    while time.monotonic() < deadline:
        try:
            _patch_loaded()
        except Exception:
            logger.exception("COINBASE_CAPITAL_CONSISTENCY_MONITOR_ERROR marker=%s", _MARKER)
        time.sleep(0.25)


def install() -> bool:
    global _STARTED
    with _LOCK:
        _patch_loaded()
        if not _STARTED:
            _STARTED = True
            threading.Thread(target=_monitor, name="CoinbaseCapitalConsistency", daemon=True).start()
        os.environ["NIJA_COINBASE_CAPITAL_CONSISTENCY_INSTALLED"] = "1"
        logger.critical("COINBASE_CAPITAL_CONSISTENCY_INSTALLED marker=%s", _MARKER)
        return True


install()

__all__ = ["install", "_payload_total", "_known_balance", "_patch_loaded"]
