"""Terminate recursive Coinbase connect wrapper chains and preserve fail-closed auth.

The guard unwraps acyclic ``__wrapped__`` layers, prevents same-thread connect re-entry,
and performs one authenticated private-account probe before publishing readiness.
"""
from __future__ import annotations

import logging
import os
import sys
import threading
import time
from functools import wraps
from types import ModuleType
from typing import Any

logger = logging.getLogger("nija.coinbase_connect_recursion_terminal")
_MARKER = "20260720-coinbase-connect-recursion-terminal-v2"
_PATCH_ATTR = "_nija_coinbase_connect_recursion_terminal_v2"
_LOCK = threading.RLock()
_LOCAL = threading.local()
_STARTED = False
_LAST_FAILURE = 0.0


def _coinbase_class(cls: type) -> bool:
    return "coinbase" in cls.__name__.lower()


def _unwrap(func: Any) -> tuple[Any, int, bool]:
    current = func
    seen: set[int] = set()
    depth = 0
    while callable(current):
        ident = id(current)
        if ident in seen:
            return current, depth, True
        seen.add(ident)
        wrapped = getattr(current, "__wrapped__", None)
        if not callable(wrapped):
            return current, depth, False
        current = wrapped
        depth += 1
        if depth >= 256:
            return current, depth, True
    return current, depth, False


def _private_probe(broker: Any) -> tuple[bool, str]:
    targets = [broker]
    for attr in ("client", "api_client", "rest_client", "coinbase_client", "_client", "_api_client"):
        try:
            value = getattr(broker, attr, None)
        except Exception:
            value = None
        if value is not None and value not in targets:
            targets.append(value)
    errors: list[str] = []
    for target in targets:
        for name in ("get_accounts", "list_accounts", "fetch_accounts"):
            method = getattr(target, name, None)
            if not callable(method):
                continue
            try:
                payload = method()
            except RecursionError:
                errors.append(f"{type(target).__name__}.{name}:RecursionError")
                continue
            except TypeError:
                continue
            except Exception as exc:
                errors.append(f"{type(target).__name__}.{name}:{type(exc).__name__}:{str(exc)[:100]}")
                continue
            if payload is not None and payload is not False:
                return True, f"{type(target).__name__}.{name}"
            errors.append(f"{type(target).__name__}.{name}:falsey")
    return False, ";".join(errors[-4:]) or "private_client_unavailable"


def _publish_failure(detail: str) -> None:
    global _LAST_FAILURE
    os.environ["NIJA_COINBASE_CONNECTED"] = "0"
    os.environ["NIJA_COINBASE_TRADING_READY"] = "0"
    os.environ["NIJA_COINBASE_ACTIVATION_STATE"] = "authentication_failed"
    os.environ["NIJA_COINBASE_CONNECT_RECURSION_BLOCKED"] = "1"
    now = time.monotonic()
    if now - _LAST_FAILURE >= 60.0:
        _LAST_FAILURE = now
        logger.error("COINBASE_CONNECT_FAIL_CLOSED marker=%s detail=%s", _MARKER, detail[:400])


def _publish_success(broker: Any, source: str) -> None:
    try:
        setattr(broker, "connected", True)
    except Exception:
        pass
    os.environ["NIJA_COINBASE_CONNECTED"] = "1"
    os.environ["NIJA_COINBASE_ACTIVATION_STATE"] = "connected"
    os.environ["NIJA_COINBASE_CONNECT_RECURSION_BLOCKED"] = "0"
    logger.critical("COINBASE_CONNECT_RECURSION_RECOVERED marker=%s source=%s", _MARKER, source)


def _patch_class(cls: type) -> bool:
    current = getattr(cls, "connect", None)
    if not callable(current) or getattr(current, _PATCH_ATTR, False):
        return bool(callable(current) and getattr(current, _PATCH_ATTR, False))
    base, depth, cycle = _unwrap(current)

    @wraps(current)
    def connect(self: Any, *args: Any, **kwargs: Any):
        if getattr(_LOCAL, "active", False):
            ok, source = _private_probe(self)
            if ok:
                _publish_success(self, source)
                return True
            _publish_failure("same_thread_reentry:" + source)
            return False
        _LOCAL.active = True
        try:
            target = base if cycle and callable(base) else current
            try:
                result = target(self, *args, **kwargs)
            except RecursionError:
                ok, source = _private_probe(self)
                if ok:
                    _publish_success(self, source)
                    return True
                _publish_failure("RecursionError:" + source)
                return False
            if bool(result) or bool(getattr(self, "connected", False)):
                return result
            ok, source = _private_probe(self)
            if ok:
                _publish_success(self, source)
                return True
            _publish_failure(source)
            return result
        finally:
            _LOCAL.active = False

    setattr(connect, _PATCH_ATTR, True)
    setattr(connect, "__wrapped__", base if callable(base) else current)
    cls.connect = connect
    logger.critical(
        "COINBASE_CONNECT_RECURSION_TERMINAL_PATCHED marker=%s module=%s class=%s removed_layers=%d cycle=%s",
        _MARKER, cls.__module__, cls.__name__, depth, str(cycle).lower(),
    )
    return True


def _patch_loaded() -> bool:
    changed = False
    for name in ("bot.broker_manager", "broker_manager", "bot.broker_integration", "broker_integration"):
        module = sys.modules.get(name)
        if not isinstance(module, ModuleType):
            continue
        for value in vars(module).values():
            if isinstance(value, type) and _coinbase_class(value):
                changed = _patch_class(value) or changed
    return changed


def _watchdog() -> None:
    while True:
        try:
            _patch_loaded()
        except Exception as exc:
            logger.debug("COINBASE_CONNECT_TERMINAL_RETRY marker=%s error=%s", _MARKER, exc)
        time.sleep(1.0)


def install() -> bool:
    global _STARTED
    with _LOCK:
        _patch_loaded()
        if not _STARTED:
            _STARTED = True
            threading.Thread(target=_watchdog, name="CoinbaseConnectRecursionTerminal", daemon=True).start()
        os.environ["NIJA_COINBASE_CONNECT_RECURSION_TERMINAL_INSTALLED"] = "1"
        logger.critical("COINBASE_CONNECT_RECURSION_TERMINAL_INSTALLED marker=%s", _MARKER)
        return True


install()

__all__ = ["install", "_unwrap", "_private_probe"]
