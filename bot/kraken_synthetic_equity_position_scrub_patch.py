"""Remove synthetic accounting metadata before Kraken position classification.

The canonical balance cache may contain fields such as ``canonical_equity`` and
``total_funds``.  They are accounting metadata, not exchange assets.  This patch
scrubs those keys from cached balance payloads *before* any Kraken ``get_positions``
or balance wrapper can classify them, and filters any legacy synthetic rows from
returned position snapshots.
"""
from __future__ import annotations

import builtins
import importlib
import logging
import os
import sys
import threading
from functools import wraps
from types import ModuleType
from typing import Any, Mapping

logger = logging.getLogger("nija.kraken_synthetic_equity_scrub")
_MARKER = "20260714-kraken-synthetic-equity-scrub-v1"
_PATCH_ATTR = "_nija_kraken_synthetic_equity_scrub_v1"
_LOCK = threading.RLock()
_ORIGINAL_IMPORT = None
_PATCHED: set[tuple[str, int]] = set()

_EXPLICIT = {
    "CANONICAL_EQUITY", "CANONICAL_TOTAL", "TOTAL_FUNDS", "TOTAL_BALANCE",
    "TOTAL_EQUITY", "EQUITY", "PORTFOLIO_VALUE", "ACCOUNT_EQUITY",
    "HELD_EXCLUDED_FROM_EQUITY_SUM", "CRYPTO_USD", "NON_USD_USD",
    "USD_HELD", "USDT_HELD", "USDC_HELD", "TOTAL_HELD",
}
_PREFIXES = (
    "CANONICAL_", "TOTAL_", "AVAILABLE_", "BROKER_", "CAPITAL_",
    "UPDATED_", "OPEN_EXPOSURE_", "RESERVE_", "HELD_EXCLUDED_", "LAST_",
)
_SUFFIXES = (
    "_EQUITY", "_BALANCE", "_FUNDS", "_CAPITAL", "_EXPOSURE",
    "_VALUE", "_COUNT", "_COMPLETENESS", "_UPDATED",
)
_CACHE_ATTRS = (
    "_last_raw_balances", "last_raw_balances", "_raw_balances", "raw_balances",
    "_balance_payload", "balance_payload", "_balance_cache", "balance_cache",
)


def _metadata_name(value: Any) -> bool:
    name = str(value or "").strip().upper().replace("-USD", "")
    if not name:
        return True
    if name in _EXPLICIT:
        return True
    if "_" not in name:
        return False
    return name.startswith(_PREFIXES) or name.endswith(_SUFFIXES)


def _scrub_mapping(payload: Mapping[str, Any]) -> tuple[dict[str, Any], list[str]]:
    cleaned: dict[str, Any] = {}
    removed: list[str] = []
    for key, value in payload.items():
        if _metadata_name(key):
            removed.append(str(key))
            continue
        if isinstance(value, Mapping):
            nested, nested_removed = _scrub_mapping(value)
            cleaned[key] = nested
            removed.extend(f"{key}.{item}" for item in nested_removed)
        else:
            cleaned[key] = value
    return cleaned, removed


def _scrub_instance(instance: Any) -> list[str]:
    removed: list[str] = []
    for attr in _CACHE_ATTRS:
        payload = getattr(instance, attr, None)
        if not isinstance(payload, Mapping):
            continue
        cleaned, fields = _scrub_mapping(payload)
        if fields:
            try:
                setattr(instance, attr, cleaned)
                removed.extend(fields)
            except Exception:
                continue
    if removed:
        logger.warning(
            "KRAKEN_SYNTHETIC_EQUITY_CACHE_SCRUBBED marker=%s fields=%s fake_positions_prevented=true",
            _MARKER,
            sorted(set(removed)),
        )
    return removed


def _filter_rows(rows: Any) -> Any:
    if not isinstance(rows, list):
        return rows
    kept = []
    removed = []
    for row in rows:
        if not isinstance(row, Mapping):
            kept.append(row)
            continue
        symbol = row.get("symbol") or row.get("asset") or row.get("currency")
        if _metadata_name(symbol):
            removed.append(str(symbol))
            continue
        kept.append(row)
    if removed:
        logger.warning(
            "KRAKEN_SYNTHETIC_POSITION_REMOVED marker=%s symbols=%s exchange_position=false",
            _MARKER,
            sorted(set(removed)),
        )
    return kept


def _is_kraken_class(cls: type) -> bool:
    return "kraken" in cls.__name__.lower()


def _patch_class(cls: type) -> bool:
    key = (f"{cls.__module__}.{cls.__name__}", id(cls))
    if key in _PATCHED:
        return True
    if not _is_kraken_class(cls):
        return False

    changed = False
    current_positions = getattr(cls, "get_positions", None)
    if callable(current_positions) and not getattr(current_positions, _PATCH_ATTR, False):
        @wraps(current_positions)
        def get_positions(self: Any, *args: Any, **kwargs: Any):
            _scrub_instance(self)
            return _filter_rows(current_positions(self, *args, **kwargs))

        setattr(get_positions, _PATCH_ATTR, True)
        setattr(get_positions, "__wrapped__", current_positions)
        cls.get_positions = get_positions
        changed = True

    current_balance = getattr(cls, "get_account_balance", None)
    if callable(current_balance) and not getattr(current_balance, _PATCH_ATTR, False):
        @wraps(current_balance)
        def get_account_balance(self: Any, *args: Any, **kwargs: Any):
            _scrub_instance(self)
            result = current_balance(self, *args, **kwargs)
            _scrub_instance(self)
            return result

        setattr(get_account_balance, _PATCH_ATTR, True)
        setattr(get_account_balance, "__wrapped__", current_balance)
        cls.get_account_balance = get_account_balance
        changed = True

    if changed:
        _PATCHED.add(key)
        logger.critical(
            "KRAKEN_SYNTHETIC_EQUITY_POSITION_SCRUB_INSTALLED marker=%s class=%s",
            _MARKER,
            cls.__name__,
        )
    return changed


def _patch_module(module: ModuleType) -> bool:
    changed = False
    for name in dir(module):
        try:
            obj = getattr(module, name)
        except Exception:
            continue
        if isinstance(obj, type):
            changed = _patch_class(obj) or changed
    return changed


def _patch_loaded() -> bool:
    changed = False
    for module in tuple(sys.modules.values()):
        if isinstance(module, ModuleType):
            try:
                changed = _patch_module(module) or changed
            except Exception:
                continue
    for name in ("bot.broker_manager", "broker_manager", "bot.kraken_broker", "kraken_broker"):
        try:
            module = importlib.import_module(name)
        except Exception:
            continue
        changed = _patch_module(module) or changed
    return changed


def install_import_hook() -> None:
    global _ORIGINAL_IMPORT
    _patch_loaded()
    with _LOCK:
        if _ORIGINAL_IMPORT is None:
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
    os.environ["NIJA_KRAKEN_SYNTHETIC_EQUITY_SCRUB_INSTALLED"] = "1"
    logger.critical("KRAKEN_SYNTHETIC_EQUITY_SCRUB_RUNTIME_INSTALLED marker=%s", _MARKER)


def install() -> None:
    install_import_hook()


__all__ = [
    "install", "install_import_hook", "_metadata_name", "_scrub_mapping",
    "_scrub_instance", "_filter_rows", "_patch_class",
]
