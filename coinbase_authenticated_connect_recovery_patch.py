"""Recover false-negative Coinbase connect results with an authenticated account probe.

The patch never marks Coinbase connected from credential shape, public products, cached
balances, or environment flags alone.  A failed/falsey connect is upgraded only when a
private account endpoint succeeds on the broker or its authenticated SDK client.
"""
from __future__ import annotations

import importlib
import logging
import os
import sys
import threading
import time
from functools import wraps
from types import ModuleType
from typing import Any, Mapping, Sequence

logger = logging.getLogger("nija.coinbase_authenticated_connect_recovery")
_MARKER = "20260720-coinbase-authenticated-connect-v1"
_PATCH_ATTR = "_nija_coinbase_authenticated_connect_v1"
_LOCK = threading.RLock()
_STARTED = False
_LAST_FAILURE: dict[str, float] = {}


def _is_coinbase_class(cls: type) -> bool:
    return "coinbase" in cls.__name__.lower()


def _clients(broker: Any) -> list[Any]:
    found: list[Any] = []
    for attr in ("client", "api_client", "rest_client", "coinbase_client", "_client", "_api_client"):
        try:
            value = getattr(broker, attr, None)
        except Exception:
            value = None
        if value is not None and value not in found:
            found.append(value)
    found.insert(0, broker)
    return found


def _payload_success(payload: Any) -> bool:
    # A successful private endpoint may legitimately return an empty account list.
    if payload is None or payload is False:
        return False
    if isinstance(payload, Mapping):
        error = payload.get("error") or payload.get("errors")
        if error:
            return False
        return True
    if isinstance(payload, Sequence) and not isinstance(payload, (str, bytes, bytearray)):
        return True
    # Coinbase SDK response objects are valid even when their accounts collection is empty.
    return hasattr(payload, "accounts") or hasattr(payload, "to_dict") or bool(payload)


def _authenticated_probe(broker: Any) -> tuple[bool, str]:
    errors: list[str] = []
    for target in _clients(broker):
        for method_name in ("get_accounts", "list_accounts", "fetch_accounts"):
            method = getattr(target, method_name, None)
            if not callable(method):
                continue
            try:
                payload = method()
            except TypeError:
                continue
            except Exception as exc:
                errors.append(f"{type(target).__name__}.{method_name}:{type(exc).__name__}:{str(exc)[:100]}")
                continue
            if _payload_success(payload):
                return True, f"{type(target).__name__}.{method_name}"
            errors.append(f"{type(target).__name__}.{method_name}:falsey_payload")
    return False, ";".join(errors[-3:]) or "private_account_method_unavailable"


def _measure_spendable(broker: Any) -> float:
    try:
        helper = importlib.import_module("bot.coinbase_funding_readiness_repair_patch")
        measure = getattr(helper, "_measure_spendable", None)
        if callable(measure):
            return max(0.0, float(measure(broker) or 0.0))
    except Exception:
        pass
    return 0.0


def _publish_connected(broker: Any, source: str) -> None:
    try:
        setattr(broker, "connected", True)
    except Exception:
        pass
    spendable = _measure_spendable(broker)
    os.environ["NIJA_COINBASE_CONNECTED"] = "1"
    os.environ["NIJA_COINBASE_BALANCE_OBSERVED"] = "1"
    os.environ["NIJA_COINBASE_SPENDABLE_QUOTE"] = f"{spendable:.8f}"
    os.environ["NIJA_COINBASE_FUNDING_STATUS"] = "funded" if spendable > 0 else "observed_zero"
    os.environ["NIJA_COINBASE_TRADING_READY"] = "1" if spendable > 0 else "0"
    os.environ["NIJA_COINBASE_ACTIVATED"] = "1"
    os.environ["NIJA_COINBASE_ACTIVATION_STATE"] = "ready" if spendable > 0 else "connected_unfunded"
    logger.critical(
        "COINBASE_AUTHENTICATED_CONNECT_RECOVERED marker=%s source=%s spendable=$%.2f",
        _MARKER, source, spendable,
    )


def _log_failure_once(cls: type, detail: str) -> None:
    key = cls.__module__ + "." + cls.__name__ + ":" + detail
    now = time.monotonic()
    if now - _LAST_FAILURE.get(key, 0.0) < 60.0:
        return
    _LAST_FAILURE[key] = now
    logger.error(
        "COINBASE_AUTHENTICATED_CONNECT_FAILED marker=%s class=%s detail=%s",
        _MARKER, cls.__name__, detail[:300],
    )


def _patch_class(cls: type) -> bool:
    if not _is_coinbase_class(cls):
        return False
    current = getattr(cls, "connect", None)
    if not callable(current) or getattr(current, _PATCH_ATTR, False):
        return bool(callable(current) and getattr(current, _PATCH_ATTR, False))

    @wraps(current)
    def connect(self: Any, *args: Any, **kwargs: Any):
        result = current(self, *args, **kwargs)
        if bool(result) or bool(getattr(self, "connected", False)):
            return result
        authenticated, detail = _authenticated_probe(self)
        if authenticated:
            _publish_connected(self, detail)
            return True
        os.environ["NIJA_COINBASE_CONNECTED"] = "0"
        os.environ["NIJA_COINBASE_ACTIVATION_STATE"] = "authentication_failed"
        _log_failure_once(cls, detail)
        return result

    setattr(connect, _PATCH_ATTR, True)
    connect.__wrapped__ = current  # type: ignore[attr-defined]
    setattr(cls, "connect", connect)
    logger.warning(
        "COINBASE_AUTHENTICATED_CONNECT_SURFACE_PATCHED marker=%s module=%s class=%s",
        _MARKER, cls.__module__, cls.__name__,
    )
    return True


def _patch_module(module: ModuleType) -> bool:
    changed = False
    for value in vars(module).values():
        if isinstance(value, type) and _is_coinbase_class(value):
            changed = _patch_class(value) or changed
    return changed


def _patch_loaded() -> bool:
    changed = False
    for name, module in list(sys.modules.items()):
        if isinstance(module, ModuleType) and name in {
            "bot.broker_manager", "broker_manager", "bot.broker_integration", "broker_integration"
        }:
            changed = _patch_module(module) or changed
    return changed


def _watchdog() -> None:
    deadline = time.monotonic() + 240.0
    while time.monotonic() < deadline:
        try:
            _patch_loaded()
        except Exception as exc:
            logger.debug("COINBASE_AUTHENTICATED_CONNECT_RETRY marker=%s error=%s", _MARKER, exc)
        time.sleep(0.25)


def install() -> bool:
    global _STARTED
    with _LOCK:
        _patch_loaded()
        if not _STARTED:
            _STARTED = True
            threading.Thread(target=_watchdog, name="CoinbaseAuthenticatedConnectRecovery", daemon=True).start()
        os.environ["NIJA_COINBASE_AUTHENTICATED_CONNECT_RECOVERY_INSTALLED"] = "1"
        logger.critical("COINBASE_AUTHENTICATED_CONNECT_RECOVERY_INSTALLED marker=%s", _MARKER)
        return True


__all__ = ["install", "_authenticated_probe", "_patch_class"]
