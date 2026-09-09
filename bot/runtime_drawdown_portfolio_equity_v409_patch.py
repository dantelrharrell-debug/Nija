"""Portfolio-equity correction for the global drawdown breaker (v409).

CapitalAuthority intentionally publishes spendable/platform broker balances for
sizing and routing.  Coinbase's platform balance is therefore cash-like and can
fall when USD is converted into an owned crypto position.  The global drawdown
breaker, however, must compare total portfolio equity, not spendable cash.

This patch corrects only that accounting mismatch:

* Kraken remains untouched because its admitted platform capital is already
  authenticated TradeBalance equity.
* Coinbase platform holdings are added only when the startup position snapshot
  is authoritative/adopted and the local tracker has verified cost basis.
* Market value comes from an existing row price when available, otherwise from
  Coinbase's public current-price method with a short local cache.
* If any required proof is missing, no correction is applied and the breaker
  remains fail-closed.
* Drawdown thresholds are unchanged.  No order, fill, balance, position, price,
  execution proof, writer authority, or readiness is fabricated.
* A HALT level caused solely by the omitted authoritative Coinbase holding may
  be reclassified to the level implied by corrected equity while preserving the
  existing peak.  A non-drawdown kill switch is never cleared.
"""
from __future__ import annotations

import importlib
import logging
import os
import threading
import time
from functools import wraps
from typing import Any, Mapping

LOGGER = logging.getLogger("nija.runtime_drawdown_portfolio_equity_v409")
MARKER = "20260909-runtime-drawdown-portfolio-equity-v409"
_READY_FLAG = "NIJA_RUNTIME_DRAWDOWN_PORTFOLIO_EQUITY_V409_READY"
_PATCH_ATTR = "_nija_drawdown_portfolio_equity_v409"
_LOCK = threading.RLock()
_PRICE_CACHE: dict[tuple[int, str], tuple[float, float]] = {}
_LAST_LOG: tuple[float, float, float] | None = None


