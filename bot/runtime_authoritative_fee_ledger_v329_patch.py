"""Authoritative entry-fee and short-ledger authority v329.

ExecutionEngine's legacy entry bookkeeping assumes a flat 0.60% entry fee and
always calls ``record_buy`` even for a short entry.  The live admission/routing
stack is now venue-aware, so bookkeeping must use the same economics.

v329 changes bookkeeping only after the existing execution path has produced a
position.  It never submits, cancels, sizes, reroutes, approves or closes an
order.

Invariants:
* runtime/account taker fee wins when exposed by the live broker;
* otherwise the canonical v324 current public fee fallback is used;
* numeric ledger/open-position ``entry_fee`` is overwritten with that fee;
* a short entry is stored as SELL + OPEN rather than BUY + OPEN;
* the returned/in-memory position receives the corrected ``entry_fee`` and
  ``executed_cost`` fields;
* no fill, risk, writer, nonce, kill-switch, capital, reconciliation or exit
  gate is weakened.
"""
from __future__ import annotations

from contextvars import ContextVar
from functools import wraps
import importlib
import logging
import math
import os
import threading
import time
from typing import Any, Optional

LOGGER = logging.getLogger("nija.runtime_authoritative_fee_ledger_v329")
MARKER = "20260831-runtime-authoritative-fee-ledger-v329"
_PATCH_ATTR = "_nija_runtime_authoritative_fee_ledger_v329"
_LOCK = threading.RLock()
_ENTRY_CONTEXT: ContextVar[Optional[dict[str, Any]]] = ContextVar(
    "nija_v329_entry_context", default=None
)
_FEE_CACHE: dict[tuple[int, str], tuple[float, float, str]] = {}
_FEE_CACHE_LOCK = threading.RLock()


def _f(value: Any, default: float = 0.0) -> float:
    try:
        out = float(value if value is not None else default)
    except (TypeError, ValueError, OverflowError):
        return default
    return out if math.isfinite(out) else default


def _norm(value: Any) -> str:
    return str(value or "").strip().lower().replace(" ", "_")


def _fee_rate(broker: Any, symbol: str) -> tuple[float, str]:
    key = (id(broker), str(symbol or "").upper())
    now = time.monotonic()
    with _FEE_CACHE_LOCK:
        cached = _FEE_CACHE.get(key)
        if cached and now - cached[0] <= 60.0:
            return cached[1], cached[2]

    core = importlib.import_module("bot.runtime_all_in_profitability_authority_v324_core")
    runtime_fn = getattr(core, "_runtime_taker_fee", None)
    broker_name_fn = getattr(core, "_broker_name_from_client", None)
    fallback_fn = getattr(core, "_current_base_fees", None)

    rate = None
    if callable(runtime_fn):
        try:
            rate = runtime_fn(broker, symbol)
        except Exception:
            rate = None
    if rate is not None and 0.0 <= _f(rate, -1.0) <= 0.05:
        result = (_f(rate), "broker_runtime_taker_fee")
    else:
        broker_name = "unknown"
        if callable(broker_name_fn):
            try:
                broker_name = str(broker_name_fn(broker) or "unknown")
            except Exception:
                pass
        if callable(fallback_fn):
            _maker, taker, source = fallback_fn(broker_name, symbol)
            result = (max(0.0, min(0.05, _f(taker, 0.005))), f"fallback:{source}")
        else:
            result = (0.005, "unknown_conservative_fallback")

    with _FEE_CACHE_LOCK:
        _FEE_CACHE[key] = (now, result[0], result[1])
    return result


def _current_authoritative_fee(symbol: str, size_usd: float) -> tuple[float, float, str]:
    ctx = _ENTRY_CONTEXT.get() or {}
    rate, source = _fee_rate(ctx.get("broker_client"), symbol)
    fee = max(0.0, _f(size_usd)) * rate
    return fee, rate, source


def _append_notes(notes: Any, *, fee: float, rate: float, source: str, side: str, price: float, quantity: float) -> str:
    base = str(notes or "").strip()
    executed_cost = max(0.0, _f(price)) * max(0.0, _f(quantity)) + max(0.0, fee)
    suffix = (
        f"v329_authoritative_entry_fee=${fee:.8f}; "
        f"v329_fee_rate={rate:.8f}; v329_fee_source={source}; "
        f"v329_entry_side={side}; v329_authoritative_executed_cost=${executed_cost:.8f}"
    )
    return f"{base} | {suffix}" if base else suffix


