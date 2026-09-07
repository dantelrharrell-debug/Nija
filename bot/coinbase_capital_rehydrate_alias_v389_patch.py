"""Cover the canonical CoinbaseAdvancedTradeBroker with v388 rehydration.

This patch only extends v388's existing read-only connect hook to the canonical
Coinbase class alias used by some startup paths. It never submits orders, grants
execution authority, fabricates balances, or changes risk/protection gates.
"""
from __future__ import annotations

import importlib
import logging
import os
import sys
import threading
import time
from types import ModuleType
from typing import Any

logger = logging.getLogger("nija.coinbase_capital_rehydrate_alias_v389")
MARKER = "20260907-coinbase-capital-rehydrate-alias-v389"
_LOCK = threading.RLock()
_INSTALLED = False
_MONITOR_STARTED = False


def _v388() -> Any:
    for name in (
        "nija_coinbase_capital_readonly_rehydrate_v388_patch",
        "bot.coinbase_capital_readonly_rehydrate_v388_patch",
    ):
        module = sys.modules.get(name)
        if module is not None and callable(getattr(module, "_patch_class", None)):
            return module
    return importlib.import_module("bot.coinbase_capital_readonly_rehydrate_v388_patch")


def _patch_loaded() -> bool:
    v388 = _v388()
    patch_class = getattr(v388, "_patch_class", None)
    if not callable(patch_class):
        return False
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
            "CoinbaseAdvancedTradeBroker",
            "CoinbaseBroker",
            "CoinbaseBrokerAdapter",
            "_CoinbaseInvalidProductFilter",
        ):
            cls = getattr(module, class_name, None)
            if isinstance(cls, type):
                try:
                    changed = bool(patch_class(cls)) or changed
                except Exception:
                    logger.exception(
                        "COINBASE_CAPITAL_REHYDRATE_ALIAS_V389_CLASS_ERROR marker=%s module=%s class=%s",
                        MARKER,
                        module_name,
                        class_name,
                    )
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
            logger.exception("COINBASE_CAPITAL_REHYDRATE_ALIAS_V389_MONITOR_ERROR marker=%s", MARKER)
        time.sleep(0.20)


def install() -> bool:
    global _INSTALLED, _MONITOR_STARTED
    with _LOCK:
        v388 = _v388()
        installer = getattr(v388, "install", None)
        if callable(installer):
            installer()
        _patch_loaded()
        if not _MONITOR_STARTED:
            _MONITOR_STARTED = True
            threading.Thread(
                target=_monitor,
                name="CoinbaseCapitalRehydrateAliasV389",
                daemon=True,
            ).start()
        if not _INSTALLED:
            _INSTALLED = True
            logger.critical(
                "COINBASE_CAPITAL_REHYDRATE_ALIAS_V389_INSTALLED marker=%s "
                "canonical_class=CoinbaseAdvancedTradeBroker read_only=true "
                "orders_submitted=false execution_authority_unchanged=true "
                "balance_fabricated=false safety_gates_bypassed=false",
                MARKER,
            )
        return True


install()

__all__ = ["MARKER", "install", "_patch_loaded"]