def _float(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
        return default if number != number else number
    except Exception:
        return default


def _label(value: Any) -> str:
    raw = getattr(value, "value", value)
    text = str(raw or "").strip().lower()
    if "." in text:
        text = text.rsplit(".", 1)[-1]
    return text


def _connected(broker: Any) -> bool:
    if broker is None:
        return False
    for attr in ("is_connected", "connected"):
        probe = getattr(broker, attr, None)
        try:
            value = probe() if callable(probe) else probe
            if value is not None:
                return bool(value)
        except Exception:
            continue
    return False


def _canonical_manager() -> Any:
    try:
        v281 = importlib.import_module("bot.runtime_all_account_position_exit_coverage_v281_patch")
        getter = getattr(v281, "_canonical_manager", None)
        manager = getter() if callable(getter) else None
        if manager is not None:
            return manager
    except Exception:
        pass
    for name in ("bot.multi_account_broker_manager", "multi_account_broker_manager"):
        try:
            module = importlib.import_module(name)
            getter = getattr(module, "get_broker_manager", None)
            manager = getter() if callable(getter) else None
            if manager is not None:
                return manager
        except Exception:
            continue
    return None


def _platform_coinbase(manager: Any) -> Any:
    if manager is None:
        return None
    try:
        items = tuple((getattr(manager, "_platform_brokers", {}) or {}).items())
    except Exception:
        return None
    for broker_type, broker in items:
        if _label(broker_type) == "coinbase":
            return broker
    return None


def _normalise_symbol(value: Any) -> str:
    return str(value or "").strip().upper().replace("/", "-").replace("_", "-")


def _row_quantity(row: Mapping[str, Any]) -> float:
    for key in ("quantity", "qty", "amount", "size", "units", "balance"):
        if row.get(key) is not None:
            return _float(row.get(key))
    return 0.0


def _cached_public_price(broker: Any, symbol: str, row: Mapping[str, Any]) -> float:
    for key in ("current_price", "market_price", "mark_price", "last_price", "price"):
        price = _float(row.get(key))
        if price > 0:
            return price

    cache_key = (id(broker), symbol)
    now = time.monotonic()
    cached = _PRICE_CACHE.get(cache_key)
    if cached and now - cached[0] <= 15.0 and cached[1] > 0:
        return cached[1]

    for method_name in ("get_current_price", "get_price", "get_ticker_price", "fetch_price"):
        method = getattr(broker, method_name, None)
        if not callable(method):
            continue
        try:
            price = _float(method(symbol))
        except Exception:
            price = 0.0
        if price > 0:
            _PRICE_CACHE[cache_key] = (now, price)
            return price
    return 0.0


def _authoritative_coinbase_holding_value() -> tuple[bool, float, tuple[str, ...], str]:
    manager = _canonical_manager()
    broker = _platform_coinbase(manager)
    if broker is None:
        return False, 0.0, (), "coinbase_platform_broker_missing"
    if not _connected(broker):
        return False, 0.0, (), "coinbase_platform_disconnected"
    if getattr(broker, "_startup_position_sync_fetch_ok", None) is not True:
        return False, 0.0, (), "authoritative_position_fetch_unproven"
    if getattr(broker, "_startup_position_sync_adopted", None) is not True:
        return False, 0.0, (), "authoritative_position_snapshot_unproven"

    try:
        authoritative = {
            _normalise_symbol(value)
            for value in tuple(getattr(broker, "_startup_position_sync_symbols", ()) or ())
            if _normalise_symbol(value)
        }
    except Exception:
        return False, 0.0, (), "authoritative_snapshot_symbols_invalid"

    if not authoritative:
        return True, 0.0, (), "authoritative_no_open_positions"

    tracker = getattr(broker, "position_tracker", None)
    get_position = getattr(tracker, "get_position", None) if tracker is not None else None
    if not callable(get_position):
        return False, 0.0, (), "position_tracker_unavailable"

    total = 0.0
    valued: list[str] = []
    for symbol in sorted(authoritative):
        try:
            row = get_position(symbol)
        except Exception:
            return False, 0.0, tuple(valued), f"tracker_read_failed:{symbol}"
        if not isinstance(row, Mapping):
            return False, 0.0, tuple(valued), f"tracker_position_missing:{symbol}"
        qty = abs(_row_quantity(row))
        if qty <= 0:
            return False, 0.0, tuple(valued), f"authoritative_quantity_unproven:{symbol}"
        if row.get("cost_basis_verified") is not True:
            return False, 0.0, tuple(valued), f"cost_basis_unverified:{symbol}"
        price = _cached_public_price(broker, symbol, row)
        if price <= 0:
            return False, 0.0, tuple(valued), f"market_price_unproven:{symbol}"
        total += qty * price
        valued.append(symbol)

    return True, total, tuple(valued), "authoritative_coinbase_holdings_marked"


def _capital_authority_matches(equity: float) -> tuple[bool, float]:
    try:
        ca = importlib.import_module("bot.capital_authority").get_capital_authority()
        current = _float(ca.get_real_capital())
    except Exception:
        return False, 0.0
    if current <= 0 or equity <= 0:
        return False, current
    tolerance = max(1.0, current * 0.02)
    return abs(current - equity) <= tolerance, current


def _reclassify_false_halt_if_proven(cb: Any, corrected_equity: float) -> bool:
    """Reclassify only the breaker level; external kill-switch recovery stays separate."""
    try:
        level = getattr(cb, "_level", None)
        if str(getattr(level, "value", level) or "").upper() != "HALT":
            return False
        peak = _float(getattr(cb, "_peak_equity", 0.0))
        if peak <= 0 or corrected_equity <= 0:
            return False
        drawdown = max(0.0, (peak - corrected_equity) / peak * 100.0)
        config = getattr(cb, "_config", None)
        halt_pct = _float(getattr(config, "halt_pct", 0.0))
        if halt_pct <= 0 or drawdown >= halt_pct:
            return False
        level_from_drawdown = getattr(cb, "_level_from_drawdown", None)
        if not callable(level_from_drawdown):
            return False
        new_level = level_from_drawdown(drawdown)
        lock = getattr(cb, "_lock", None)
        if lock is None:
            return False
        with lock:
            setattr(cb, "_current_equity", corrected_equity)
            setattr(cb, "_low_equity", corrected_equity)
            setattr(cb, "_level", new_level)
            setattr(cb, "_consecutive_wins", 0)
        LOGGER.critical(
            "DRAWDOWN_V409_FALSE_HALT_RECLASSIFIED marker=%s peak=%.8f corrected_equity=%.8f corrected_drawdown_pct=%.6f new_level=%s "
            "peak_preserved=true threshold_unchanged=true kill_switch_cleared=false orders_submitted=false safety_gates_bypassed=false",
            MARKER, peak, corrected_equity, drawdown,
            str(getattr(new_level, "value", new_level)),
        )
        return True
    except Exception:
        LOGGER.exception("DRAWDOWN_V409_FALSE_HALT_RECLASSIFY_ERROR marker=%s fail_closed=true", MARKER)
        return False


def _patch() -> bool:
    module = importlib.import_module("bot.global_drawdown_circuit_breaker")
    cls = getattr(module, "GlobalDrawdownCircuitBreaker", None)
    if not isinstance(cls, type):
        return False
    current = getattr(cls, "update_equity", None)
    if not callable(current):
        return False
    if bool(getattr(current, _PATCH_ATTR, False)):
        return True

    @wraps(current)
    def update_equity(self: Any, equity_usd: float):
        global _LAST_LOG
        raw_equity = max(0.0, _float(equity_usd))
        matches, ca_total = _capital_authority_matches(raw_equity)
        corrected = raw_equity
        holding_value = 0.0
        symbols: tuple[str, ...] = ()
        reason = "capital_authority_series_mismatch"
        proof_ready = False

        if matches:
            proof_ready, holding_value, symbols, reason = _authoritative_coinbase_holding_value()
            if proof_ready and holding_value > 0:
                corrected = raw_equity + holding_value
                _reclassify_false_halt_if_proven(self, corrected)

        signature = (round(raw_equity, 6), round(holding_value, 6), round(corrected, 6))
        if signature != _LAST_LOG:
            _LAST_LOG = signature
            log = LOGGER.info if proof_ready else LOGGER.warning
            log(
                "DRAWDOWN_V409_PORTFOLIO_EQUITY marker=%s raw_capital=%.8f capital_authority=%.8f coinbase_holding_value=%.8f corrected_equity=%.8f "
                "proof_ready=%s symbols=%s reason=%s kraken_tradebalance_unchanged=true thresholds_unchanged=true price_fabricated=false balance_fabricated=false "
                "position_fabricated=false execution_authority_unchanged=true orders_submitted=false safety_gates_bypassed=false",
                MARKER, raw_equity, ca_total, holding_value, corrected,
                str(proof_ready).lower(), ",".join(symbols) or "none", reason,
            )
        return current(self, corrected)

    setattr(update_equity, _PATCH_ATTR, True)
    setattr(update_equity, "__wrapped__", current)
    setattr(cls, "update_equity", update_equity)
    return True


def _recover_exact_false_drawdown_stop() -> bool:
    """Clear only an exact drawdown-caused stop after corrected equity proves HALT false.

    This does not force LIVE_ACTIVE.  It only deactivates the global kill switch;
    normal startup/readiness gates must independently restore execution authority.
    """
    try:
        drawdown = importlib.import_module("bot.global_drawdown_circuit_breaker")
        getter = getattr(drawdown, "get_global_drawdown_cb", None)
        cb = getter() if callable(getter) else None
        if cb is None:
            return False
        raw = _float(getattr(cb, "_current_equity", 0.0))
        matches, _ca_total = _capital_authority_matches(raw)
        if not matches:
            return False
        proof_ready, holding_value, _symbols, _reason = _authoritative_coinbase_holding_value()
        if not proof_ready or holding_value <= 0:
            return False
        corrected = raw + holding_value
        peak = _float(getattr(cb, "_peak_equity", 0.0))
        config = getattr(cb, "_config", None)
        halt_pct = _float(getattr(config, "halt_pct", 0.0))
        if peak <= 0 or halt_pct <= 0:
            return False
        corrected_dd = max(0.0, (peak - corrected) / peak * 100.0)
        if corrected_dd >= halt_pct:
            return False

        kill_module = importlib.import_module("bot.kill_switch")
        ks_getter = getattr(kill_module, "get_kill_switch", None)
        ks = ks_getter() if callable(ks_getter) else None
        if ks is None or not bool(ks.is_active()):
            return False
        status = dict(ks.get_status() or {})
        history = status.get("recent_history") or status.get("history") or []
        last = history[-1] if isinstance(history, list) and history else {}
        reason_text = str(last.get("reason", "") if isinstance(last, Mapping) else last).lower()
        source_text = str(last.get("source", "") if isinstance(last, Mapping) else "").lower()
        if "globaldrawdowncircuitbreaker" not in reason_text and "drawdown" not in reason_text:
            return False
        if source_text and "globaldrawdowncircuitbreaker" not in source_text and source_text not in {"auto", "risk"}:
            return False

        _reclassify_false_halt_if_proven(cb, corrected)
        ks.deactivate(
            "v409 corrected portfolio equity proved prior GlobalDrawdownCircuitBreaker HALT was caused by omitted authoritative Coinbase holding value"
        )
        LOGGER.critical(
            "DRAWDOWN_V409_FALSE_KILL_SWITCH_CLEARED marker=%s raw_equity=%.8f holding_value=%.8f corrected_equity=%.8f peak=%.8f corrected_drawdown_pct=%.6f halt_pct=%.6f "
            "exact_drawdown_source_required=true force_activation=false readiness_bypass=false threshold_unchanged=true orders_submitted=false safety_gates_bypassed=false",
            MARKER, raw, holding_value, corrected, peak, corrected_dd, halt_pct,
        )
        return True
    except Exception:
        LOGGER.exception("DRAWDOWN_V409_FALSE_KILL_SWITCH_RECOVERY_ERROR marker=%s fail_closed=true", MARKER)
        return False


def install() -> bool:
    with _LOCK:
        try:
            ready = _patch()
            os.environ[_READY_FLAG] = "1" if ready else "0"
            if ready:
                # Recovery is deliberately best-effort and proof-gated.  Failure leaves
                # the existing stop untouched.
                _recover_exact_false_drawdown_stop()
            LOGGER.critical(
                "RUNTIME_DRAWDOWN_PORTFOLIO_EQUITY_V409_%s marker=%s coinbase_authoritative_holdings=true kraken_tradebalance_unchanged=true "
                "halt_threshold_unchanged=true false_stop_recovery_proof_gated=true force_activation=false orders_submitted=false safety_gates_bypassed=false",
                "READY" if ready else "PENDING", MARKER,
            )
            return bool(ready)
        except Exception:
            os.environ[_READY_FLAG] = "0"
            LOGGER.exception("RUNTIME_DRAWDOWN_PORTFOLIO_EQUITY_V409_INSTALL_ERROR marker=%s trading_fail_closed=true", MARKER)
            return False


install_import_hook = install

__all__ = ["MARKER", "install", "install_import_hook"]
