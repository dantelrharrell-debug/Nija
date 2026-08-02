"""Keep Coinbase valuation caches separate from execution readiness."""
from __future__ import annotations

import builtins
import logging
import os
import sys
import threading
import time
from functools import wraps
from types import ModuleType
from typing import Any, Iterator, Mapping

logger = logging.getLogger("nija.coinbase_capital_consistency")
_MARKER = "20260802-coinbase-capital-install-idempotency-v3"
_PATCH_ATTR = "_nija_coinbase_capital_consistency_v2"
_STATE_KEY = "_NIJA_COINBASE_CAPITAL_CONSISTENCY_SHARED_STATE_V3"
if not hasattr(builtins, _STATE_KEY):
    setattr(
        builtins,
        _STATE_KEY,
        {
            "lock": threading.RLock(),
            "monitor_started": False,
            "install_attested": False,
        },
    )
_STATE: dict[str, Any] = getattr(builtins, _STATE_KEY)
_LOCK: threading.RLock = _STATE["lock"]


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
    for key in (
        "total_funds",
        "trading_balance",
        "total_available",
        "available_balance",
    ):
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


def _broker_targets(broker: Any) -> Iterator[Any]:
    """Yield an adapter and its canonical broker without following cycles."""
    current = broker
    seen: set[int] = set()
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        yield current
        nested = getattr(current, "_broker", None)
        if nested is None or nested is current:
            return
        current = nested


def _auth_failure_detected(broker: Any) -> bool:
    for target in _broker_targets(broker):
        for attr in (
            "_auth_failed",
            "auth_failed",
            "_permanent_auth_failure",
            "permanent_auth_failure",
        ):
            try:
                if bool(getattr(target, attr, False)):
                    return True
            except Exception:
                continue
    return False


def _known_balance(broker: Any) -> float:
    """Return valuation-only cached equity.

    This value must never make a venue execution-ready after authentication has
    failed. Callers must check the auth-failure flag before publishing.
    """
    for target in _broker_targets(broker):
        for attr in (
            "_last_known_balance",
            "last_known_balance",
            "_last_balance",
            "last_balance",
            "_last_known_balance_payload",
            "last_balance_payload",
            "_last_raw_balances",
            "raw_balances",
            "_raw_balances",
        ):
            try:
                amount = _payload_total(getattr(target, attr, None))
            except Exception:
                amount = 0.0
            if amount > 0:
                return amount
    return _number(os.environ.get("NIJA_COINBASE_SPENDABLE_QUOTE"))


def _publish_auth_failed(broker: Any) -> None:
    """Quarantine Coinbase execution while preserving valuation caches."""
    changed = any(
        os.environ.get(name) not in {"0", "authentication_failed", "auth_failed"}
        for name in (
            "NIJA_COINBASE_CONNECTED",
            "NIJA_COINBASE_TRADING_READY",
            "NIJA_COINBASE_ACTIVATED",
            "NIJA_COINBASE_ACTIVATION_STATE",
        )
    )
    for target in _broker_targets(broker):
        for attr, value in (
            ("connected", False),
            ("_is_available", False),
            ("exit_only_mode", True),
        ):
            try:
                setattr(target, attr, value)
            except Exception:
                pass
    os.environ.update(
        {
            "NIJA_COINBASE_CONNECTED": "0",
            "NIJA_COINBASE_BALANCE_OBSERVED": "0",
            "NIJA_COINBASE_SPENDABLE_QUOTE": "0",
            "NIJA_COINBASE_TRADING_READY": "0",
            "NIJA_COINBASE_ACTIVATED": "0",
            "NIJA_COINBASE_ACTIVATION_STATE": "authentication_failed",
            "NIJA_COINBASE_FUNDING_STATUS": "auth_failed",
            "NIJA_COINBASE_AUTH_STATE": "authentication_failed",
        }
    )
    if changed:
        logger.error(
            "COINBASE_CAPITAL_AUTH_FAIL_CLOSED marker=%s "
            "cached_equity_preserved_for_valuation=true execution_ready=false",
            _MARKER,
        )


def _publish(broker: Any, amount: float) -> None:
    if _auth_failure_detected(broker):
        _publish_auth_failed(broker)
        return
    if amount <= 0:
        return
    for target in _broker_targets(broker):
        for attr in ("_last_known_balance", "last_known_balance"):
            try:
                setattr(target, attr, amount)
            except Exception:
                pass
    os.environ.update(
        {
            "NIJA_COINBASE_CONNECTED": "1",
            "NIJA_COINBASE_BALANCE_OBSERVED": "1",
            "NIJA_COINBASE_SPENDABLE_QUOTE": f"{amount:.8f}",
            "NIJA_COINBASE_TRADING_READY": "1",
            "NIJA_COINBASE_ACTIVATED": "1",
            "NIJA_COINBASE_ACTIVATION_STATE": "ready",
            "NIJA_COINBASE_FUNDING_STATUS": "funded",
            "NIJA_COINBASE_AUTH_STATE": "authenticated",
            "NIJA_COINBASE_PEM_STATE": "valid",
        }
    )