def _insert_short_open(
    ledger: Any,
    *,
    symbol: str,
    price: float,
    quantity: float,
    size_usd: float,
    fee: float,
    order_id: str | None,
    position_id: str | None,
    user_id: str,
    notes: str | None,
    platform_trade_id: str | None,
) -> int:
    module = importlib.import_module("bot.trade_ledger_db")
    with ledger._get_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO trade_ledger
            (timestamp, user_id, symbol, side, action, price, quantity,
             size_usd, fee, order_id, position_id, platform_trade_id, notes)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                module.datetime.now().isoformat(), user_id, symbol, "SELL", "OPEN",
                price, quantity, size_usd, fee, order_id, position_id,
                platform_trade_id, notes,
            ),
        )
        tx_id = int(cur.lastrowid or 0)
    LOGGER.critical(
        "AUTHORITATIVE_FEE_LEDGER_V329_SHORT_OPEN marker=%s user=%s symbol=%s tx_id=%s fee=%.8f",
        MARKER, user_id, symbol, tx_id, fee,
    )
    return tx_id


def _patch_ledger() -> bool:
    try:
        module = importlib.import_module("bot.trade_ledger_db")
        cls = getattr(module, "TradeLedgerDB", None)
    except Exception:
        return False
    if cls is None:
        return False

    current_buy = getattr(cls, "record_buy", None)
    if not callable(current_buy):
        return False
    if not getattr(current_buy, _PATCH_ATTR, False):
        @wraps(current_buy)
        def record_entry_with_authoritative_fee(
            self,
            symbol: str,
            price: float,
            quantity: float,
            size_usd: float,
            fee: float = 0.0,
            order_id: str = None,
            position_id: str = None,
            user_id: str = "platform",
            notes: str = None,
            platform_trade_id: str = None,
        ) -> int:
            ctx = _ENTRY_CONTEXT.get()
            if not ctx:
                return current_buy(
                    self, symbol, price, quantity, size_usd, fee,
                    order_id, position_id, user_id, notes, platform_trade_id,
                )
            auth_fee, rate, source = _current_authoritative_fee(symbol, size_usd)
            side = _norm(ctx.get("side"))
            corrected_notes = _append_notes(
                notes, fee=auth_fee, rate=rate, source=source,
                side=side, price=price, quantity=quantity,
            )
            if side in {"short", "sell"}:
                return _insert_short_open(
                    self,
                    symbol=symbol,
                    price=price,
                    quantity=quantity,
                    size_usd=size_usd,
                    fee=auth_fee,
                    order_id=order_id,
                    position_id=position_id,
                    user_id=user_id,
                    notes=corrected_notes,
                    platform_trade_id=platform_trade_id,
                )
            LOGGER.critical(
                "AUTHORITATIVE_FEE_LEDGER_V329_LONG_OPEN marker=%s user=%s symbol=%s old_fee=%.8f new_fee=%.8f rate=%.8f source=%s",
                MARKER, user_id, symbol, _f(fee), auth_fee, rate, source,
            )
            return current_buy(
                self, symbol, price, quantity, size_usd, auth_fee,
                order_id, position_id, user_id, corrected_notes, platform_trade_id,
            )

        setattr(record_entry_with_authoritative_fee, _PATCH_ATTR, True)
        setattr(record_entry_with_authoritative_fee, "__wrapped__", current_buy)
        cls.record_buy = record_entry_with_authoritative_fee

    current_open = getattr(cls, "open_position", None)
    if not callable(current_open):
        return False
    if not getattr(current_open, _PATCH_ATTR, False):
        @wraps(current_open)
        def open_position_with_authoritative_fee(
            self,
            position_id: str,
            symbol: str,
            side: str,
            entry_price: float,
            quantity: float,
            size_usd: float,
            stop_loss: float = None,
            take_profit_1: float = None,
            take_profit_2: float = None,
            take_profit_3: float = None,
            entry_fee: float = 0.0,
            user_id: str = "platform",
            notes: str = None,
            position_source: str = "nija_strategy",
        ) -> bool:
            if _ENTRY_CONTEXT.get():
                auth_fee, rate, source = _current_authoritative_fee(symbol, size_usd)
                entry_fee = auth_fee
                notes = _append_notes(
                    notes, fee=auth_fee, rate=rate, source=source,
                    side=_norm(side), price=entry_price, quantity=quantity,
                )
            return current_open(
                self, position_id, symbol, side, entry_price, quantity, size_usd,
                stop_loss, take_profit_1, take_profit_2, take_profit_3,
                entry_fee, user_id, notes, position_source,
            )

        setattr(open_position_with_authoritative_fee, _PATCH_ATTR, True)
        setattr(open_position_with_authoritative_fee, "__wrapped__", current_open)
        cls.open_position = open_position_with_authoritative_fee
    return True


