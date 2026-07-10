from __future__ import annotations

import builtins
import logging
import sys
import time
from functools import wraps
from types import ModuleType
from typing import Any

logger = logging.getLogger("nija.disconnected_coinbase_balance_guard")
_MARKER = "20260709av"
_HOOK = "_NIJA_DISCONNECTED_COINBASE_BALANCE_GUARD_HOOK_20260709AV"
_DETAIL_ATTR = "_nija_disconnected_coinbase_detail_guard_20260709av"
_PUBLIC_ATTR = "_nija_disconnected_coinbase_public_guard_20260709av"
_LAST_LOG: dict[int, float] = {}
_BROKER_MODULES = {"bot.broker_manager", "broker_manager"}


def _is_disconnected(instance: Any) -> bool:
    # This guard is only installed on the concrete CoinbaseBroker implementation,
    # whose connection contract includes both ``client`` and ``connected``.
    client = getattr(instance, "client", None)
    if client is None:
        return True
    connected = getattr(instance, "connected", None)
    return connected is False


def _zero_detail() -> dict[str, Any]:
    return {
        "usdc": 0.0,
        "usd": 0.0,
        "trading_balance": 0.0,
        "usd_held": 0.0,
        "usdc_held": 0.0,
        "total_held": 0.0,
        "total_funds": 0.0,
        "crypto": {},
        "consumer_usd": 0.0,
        "consumer_usdc": 0.0,
    }


def _log_once(instance: Any, surface: str) -> None:
    now = time.monotonic()
    key = id(instance)
    if now - _LAST_LOG.get(key, 0.0) < 300.0:
        return
    _LAST_LOG[key] = now
    logger.warning(
        "COINBASE_BALANCE_DISCONNECTED_SKIPPED marker=%s surface=%s client_present=%s connected=%s",
        _MARKER,
        surface,
        getattr(instance, "client", None) is not None,
        getattr(instance, "connected", None),
    )


def _patch_class(cls: type) -> bool:
    # CoinbaseBrokerAdapter exposes a different balance contract (dict return and
    # no ``client`` attribute). Requiring the concrete broker's private detailed
    # reader prevents this patch from ever changing adapter behavior.
    original_detail = getattr(cls, "_get_account_balance_detailed", None)
    if not callable(original_detail):
        return False

    changed = False
    if not getattr(original_detail, _DETAIL_ATTR, False):
        @wraps(original_detail)
        def _detail(self: Any, *args: Any, **kwargs: Any) -> Any:
            if not _is_disconnected(self):
                return original_detail(self, *args, **kwargs)
            result = _zero_detail()
            try:
                self._balance_cache = result
                self._balance_cache_time = time.time()
                self._last_known_balance = 0.0
            except Exception:
                pass
            _log_once(self, "_get_account_balance_detailed")
            return result

        setattr(_detail, _DETAIL_ATTR, True)
        setattr(cls, "_get_account_balance_detailed", _detail)
        changed = True

    original_public = getattr(cls, "get_account_balance", None)
    if callable(original_public) and not getattr(original_public, _PUBLIC_ATTR, False):
        @wraps(original_public)
        def _public(self: Any, *args: Any, **kwargs: Any) -> Any:
            if not _is_disconnected(self):
                return original_public(self, *args, **kwargs)
            try:
                self._last_known_balance = 0.0
            except Exception:
                pass
            _log_once(self, "get_account_balance")
            return 0.0

        setattr(_public, _PUBLIC_ATTR, True)
        setattr(cls, "get_account_balance", _public)
        changed = True
    return changed


def _patch_module(module: ModuleType) -> bool:
    changed = False
    for name in ("CoinbaseBroker", "CoinbaseAdvancedTradeBroker"):
        cls = getattr(module, name, None)
        if isinstance(cls, type):
            changed = _patch_class(cls) or changed
    if changed:
        logger.warning("COINBASE_BALANCE_DISCONNECTED_GUARD_PATCHED marker=%s module=%s", _MARKER, module.__name__)
    return changed


def _patch_loaded() -> bool:
    patched = False
    for name in _BROKER_MODULES:
        module = sys.modules.get(name)
        if isinstance(module, ModuleType):
            patched = _patch_module(module) or patched
    return patched


def install_import_hook() -> None:
    _patch_loaded()
    if getattr(builtins, _HOOK, False):
        return
    original_import = builtins.__import__

    def importing(name: str, globals: Any = None, locals: Any = None, fromlist: Any = (), level: int = 0):
        module = original_import(name, globals, locals, fromlist, level)
        if str(name) in _BROKER_MODULES:
            _patch_loaded()
        return module

    builtins.__import__ = importing
    setattr(builtins, _HOOK, True)
    logger.warning("COINBASE_BALANCE_DISCONNECTED_GUARD_INSTALL_COMPLETE marker=%s", _MARKER)


def install() -> None:
    install_import_hook()
