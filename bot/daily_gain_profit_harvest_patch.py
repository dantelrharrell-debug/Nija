"""Harvest today's gains from every held Kraken position without selling overall losers.

This patch extends the account-local Kraken exit supervisor. Every platform and
user-held position is enriched with Kraken's current UTC-day open and evaluated
for a daily-gain exit. A sell is eligible only when:

* the position has a verified positive cost basis,
* the current price is above fee-adjusted lifetime break-even (below for shorts),
* today's move exceeds the configured daily harvest threshold, and
* the normal exit engine has not already selected a stronger reason.

Orders still flow through the existing account-scoped exit pipeline, preserving
writer authority, private authentication, exchange minimums and duplicate-exit
protection. The rule never treats an intraday bounce as profit when the holding
is still below its lifetime break-even.
"""
from __future__ import annotations

import logging
import os
import threading
from functools import wraps
from typing import Any, Iterable, Mapping, MutableMapping, Optional, Tuple

logger = logging.getLogger("nija.daily_gain_profit_harvest")
_MARKER = "20260715-daily-gain-harvest-v1"
_TRUE = {"1", "true", "yes", "on", "enabled", "y"}
_LOCK = threading.RLock()
_INSTALLED = False


def _truthy(name: str, default: str = "true") -> bool:
    return str(os.environ.get(name, default) or "").strip().lower() in _TRUE


def _f(value: Any, default: float = 0.0) -> float:
    try:
        value = float(value)
        return default if value != value else value
    except Exception:
        return default


def _threshold() -> float:
    return max(0.001, _f(os.environ.get("NIJA_DAILY_GAIN_HARVEST_PCT"), 0.006))


def _ticker_snapshot(runtime: Any, broker: Any, pair: str) -> Tuple[float, float]:
    """Return (current, UTC-day-open) from Kraken's ticker payload."""
    try:
        payload = runtime._public_call(broker, "Ticker", {"pair": pair})
        result = payload.get("result", {}) if isinstance(payload, Mapping) else {}
        if not isinstance(result, Mapping) or not result:
            return 0.0, 0.0
        row = next(iter(result.values()))
        if not isinstance(row, Mapping):
            return 0.0, 0.0
        close = row.get("c")
        current = _f(close[0] if isinstance(close, (list, tuple)) and close else row.get("last"))
        day_open = _f(row.get("o") or row.get("open") or row.get("open_price"))
        return current, day_open
    except Exception:
        return 0.0, 0.0


def _daily_harvest_reason(
    runtime: Any,
    position: Mapping[str, Any],
    price: float,
    account: str,
    symbol: str,
) -> Tuple[Optional[str], float]:
    if not _truthy("NIJA_DAILY_GAIN_HARVEST_ENABLED", "true"):
        return None, 0.0
    entry = _f(runtime._entry_price(position))
    day_open = _f(position.get("daily_open_price"))
    if entry <= 0 or day_open <= 0 or price <= 0:
        return None, 0.0

    side = str(position.get("side") or "long").strip().lower()
    short = side in {"short", "sell"}
    daily_gain = (day_open - price) / day_open if short else (price - day_open) / day_open
    if daily_gain + 1e-12 < _threshold():
        return None, daily_gain

    breakeven, _ = runtime._exit_thresholds(account, symbol, entry)
    if short:
        round_trip = max(0.001, (breakeven / entry) - 1.0)
        breakeven = entry * (1.0 - round_trip)
        lifetime_net_positive = price <= breakeven
    else:
        lifetime_net_positive = price >= breakeven
    if not lifetime_net_positive:
        return None, daily_gain
    return "daily_gain_harvest", daily_gain