def _patch_execution_engine() -> bool:
    try:
        module = importlib.import_module("bot.execution_engine")
        cls = getattr(module, "ExecutionEngine", None)
    except Exception:
        return False
    if cls is None:
        return False
    current = getattr(cls, "execute_entry", None)
    if not callable(current):
        return False
    if getattr(current, _PATCH_ATTR, False):
        return True

    @wraps(current)
    def execute_entry_with_fee_context(
        self,
        symbol: str,
        side: str,
        position_size: float,
        entry_price: float,
        stop_loss: float,
        take_profit_levels,
        *args,
        **kwargs,
    ):
        ctx = {
            "broker_client": getattr(self, "broker_client", None),
            "user_id": str(getattr(self, "user_id", "") or "platform"),
            "symbol": symbol,
            "side": side,
            "size_usd": _f(position_size),
        }
        token = _ENTRY_CONTEXT.set(ctx)
        try:
            position = current(
                self, symbol, side, position_size, entry_price, stop_loss,
                take_profit_levels, *args, **kwargs,
            )
            if isinstance(position, dict) and position:
                size = max(0.0, _f(position.get("position_size"), position_size))
                fee, rate, source = _current_authoritative_fee(symbol, size)
                price = max(0.0, _f(position.get("entry_price"), entry_price))
                qty = max(0.0, _f(position.get("quantity"), 0.0))
                position["entry_fee"] = fee
                position["entry_fee_rate"] = rate
                position["entry_fee_source"] = source
                position["executed_cost"] = price * qty + fee
                try:
                    stored = getattr(self, "positions", {}).get(symbol)
                    if isinstance(stored, dict):
                        stored.update(
                            entry_fee=fee,
                            entry_fee_rate=rate,
                            entry_fee_source=source,
                            executed_cost=price * qty + fee,
                        )
                except Exception:
                    pass
                LOGGER.critical(
                    "AUTHORITATIVE_FEE_LEDGER_V329_POSITION_CORRECTED marker=%s user=%s symbol=%s side=%s fee=%.8f rate=%.8f source=%s",
                    MARKER, ctx["user_id"], symbol, side, fee, rate, source,
                )
            return position
        finally:
            _ENTRY_CONTEXT.reset(token)

    setattr(execute_entry_with_fee_context, _PATCH_ATTR, True)
    setattr(execute_entry_with_fee_context, "__wrapped__", current)
    cls.execute_entry = execute_entry_with_fee_context
    return True


def install_import_hook() -> bool:
    with _LOCK:
        outcomes = {
            "ledger_entry_fee_and_side": _patch_ledger(),
            "in_memory_entry_fee": _patch_execution_engine(),
        }
        ready = all(outcomes.values())
        os.environ["NIJA_RUNTIME_AUTHORITATIVE_FEE_LEDGER_V329_READY"] = "1" if ready else "0"
        if ready:
            LOGGER.critical(
                "RUNTIME_AUTHORITATIVE_FEE_LEDGER_V329_READY marker=%s outcomes=%s "
                "runtime_fee_first=true canonical_fee_fallback=true short_entry_sell_open=true "
                "numeric_entry_fee_corrected=true executed_cost_corrected=true order_submission_unchanged=true "
                "safety_gates_bypassed=false",
                MARKER, outcomes,
            )
        else:
            LOGGER.critical(
                "RUNTIME_AUTHORITATIVE_FEE_LEDGER_V329_INCOMPLETE marker=%s outcomes=%s fail_closed_execution_unchanged=true",
                MARKER, outcomes,
            )
        return ready


def install() -> bool:
    return install_import_hook()


__all__ = ["MARKER", "install", "install_import_hook", "_fee_rate"]
