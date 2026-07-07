"""Position close + realized P&L runtime patch."""

from __future__ import annotations

import builtins
import logging
from datetime import datetime
from typing import Any, Optional

logger = logging.getLogger("nija.position_close_pnl")
_LEDGER_PATCHED_ATTR = "__nija_position_close_pnl_ledger_patch__"
_ENGINE_PATCHED_ATTR = "__nija_position_close_pnl_engine_patch__"


def _f(value: Any, default: float = 0.0) -> float:
    try:
        out = float(value)
        return default if out != out else out
    except Exception:
        return default


def _sym(value: Any) -> str:
    return str(value or "").strip().upper().replace("/", "-").replace("_", "-")


def _side(value: Any) -> str:
    return str(value or "").strip().lower()


def _result(**kwargs: Any) -> dict[str, Any]:
    base = {
        "success": False,
        "position_id": "",
        "user_id": "",
        "symbol": "",
        "side": "",
        "entry_price": 0.0,
        "exit_price": 0.0,
        "quantity": 0.0,
        "size_usd": 0.0,
        "exit_value_usd": 0.0,
        "entry_fee": 0.0,
        "exit_fee": 0.0,
        "total_fees": 0.0,
        "gross_profit": 0.0,
        "net_profit": 0.0,
        "profit_pct": 0.0,
        "duration_seconds": 0.0,
        "exit_reason": "",
        "order_id": "",
        "broker": "",
        "ledger_exit_id": None,
        "error": "",
    }
    base.update(kwargs)
    return base


def _position_duration(entry_time_raw: Any) -> float:
    try:
        entry_time = datetime.fromisoformat(str(entry_time_raw or "").replace("Z", "+00:00"))
        now = datetime.now(entry_time.tzinfo) if entry_time.tzinfo else datetime.now()
        return max(0.0, (now - entry_time).total_seconds())
    except Exception:
        return 0.0


def _calculate(position: dict[str, Any], exit_price: float, exit_fee: float = 0.0) -> dict[str, Any]:
    entry_price = _f(position.get("entry_price"))
    quantity = _f(position.get("quantity"))
    size_usd = _f(position.get("size_usd"), entry_price * quantity)
    entry_fee = _f(position.get("entry_fee"))
    exit_value = quantity * exit_price
    if _side(position.get("side")) in {"long", "buy"}:
        gross = exit_value - size_usd
    else:
        gross = size_usd - exit_value
    total_fees = entry_fee + max(0.0, exit_fee)
    net = gross - total_fees
    pct = (net / size_usd * 100.0) if size_usd > 0 else 0.0
    return _result(
        success=True,
        position_id=str(position.get("position_id") or ""),
        user_id=str(position.get("user_id") or "platform"),
        symbol=_sym(position.get("symbol")),
        side=str(position.get("side") or ""),
        entry_price=entry_price,
        exit_price=exit_price,
        quantity=quantity,
        size_usd=size_usd,
        exit_value_usd=exit_value,
        entry_fee=entry_fee,
        exit_fee=max(0.0, exit_fee),
        total_fees=total_fees,
        gross_profit=gross,
        net_profit=net,
        profit_pct=pct,
        duration_seconds=_position_duration(position.get("entry_time")),
    )


def _find_position(ledger: Any, *, position_id: str = "", symbol: str = "", user_id: str = "") -> Optional[dict[str, Any]]:
    with ledger._get_connection() as conn:
        cur = conn.cursor()
        if position_id:
            cur.execute("SELECT * FROM open_positions WHERE position_id = ? AND status = 'open'", (position_id,))
            row = cur.fetchone()
            return dict(row) if row else None
        query = "SELECT * FROM open_positions WHERE status = 'open'"
        params: list[Any] = []
        if symbol:
            query += " AND UPPER(REPLACE(REPLACE(symbol, '/', '-'), '_', '-')) = ?"
            params.append(_sym(symbol))
        if user_id:
            query += " AND user_id = ?"
            params.append(user_id)
        query += " ORDER BY entry_time DESC LIMIT 1"
        cur.execute(query, params)
        row = cur.fetchone()
        return dict(row) if row else None


