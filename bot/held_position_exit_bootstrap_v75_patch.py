"""Bootstrap adaptive exit state for positions already held before deployment.

v74 is called from the universal broker exit supervisor, which enumerates the
broker's *current* position inventory every scan.  v75 makes that guarantee
explicit at installation time and preserves any trustworthy high/low-water
fields already carried by the broker position record.

No synthetic entry, peak, quantity, fill, or profit is created.  If historical
high/low-water evidence is absent, the first verified market price becomes the
initial adaptive reference and later scans update it normally.
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

from bot import adaptive_profit_exit_v74_patch as v74

LOGGER = logging.getLogger("nija.held_position_exit_bootstrap_v75")
MARKER = "20260809-held-position-exit-bootstrap-v75"
_PATCH_ATTR = "_nija_held_position_exit_bootstrap_v75"
_LOCK = threading.RLock()


def _f(value: Any, default: float = 0.0) -> float:
    try:
        result = float(value or 0.0)
    except (TypeError, ValueError, OverflowError):
        return default
    return result if result == result else default


def _persisted_peak(pos: Mapping[str, Any], market: float) -> float:
    return max(
        market,
        _f(pos.get("high_water")),
        _f(pos.get("high_water_price")),
        _f(pos.get("peak_price")),
        _f(pos.get("max_price_since_entry")),
        _f(pos.get("highest_price")),
    )


def _persisted_trough(pos: Mapping[str, Any], market: float) -> float:
    values = [
        value
        for value in (
            market,
            _f(pos.get("low_water")),
            _f(pos.get("low_water_price")),
            _f(pos.get("trough_price")),
            _f(pos.get("min_price_since_entry")),
            _f(pos.get("lowest_price")),
        )
        if value > 0.0
    ]
    return min(values) if values else market


def _install_peak_bootstrap() -> bool:
    current = getattr(v74, "_update_peak", None)
    if not callable(current):
        return False
    if getattr(current, _PATCH_ATTR, False):
        return True

    @wraps(current)
    def update_peak_with_held_history(
        universal: ModuleType,
        broker: Any,
        pos: Mapping[str, Any],
        market: float,
        short: bool,
        regime: str,
    ) -> dict[str, Any]:
        key = v74._position_key(universal, broker, pos)
        with v74._LOCK:
            existing = v74._POSITIONS.get(key)
            if not existing:
                peak = _persisted_peak(pos, market)
                trough = _persisted_trough(pos, market)
                v74._POSITIONS[key] = {
                    "peak": peak,
                    "trough": trough,
                    "armed": False,
                    "regime": regime,
                    "market": market,
                    "short": short,
                    "bootstrap_source": (
                        "persisted_position_history"
                        if peak > market or trough < market
                        else "first_verified_market"
                    ),
                }
                LOGGER.critical(
                    "HELD_POSITION_EXIT_V75_BOOTSTRAPPED marker=%s venue=%s account=%s symbol=%s "
                    "position_id=%s market=%.8f peak=%.8f trough=%.8f source=%s",
                    MARKER,
                    v74.v68._broker_label(universal, broker),
                    v74._account(universal, broker, pos),
                    universal.auto_exit._sym(pos.get("symbol")),
                    str(pos.get("position_id") or pos.get("id") or ""),
                    market,
                    peak,
                    trough,
                    v74._POSITIONS[key]["bootstrap_source"],
                )
        return current(universal, broker, pos, market, short, regime)

    setattr(update_peak_with_held_history, _PATCH_ATTR, True)
    setattr(update_peak_with_held_history, "__wrapped__", current)
    v74._update_peak = update_peak_with_held_history
    return True


def _bootstrap_existing_positions(universal: ModuleType) -> int:
    """Seed adaptive state for every currently held broker position."""
    snapshot = getattr(universal, "_snapshot", None)
    positions_fn = getattr(universal, "_tracker_positions", None)
    if not callable(snapshot) or not callable(positions_fn):
        return 0
    count = 0
    for broker in list(snapshot() or []):
        for pos in list(positions_fn(broker) or []):
            if not isinstance(pos, Mapping):
                continue
            symbol = universal.auto_exit._sym(pos.get("symbol"))
            entry = universal.auto_exit._entry_price(dict(pos))
            qty = universal.auto_exit._quantity(dict(pos))
            if not symbol or entry <= 0.0 or qty <= 0.0:
                continue
            market = universal.auto_exit._price(broker, symbol)
            if market <= 0.0:
                continue
            short = universal.auto_exit._side(pos.get("side"), dict(pos)) in {"short", "sell"}
            regime, _confidence = v74._regime_snapshot(pos)
            v74._update_peak(universal, broker, pos, market, short, regime)
            count += 1
    if count:
        LOGGER.critical(
            "HELD_POSITION_EXIT_V75_EXISTING_POSITIONS_CONNECTED marker=%s positions=%d adaptive_exit=true",
            MARKER,
            count,
        )
    return count


def _patch_loaded() -> bool:
    _install_peak_bootstrap()
    changed = False
    for name in (
        "bot.universal_broker_exit_supervisor_patch",
        "universal_broker_exit_supervisor_patch",
    ):
        module = sys.modules.get(name)
        if not isinstance(module, ModuleType):
            continue
        try:
            _bootstrap_existing_positions(module)
            changed = True
        except Exception as exc:
            LOGGER.warning(
                "HELD_POSITION_EXIT_V75_BOOTSTRAP_RETRY marker=%s module=%s error=%s:%s",
                MARKER,
                name,
                type(exc).__name__,
                exc,
            )
    return changed


def install_import_hook() -> bool:
    with _LOCK:
        v74.install_import_hook()
        try:
            importlib.import_module("bot.universal_broker_exit_supervisor_patch")
        except Exception:
            pass
        _patch_loaded()
        flag = "_NIJA_HELD_POSITION_EXIT_BOOTSTRAP_V75_IMPORT_HOOK"
        if getattr(builtins, flag, False):
            return True
        original_import = builtins.__import__

        @wraps(original_import)
        def guarded_import(name: str, globals=None, locals=None, fromlist=(), level: int = 0):
            result = original_import(name, globals, locals, fromlist, level)
            if "universal_broker_exit" in str(name):
                _patch_loaded()
            return result

        builtins.__import__ = guarded_import
        setattr(builtins, flag, True)
        os.environ["NIJA_HELD_POSITION_EXIT_BOOTSTRAP_V75_INSTALLED"] = "1"
        LOGGER.critical(
            "HELD_POSITION_EXIT_BOOTSTRAP_V75_INSTALLED marker=%s existing_positions=true persisted_high_water=true",
            MARKER,
        )
        return True


def install() -> bool:
    return install_import_hook()


__all__ = [
    "MARKER",
    "install",
    "install_import_hook",
    "_bootstrap_existing_positions",
    "_persisted_peak",
    "_persisted_trough",
]
