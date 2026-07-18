"""Converge platform recovery ownership and Coinbase transient balance reads.

Keeps entry/risk authority unchanged. Prevents an exit-only recovery cycle from
competing with an already-live platform trader, and prevents a transient Coinbase
portfolio/get_accounts failure from replacing a recently verified positive balance
with a synthetic zero.
"""
from __future__ import annotations

import importlib
import logging
import threading
import time
from functools import wraps
from typing import Any

logger = logging.getLogger("nija.platform_recovery_coinbase_balance")
_MARKER = "20260718-platform-recovery-coinbase-balance-v1"
_LOCK = threading.RLock()
_INSTALLED = False


def _alive(thread: Any) -> bool:
    return bool(thread is not None and callable(getattr(thread, "is_alive", None)) and thread.is_alive())


def _patch_recovery_thread_detection() -> bool:
    module = importlib.import_module("account_exit_management_recovery_patch")
    current = getattr(module, "_normal_thread_alive", None)
    if not callable(current):
        return False
    if getattr(current, "_nija_platform_thread_truth_v1", False):
        return True

    @wraps(current)
    def normal_thread_alive(trader: Any, scope: str, user_id: Any, broker_type: Any, broker: Any) -> bool:
        if current(trader, scope, user_id, broker_type, broker):
            return True
        raw = getattr(broker_type, "value", broker_type)
        venue = str(raw or getattr(broker, "broker_name", "") or type(broker).__name__).lower()
        venue = venue.replace("broker", "").replace("_", "-").strip("-")
        expected = {f"Trader-{venue}", f"BrokerWorker-{venue}"}
        if scope == "user" and user_id:
            expected.add(f"Trader-{user_id}_{venue}")
        for thread in threading.enumerate():
            if thread.is_alive() and thread.name in expected:
                logger.critical(
                    "NORMAL_TRADER_DISCOVERED marker=%s scope=%s account=%s venue=%s thread=%s",
                    _MARKER, scope, user_id or "platform", venue, thread.name,
                )
                return True
        return False

    normal_thread_alive._nija_platform_thread_truth_v1 = True  # type: ignore[attr-defined]
    normal_thread_alive.__wrapped__ = current  # type: ignore[attr-defined]
    module._normal_thread_alive = normal_thread_alive
    return True


def _patch_coinbase_balance() -> bool:
    module = importlib.import_module("bot.broker_manager")
    cls = getattr(module, "CoinbaseBroker", None)
    if not isinstance(cls, type):
        return False
    current = getattr(cls, "get_account_balance", None)
    if not callable(current):
        return False
    if getattr(current, "_nija_coinbase_positive_cache_v1", False):
        return True

    @wraps(current)
    def get_account_balance(self: Any, *args: Any, **kwargs: Any):
        previous = None
        for attr in ("_nija_last_verified_coinbase_balance", "_nija_last_account_balance_usd", "_last_known_balance"):
            try:
                value = float(getattr(self, attr, 0.0) or 0.0)
                if value > 0:
                    previous = value
                    break
            except Exception:
                pass
        try:
            result = current(self, *args, **kwargs)
        except Exception:
            if previous is not None:
                logger.warning("COINBASE_BALANCE_TRANSIENT_CACHE_USED marker=%s balance=%.8f reason=exception", _MARKER, previous)
                return previous
            raise
        try:
            value = float(result or 0.0)
        except Exception:
            value = 0.0
        if value > 0:
            setattr(self, "_nija_last_verified_coinbase_balance", value)
            setattr(self, "_nija_last_verified_coinbase_balance_at", time.time())
            return result
        age = time.time() - float(getattr(self, "_nija_last_verified_coinbase_balance_at", 0.0) or 0.0)
        if previous is not None and age <= 300.0:
            logger.warning(
                "COINBASE_BALANCE_TRANSIENT_ZERO_REJECTED marker=%s reported=0.0 cached=%.8f cache_age_s=%.1f",
                _MARKER, previous, age,
            )
            return previous
        return result

    get_account_balance._nija_coinbase_positive_cache_v1 = True  # type: ignore[attr-defined]
    get_account_balance.__wrapped__ = current  # type: ignore[attr-defined]
    cls.get_account_balance = get_account_balance
    return True


def install() -> bool:
    global _INSTALLED
    with _LOCK:
        if _INSTALLED:
            return True
        results = {
            "normal_thread_detection": _patch_recovery_thread_detection(),
            "coinbase_positive_cache": _patch_coinbase_balance(),
        }
        if not all(results.values()):
            raise RuntimeError(f"platform_recovery_coinbase_balance_incomplete:{results}")
        _INSTALLED = True
        logger.critical("PLATFORM_RECOVERY_COINBASE_BALANCE_READY marker=%s results=%s", _MARKER, results)
        return True


__all__ = ["install"]