def _close_and_record(
    ledger: Any,
    *,
    position_id: str = "",
    symbol: str = "",
    user_id: str = "",
    exit_price: float = 0.0,
    exit_fee: float = 0.0,
    exit_reason: str = "manual_close",
    order_id: str = "",
    broker: str = "",
) -> dict[str, Any]:
    if _f(exit_price) <= 0:
        return _result(success=False, position_id=position_id, symbol=_sym(symbol), user_id=user_id, error="invalid_exit_price")
    try:
        with ledger._get_connection() as conn:
            cur = conn.cursor()
            if position_id:
                cur.execute("SELECT * FROM open_positions WHERE position_id = ? AND status = 'open'", (position_id,))
            else:
                query = "SELECT * FROM open_positions WHERE status = 'open'"
                params: list[Any] = []
                if symbol:
                    query += " AND UPPER(REPLACE(REPLACE(symbol, '/', '-'), '_', '-')) = ?"
                    params.append(_sym(symbol))
                if user_id:
                    query += " AND user_id = ?"
                    params.append(user_id)
                query += " ORDER BY entry_time DESC LIMIT 1"
                cur.execute(query, params)
                row = cur.fetchone()
                pos = dict(row) if row else None
                if not pos:
                    return _result(success=False, position_id=position_id, symbol=_sym(symbol), user_id=user_id, error="open_position_not_found")
                position_id = str(pos.get("position_id") or "")
                cur.execute("SELECT * FROM open_positions WHERE position_id = ? AND status = 'open'", (position_id,))
            row = cur.fetchone()
            if not row:
                return _result(success=False, position_id=position_id, symbol=_sym(symbol), user_id=user_id, error="open_position_not_found")
            pos = dict(row)
            pnl = _calculate(pos, _f(exit_price), _f(exit_fee))
            pnl.update(exit_reason=exit_reason, order_id=order_id, broker=broker)
            exit_side = "SELL" if _side(pos.get("side")) in {"long", "buy"} else "BUY"
            cur.execute(
                """
                INSERT INTO trade_ledger
                (timestamp, user_id, symbol, side, action, price, quantity, size_usd, fee,
                 order_id, position_id, platform_trade_id, notes)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    datetime.now().isoformat(), pnl["user_id"], pnl["symbol"], exit_side, "CLOSE",
                    pnl["exit_price"], pnl["quantity"], pnl["exit_value_usd"], pnl["exit_fee"],
                    order_id or None, pnl["position_id"], None,
                    f"exit_reason={exit_reason}; broker={broker}; net_pnl={pnl['net_profit']:.8f}; pnl_pct={pnl['profit_pct']:.4f}%",
                ),
            )
            pnl["ledger_exit_id"] = int(cur.lastrowid or 0)
            cur.execute(
                """
                INSERT OR REPLACE INTO completed_trades
                (position_id, user_id, symbol, side, entry_price, exit_price, quantity, size_usd,
                 entry_fee, exit_fee, total_fees, gross_profit, net_profit, profit_pct,
                 entry_time, exit_time, duration_seconds, exit_reason, notes)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    pnl["position_id"], pnl["user_id"], pnl["symbol"], pos.get("side"),
                    pnl["entry_price"], pnl["exit_price"], pnl["quantity"], pnl["size_usd"],
                    pnl["entry_fee"], pnl["exit_fee"], pnl["total_fees"], pnl["gross_profit"],
                    pnl["net_profit"], pnl["profit_pct"], pos.get("entry_time"),
                    datetime.now().isoformat(), pnl["duration_seconds"], exit_reason, pos.get("notes"),
                ),
            )
            cur.execute("DELETE FROM open_positions WHERE position_id = ?", (pnl["position_id"],))
        emoji = "🟢" if pnl["net_profit"] > 0 else "🔴" if pnl["net_profit"] < 0 else "⚪"
        logger.critical(
            "%s POSITION_CLOSED_PNL position_id=%s symbol=%s entry=%.8f exit=%.8f qty=%.8f net=%.8f pct=%+.4f%% reason=%s broker=%s",
            emoji, pnl["position_id"], pnl["symbol"], pnl["entry_price"], pnl["exit_price"],
            pnl["quantity"], pnl["net_profit"], pnl["profit_pct"], exit_reason, broker or "unknown",
        )
        print(f"[NIJA-PRINT] POSITION_CLOSED_PNL symbol={pnl['symbol']} net=${pnl['net_profit']:.4f} pct={pnl['profit_pct']:+.4f}% reason={exit_reason}", flush=True)
        return pnl
    except Exception as exc:
        logger.error("POSITION_CLOSE_PNL_FAILED position_id=%s symbol=%s err=%s", position_id, symbol, exc)
        return _result(success=False, position_id=position_id, symbol=_sym(symbol), user_id=user_id, error=str(exc))