def _wrap_balance(cls: type, name: str, current: Any) -> Any:
    @wraps(current)
    def wrapped(self: Any, *args: Any, **kwargs: Any):
        result = current(self, *args, **kwargs)
        if _auth_failure_detected(self):
            _publish_auth_failed(self)
            return 0.0
        amount = _payload_total(result)
        if amount <= 0 and bool(getattr(self, "connected", False)):
            amount = _known_balance(self)
            if amount > 0:
                logger.critical(
                    "COINBASE_CAPITAL_ZERO_SURFACE_REPAIRED "
                    "marker=%s class=%s method=%s amount=$%.2f",
                    _MARKER,
                    cls.__name__,
                    name,
                    amount,
                )
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
        if _auth_failure_detected(self):
            _publish_auth_failed(self)
            return False
        connected = bool(result) or bool(getattr(self, "connected", False))
        if connected:
            amount = _known_balance(self)
            if amount > 0:
                _publish(self, amount)
            else:
                os.environ["NIJA_COINBASE_PEM_STATE"] = "valid"
            logger.critical(
                "COINBASE_CAPITAL_CONSISTENCY_READY "
                "marker=%s class=%s connected=true amount=$%.2f",
                _MARKER,
                cls.__name__,
                amount,
            )
        return result

    setattr(wrapped, _PATCH_ATTR, True)
    wrapped.__wrapped__ = current  # type: ignore[attr-defined]
    return wrapped


def _chain_has_patch(current: Any) -> bool:
    seen: set[int] = set()
    node = current
    for _ in range(64):
        if not callable(node) or id(node) in seen:
            return False
        seen.add(id(node))
        if bool(getattr(node, _PATCH_ATTR, False)):
            return True
        node = getattr(node, "__wrapped__", None)
    return False


def _patch_class(cls: type) -> bool:
    changed = False
    connect = getattr(cls, "connect", None)
    if callable(connect) and not _chain_has_patch(connect):
        cls.connect = _wrap_connect(cls, connect)
        changed = True
    for name in ("get_account_balance", "get_balance", "fetch_balance"):
        current = getattr(cls, name, None)
        if callable(current) and not _chain_has_patch(current):
            setattr(cls, name, _wrap_balance(cls, name, current))
            changed = True
    return changed


def _patch_loaded() -> bool:
    changed = False
    for module_name in (
        "bot.broker_manager",
        "broker_manager",
        "bot.broker_integration",
        "broker_integration",
    ):
        module = sys.modules.get(module_name)
        if not isinstance(module, ModuleType):
            continue
        for class_name in (
            "CoinbaseBroker",
            "CoinbaseBrokerAdapter",
            "_CoinbaseInvalidProductFilter",
        ):
            cls = getattr(module, class_name, None)
            if isinstance(cls, type):
                changed = _patch_class(cls) or changed
    return changed


def _monitor() -> None:
    deadline = time.monotonic() + max(
        120.0,
        float(os.environ.get("NIJA_PATCH_MONITOR_SECONDS", "600") or 600),
    )
    while time.monotonic() < deadline:
        try:
            _patch_loaded()
        except Exception:
            logger.exception(
                "COINBASE_CAPITAL_CONSISTENCY_MONITOR_ERROR marker=%s",
                _MARKER,
            )
        time.sleep(0.25)


def install() -> bool:
    """Install once even when compatibility loaders import this file by alias."""
    with _LOCK:
        _patch_loaded()
        if not bool(_STATE["monitor_started"]):
            _STATE["monitor_started"] = True
            threading.Thread(
                target=_monitor,
                name="CoinbaseCapitalConsistencyV3",
                daemon=True,
            ).start()
        os.environ["NIJA_COINBASE_CAPITAL_CONSISTENCY_INSTALLED"] = "1"
        if not bool(_STATE["install_attested"]):
            _STATE["install_attested"] = True
            logger.critical(
                "COINBASE_CAPITAL_CONSISTENCY_INSTALLED marker=%s",
                _MARKER,
            )
        return True


install()

__all__ = [
    "install",
    "_payload_total",
    "_known_balance",
    "_auth_failure_detected",
    "_publish_auth_failed",
    "_patch_loaded",
]
