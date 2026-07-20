"""Make fresh Kraken private equity authoritative over older cached snapshots.

The existing equity repair intentionally used max(live, cached) to avoid undercounting,
but that makes equity monotonic and lets an old higher snapshot override a newer private
balance. This guard unwraps the Kraken balance method to its live implementation and uses
cached/enriched totals only when the private request cannot produce a positive balance.
"""
from __future__ import annotations

import builtins
import logging
import os
import sys
import threading
import time
from functools import wraps
from types import ModuleType
from typing import Any, Mapping

logger = logging.getLogger("nija.kraken_equity_freshness")
_MARKER = "20260720-kraken-equity-freshness-v3"
_PATCH_ATTR = "_nija_kraken_equity_freshness_v3"
_LOCK = threading.RLock()
_STARTED = False


def _f(value: Any) -> float:
    try:
        parsed = float(value or 0.0)
    except (TypeError, ValueError, OverflowError):
        return 0.0
    return parsed if parsed == parsed and parsed > 0 else 0.0


def _total(value: Any) -> float:
    if isinstance(value, Mapping):
        for key in (
            "total_funds", "total_balance", "total_equity", "equity",
            "account_equity", "portfolio_value", "balance", "available_balance",
        ):
            parsed = _f(value.get(key))
            if parsed > 0:
                return parsed
        result = value.get("result")
        if isinstance(result, Mapping):
            for key in ("eb", "e", "equity", "total_funds", "total_balance"):
                parsed = _f(result.get(key))
                if parsed > 0:
                    return parsed
        return 0.0
    return _f(value)


def _unwrap_live(method: Any) -> Any:
    current = method
    seen: set[int] = set()
    while callable(current) and id(current) not in seen:
        seen.add(id(current))
        nxt = getattr(current, "__wrapped__", None) or getattr(current, "_nija_original", None)
        if not callable(nxt):
            break
        current = nxt
    return current


def _is_kraken(cls: type) -> bool:
    return "kraken" in cls.__name__.lower()


def _patch_class(cls: type) -> bool:
    current = getattr(cls, "get_account_balance", None)
    if not _is_kraken(cls) or not callable(current):
        return False
    if getattr(current, _PATCH_ATTR, False):
        return True

    live_method = _unwrap_live(current)

    @wraps(current)
    def get_account_balance(self: Any, *args: Any, **kwargs: Any):
        fresh_value: Any = None
        fresh_total = 0.0
        fresh_error = ""
        try:
            fresh_value = live_method(self, *args, **kwargs)
            fresh_total = _total(fresh_value)
        except Exception as exc:
            fresh_error = f"{type(exc).__name__}:{str(exc)[:180]}"

        if fresh_total > 0:
            try:
                setattr(self, "_last_known_balance", fresh_total)
                setattr(self, "_nija_last_fresh_private_equity", fresh_total)
                setattr(self, "_nija_last_fresh_private_equity_at", time.time())
            except Exception:
                pass
            logger.critical(
                "KRAKEN_EQUITY_FRESH_PRIVATE_SELECTED marker=%s fresh=$%.8f cache_policy=fallback_only",
                _MARKER, fresh_total,
            )
            if isinstance(fresh_value, Mapping):
                updated = dict(fresh_value)
                updated["total_balance"] = fresh_total
                updated["total_funds"] = fresh_total
                updated["equity_fresh"] = True
                return updated
            return fresh_total

        fallback = current(self, *args, **kwargs)
        fallback_total = _total(fallback)
        logger.warning(
            "KRAKEN_EQUITY_CACHE_FALLBACK marker=%s fallback=$%.8f fresh_error=%s",
            _MARKER, fallback_total, fresh_error or "fresh_nonpositive",
        )
        return fallback

    setattr(get_account_balance, _PATCH_ATTR, True)
    get_account_balance.__wrapped__ = current  # type: ignore[attr-defined]
    setattr(cls, "get_account_balance", get_account_balance)
    logger.critical(
        "KRAKEN_EQUITY_FRESHNESS_PATCHED marker=%s module=%s class=%s",
        _MARKER, cls.__module__, cls.__name__,
    )
    return True


def _patch_module(module: ModuleType) -> bool:
    changed = False
    for value in vars(module).values():
        if isinstance(value, type) and _is_kraken(value):
            changed = _patch_class(value) or changed
    return changed


def _patch_loaded() -> bool:
    changed = False
    for name, module in list(sys.modules.items()):
        if isinstance(module, ModuleType) and any(token in name.lower() for token in ("broker", "kraken", "execution")):
            changed = _patch_module(module) or changed
    return changed


def _watchdog() -> None:
    while True:
        try:
            _patch_loaded()
        except Exception as exc:
            logger.debug("KRAKEN_EQUITY_FRESHNESS_RETRY marker=%s error=%s", _MARKER, exc)
        time.sleep(1.0)


def install() -> bool:
    global _STARTED
    with _LOCK:
        _patch_loaded()
        if not _STARTED:
            _STARTED = True
            threading.Thread(target=_watchdog, name="KrakenEquityFreshnessV3", daemon=True).start()
        os.environ["NIJA_KRAKEN_EQUITY_FRESHNESS_V3_INSTALLED"] = "1"
        logger.critical("KRAKEN_EQUITY_FRESHNESS_V3_INSTALLED marker=%s", _MARKER)
        return True


__all__ = ["install", "_patch_class", "_total", "_unwrap_live"]