def _patch_runtime(runtime: Any) -> bool:
    changed = False

    current_rows = getattr(runtime, "_position_rows", None)
    if callable(current_rows) and not getattr(current_rows, "_nija_daily_gain_rows_v1", False):
        @wraps(current_rows)
        def position_rows(broker: Any) -> Iterable[MutableMapping[str, Any]]:
            for raw in current_rows(broker):
                position = dict(raw) if isinstance(raw, Mapping) else raw
                if not isinstance(position, MutableMapping):
                    continue
                symbol = runtime._normalise_symbol(position.get("symbol"))
                pair = runtime._resolve_pair(broker, symbol) if symbol else None
                current, day_open = _ticker_snapshot(runtime, broker, pair) if pair else (0.0, 0.0)
                if current > 0:
                    position["current_price"] = current
                if day_open > 0:
                    position["daily_open_price"] = day_open
                    position["daily_gain_pct"] = (
                        (day_open - current) / day_open
                        if str(position.get("side") or "long").lower() in {"short", "sell"}
                        else (current - day_open) / day_open
                    ) if current > 0 else 0.0
                yield position
        position_rows._nija_daily_gain_rows_v1 = True  # type: ignore[attr-defined]
        position_rows.__wrapped__ = current_rows  # type: ignore[attr-defined]
        runtime._position_rows = position_rows
        changed = True

    current_reason = getattr(runtime, "_exit_reason", None)
    if callable(current_reason) and not getattr(current_reason, "_nija_daily_gain_reason_v1", False):
        @wraps(current_reason)
        def exit_reason(position: Mapping[str, Any], price: float, account: str, symbol: str):
            reason, breakeven, target = current_reason(position, price, account, symbol)
            if reason:
                return reason, breakeven, target
            daily_reason, daily_gain = _daily_harvest_reason(runtime, position, price, account, symbol)
            if daily_reason:
                logger.critical(
                    "DAILY_GAIN_HARVEST_TRIGGER marker=%s account=%s symbol=%s daily_gain_pct=%.4f "
                    "entry=$%.8f day_open=$%.8f market=$%.8f breakeven=$%.8f",
                    _MARKER, account, symbol, daily_gain, runtime._entry_price(position),
                    _f(position.get("daily_open_price")), price, breakeven,
                )
                return daily_reason, breakeven, target
            if _f(runtime._entry_price(position)) <= 0 and _f(position.get("daily_open_price")) > 0:
                logger.warning(
                    "DAILY_GAIN_HARVEST_SKIPPED marker=%s account=%s symbol=%s reason=missing_verified_cost_basis",
                    _MARKER, account, symbol,
                )
            return reason, breakeven, target
        exit_reason._nija_daily_gain_reason_v1 = True  # type: ignore[attr-defined]
        exit_reason.__wrapped__ = current_reason  # type: ignore[attr-defined]
        runtime._exit_reason = exit_reason
        changed = True

    return changed


def install() -> bool:
    global _INSTALLED
    with _LOCK:
        if _INSTALLED:
            return True
        os.environ.setdefault("NIJA_DAILY_GAIN_HARVEST_ENABLED", "true")
        os.environ.setdefault("NIJA_DAILY_GAIN_HARVEST_PCT", "0.006")
        try:
            from bot import kraken_all_account_exit_runtime_patch as runtime
        except Exception:
            import kraken_all_account_exit_runtime_patch as runtime  # type: ignore
        installer = getattr(runtime, "install_import_hook", None)
        if callable(installer):
            installer()
        if not _patch_runtime(runtime):
            # Already patched is also a valid converged state.
            reason = getattr(runtime, "_exit_reason", None)
            if not getattr(reason, "_nija_daily_gain_reason_v1", False):
                raise RuntimeError("kraken_exit_runtime_not_patchable")
        _INSTALLED = True
        os.environ["NIJA_DAILY_GAIN_PROFIT_HARVEST_INSTALLED"] = "1"
        logger.critical(
            "DAILY_GAIN_PROFIT_HARVEST_INSTALLED marker=%s threshold_pct=%.4f all_accounts=true "
            "requires_fee_adjusted_lifetime_profit=true",
            _MARKER, _threshold(),
        )
        return True


__all__ = ["install", "_daily_harvest_reason", "_ticker_snapshot", "_patch_runtime"]
