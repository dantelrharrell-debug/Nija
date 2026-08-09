"""Account/broker-scoped profit lock and harvest APIs v71.

The historical ProfitLockEngine and ProfitHarvestLayer are process singletons
whose dictionaries are keyed by symbol.  That is safe only for one account per
symbol.  With multiple users/brokers, two BTC-USD positions would otherwise
share peak-profit, lock-tier and harvest-candidate state.

v71 adds explicit scoped APIs while preserving legacy methods for compatibility.
New live integrations must use ``scope_id + broker_name + symbol``.
"""
from __future__ import annotations

import builtins
import importlib
import logging
import os
import re
import sys
import threading
from functools import wraps
from types import ModuleType
from typing import Any

LOGGER = logging.getLogger("nija.account_scoped_profit_state_v71")
MARKER = "20260809-account-scoped-profit-state-v71"
_PATCH_ATTR = "_nija_account_scoped_profit_state_v71"
_LOCK = threading.RLock()


def _clean(value: Any) -> str:
    text = str(value or "").strip().lower()
    text = re.sub(r"[^a-z0-9_.:-]+", "_", text)
    return text.strip("_")


def scoped_position_key(scope_id: str, broker_name: str, symbol: str) -> str:
    scope = _clean(scope_id)
    broker = _clean(broker_name)
    pair = str(symbol or "").strip().upper().replace("/", "-").replace("_", "-")
    if not scope:
        raise ValueError("scope_id is required")
    if not broker:
        raise ValueError("broker_name is required")
    if not pair:
        raise ValueError("symbol is required")
    return f"scope={scope}|broker={broker}|symbol={pair}"


def _patch_lock_engine(module: ModuleType) -> bool:
    cls = getattr(module, "ProfitLockEngine", None)
    if not isinstance(cls, type):
        return False
    if getattr(cls, _PATCH_ATTR, False):
        return True

    def register_scoped_position(
        self: Any,
        scope_id: str,
        broker_name: str,
        symbol: str,
        side: str,
        entry_price: float,
        entry_time: Any = None,
    ) -> None:
        key = scoped_position_key(scope_id, broker_name, symbol)
        self.register_position(
            key,
            side=side,
            entry_price=entry_price,
            entry_time=entry_time,
        )
        LOGGER.info(
            "PROFIT_STATE_V71_LOCK_REGISTERED marker=%s scope=%s broker=%s symbol=%s key=%s",
            MARKER, scope_id, broker_name, symbol, key,
        )

    def update_scoped_position(
        self: Any,
        scope_id: str,
        broker_name: str,
        symbol: str,
        current_price: float,
    ) -> Any:
        key = scoped_position_key(scope_id, broker_name, symbol)
        decision = self.update_position(key, current_price=current_price)
        try:
            decision.symbol = str(symbol).strip().upper().replace("/", "-").replace("_", "-")
        except Exception:
            pass
        return decision

    def remove_scoped_position(self: Any, scope_id: str, broker_name: str, symbol: str):
        return self.remove_position(scoped_position_key(scope_id, broker_name, symbol))

    def get_scoped_lock_status(self: Any, scope_id: str, broker_name: str, symbol: str):
        status = self.get_lock_status(scoped_position_key(scope_id, broker_name, symbol))
        if isinstance(status, dict):
            status = dict(status)
            status["scope_id"] = scope_id
            status["broker_name"] = broker_name
            status["display_symbol"] = str(symbol).upper()
        return status

    cls.register_scoped_position = register_scoped_position
    cls.update_scoped_position = update_scoped_position
    cls.remove_scoped_position = remove_scoped_position
    cls.get_scoped_lock_status = get_scoped_lock_status
    setattr(cls, _PATCH_ATTR, True)
    LOGGER.critical(
        "ACCOUNT_SCOPED_PROFIT_LOCK_V71_PATCHED marker=%s module=%s",
        MARKER, module.__name__,
    )
    return True