def _patch_ledger(module: Any) -> bool:
    cls = getattr(module, "TradeLedgerDB", None)
    if not isinstance(cls, type) or getattr(cls, _LEDGER_PATCHED_ATTR, False):
        return False

    def get_open_position(self: Any, position_id: str = "", symbol: str = "", user_id: str = ""):
        return _find_position(self, position_id=position_id, symbol=symbol, user_id=user_id)

    def calculate_position_pnl(self: Any, position_id: str = "", symbol: str = "", user_id: str = "", exit_price: float = 0.0, exit_fee: float = 0.0):
        pos = _find_position(self, position_id=position_id, symbol=symbol, user_id=user_id)
        if not pos:
            return _result(success=False, position_id=position_id, symbol=_sym(symbol), user_id=user_id, error="open_position_not_found")
        return _calculate(pos, _f(exit_price), _f(exit_fee)) if _f(exit_price) > 0 else _result(success=False, position_id=str(pos.get("position_id") or ""), symbol=_sym(pos.get("symbol")), user_id=str(pos.get("user_id") or user_id), error="invalid_exit_price")

    def close_position_with_pnl(self: Any, **kwargs: Any):
        return _close_and_record(self, **kwargs)

    cls.get_open_position = get_open_position
    cls.calculate_position_pnl = calculate_position_pnl
    cls.close_position_with_pnl = close_position_with_pnl
    setattr(cls, _LEDGER_PATCHED_ATTR, True)
    logger.warning("POSITION_CLOSE_PNL_LEDGER_PATCHED")
    return True


def _patch_engine(module: Any) -> bool:
    cls = getattr(module, "ExecutionEngine", None)
    if not isinstance(cls, type) or getattr(cls, _ENGINE_PATCHED_ATTR, False):
        return False

    def close_position_with_pnl(self: Any, symbol: str = "", position_id: str = "", exit_price: float = 0.0, exit_fee: float = 0.0, exit_reason: str = "exit", order_id: str = "", broker: str = ""):
        ledger = getattr(self, "trade_ledger", None)
        if ledger is None:
            try:
                from bot.trade_ledger_db import get_trade_ledger_db
            except Exception:
                from trade_ledger_db import get_trade_ledger_db  # type: ignore
            ledger = get_trade_ledger_db()
            self.trade_ledger = ledger
        user_id = str(getattr(self, "user_id", "") or "platform")
        pnl = ledger.close_position_with_pnl(position_id=position_id, symbol=symbol, user_id=user_id, exit_price=exit_price, exit_fee=exit_fee, exit_reason=exit_reason, order_id=order_id, broker=broker)
        if not pnl.get("success") and not position_id:
            pnl = ledger.close_position_with_pnl(position_id=position_id, symbol=symbol, user_id="", exit_price=exit_price, exit_fee=exit_fee, exit_reason=exit_reason, order_id=order_id, broker=broker)
        try:
            if pnl.get("success"):
                self.positions.pop(_sym(pnl.get("symbol")), None)
        except Exception:
            pass
        return pnl

    cls.close_position_with_pnl = close_position_with_pnl
    cls.close_position_and_calculate_pnl = close_position_with_pnl
    setattr(cls, _ENGINE_PATCHED_ATTR, True)
    logger.warning("POSITION_CLOSE_PNL_ENGINE_PATCHED")
    return True


def install_import_hook() -> None:
    import sys
    for name in ("bot.trade_ledger_db", "trade_ledger_db"):
        mod = sys.modules.get(name)
        if mod is not None:
            _patch_ledger(mod)
    for name in ("bot.execution_engine", "execution_engine"):
        mod = sys.modules.get(name)
        if mod is not None:
            _patch_engine(mod)
    if getattr(builtins, "_NIJA_POSITION_CLOSE_PNL_IMPORT_HOOK", False):
        return
    original_import = builtins.__import__

    def guarded_import(name: str, globals=None, locals=None, fromlist=(), level: int = 0):
        mod = original_import(name, globals, locals, fromlist, level)
        try:
            if name.endswith("trade_ledger_db"):
                _patch_ledger(mod)
            if name.endswith("execution_engine"):
                _patch_engine(mod)
        except Exception as exc:
            logger.warning("POSITION_CLOSE_PNL_PATCH_FAILED module=%s err=%s", name, exc)
        return mod

    builtins.__import__ = guarded_import
    setattr(builtins, "_NIJA_POSITION_CLOSE_PNL_IMPORT_HOOK", True)
    logger.warning("POSITION_CLOSE_PNL_IMPORT_HOOK_INSTALLED")