def _patch_harvest_layer(module: ModuleType) -> bool:
    cls = getattr(module, "ProfitHarvestLayer", None)
    if not isinstance(cls, type):
        return False
    if getattr(cls, _PATCH_ATTR, False):
        return True

    def register_scoped_position(
        self: Any,
        scope_id: str,
        broker_name: str,
        symbol: str,
        side: str,
        entry_price: float,
        position_size_usd: float,
        entry_time: Any = None,
    ) -> None:
        key = scoped_position_key(scope_id, broker_name, symbol)
        self.register_position(
            key,
            side=side,
            entry_price=entry_price,
            position_size_usd=position_size_usd,
            entry_time=entry_time,
        )
        LOGGER.info(
            "PROFIT_STATE_V71_HARVEST_REGISTERED marker=%s scope=%s broker=%s symbol=%s key=%s",
            MARKER, scope_id, broker_name, symbol, key,
        )

    def process_scoped_price_update(
        self: Any,
        scope_id: str,
        broker_name: str,
        symbol: str,
        current_price: float,
    ) -> Any:
        key = scoped_position_key(scope_id, broker_name, symbol)
        decision = self.process_price_update(key, current_price=current_price)
        try:
            decision.symbol = str(symbol).strip().upper().replace("/", "-").replace("_", "-")
        except Exception:
            pass
        return decision

    def get_scoped_harvest_status(self: Any, scope_id: str, broker_name: str, symbol: str):
        status = self.get_harvest_status(scoped_position_key(scope_id, broker_name, symbol))
        if isinstance(status, dict):
            status = dict(status)
            status["scope_id"] = scope_id
            status["broker_name"] = broker_name
            status["display_symbol"] = str(symbol).upper()
        return status

    def remove_scoped_position(self: Any, scope_id: str, broker_name: str, symbol: str):
        return self.remove_position(scoped_position_key(scope_id, broker_name, symbol))

    def confirm_scoped_realized_harvest(
        self: Any,
        scope_id: str,
        broker_name: str,
        symbol: str,
        amount_usd: float,
        *,
        broker_fill_id: str,
        note: str = "",
    ) -> float:
        method = getattr(self, "confirm_realized_harvest", None)
        if not callable(method):
            raise RuntimeError("profit realization guard v66 is not installed")
        key = scoped_position_key(scope_id, broker_name, symbol)
        return float(
            method(
                key,
                amount_usd,
                broker_fill_id=broker_fill_id,
                broker_name=broker_name,
                account_id=scope_id,
                note=note,
            )
            or 0.0
        )

    cls.register_scoped_position = register_scoped_position
    cls.process_scoped_price_update = process_scoped_price_update
    cls.get_scoped_harvest_status = get_scoped_harvest_status
    cls.remove_scoped_position = remove_scoped_position
    cls.confirm_scoped_realized_harvest = confirm_scoped_realized_harvest
    setattr(cls, _PATCH_ATTR, True)
    LOGGER.critical(
        "ACCOUNT_SCOPED_PROFIT_HARVEST_V71_PATCHED marker=%s module=%s fill_proof_api=true",
        MARKER, module.__name__,
    )
    return True


def _patch_loaded() -> bool:
    changed = False
    for name in ("bot.profit_lock_engine", "profit_lock_engine"):
        module = sys.modules.get(name)
        if isinstance(module, ModuleType):
            changed = _patch_lock_engine(module) or changed
    for name in ("bot.profit_harvest_layer", "profit_harvest_layer"):
        module = sys.modules.get(name)
        if isinstance(module, ModuleType):
            changed = _patch_harvest_layer(module) or changed
    return changed


def install_import_hook() -> bool:
    with _LOCK:
        _patch_loaded()
        flag = "_NIJA_ACCOUNT_SCOPED_PROFIT_STATE_V71_IMPORT_HOOK"
        if getattr(builtins, flag, False):
            return True
        original_import = builtins.__import__

        @wraps(original_import)
        def guarded_import(name: str, globals=None, locals=None, fromlist=(), level: int = 0):
            result = original_import(name, globals, locals, fromlist, level)
            if "profit_lock_engine" in str(name) or "profit_harvest_layer" in str(name):
                _patch_loaded()
            return result

        builtins.__import__ = guarded_import
        setattr(builtins, flag, True)
        os.environ["NIJA_ACCOUNT_SCOPED_PROFIT_STATE_V71_INSTALLED"] = "1"
        LOGGER.critical(
            "ACCOUNT_SCOPED_PROFIT_STATE_V71_INSTALLED marker=%s scoped_key_required_for_new_integrations=true",
            MARKER,
        )
        return True


def install() -> bool:
    return install_import_hook()


__all__ = ["MARKER", "scoped_position_key", "install", "install_import_hook"]
