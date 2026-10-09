"""Read-only winner/loser reports from NIJA's existing confirmed-close ledger.

Reports keep broker and user ownership separate and read current fee-adjusted
values on every call. They never maintain a second P&L store, submit orders, or
change strategy weights/sizing. Borrow, funding and tax costs are not certified
by this ledger, so these figures are explicitly net of recorded execution fees.
"""
from __future__ import annotations

import logging
import math
from collections import defaultdict
from typing import Any

LOGGER = logging.getLogger("nija.confirmed_performance")


def _metrics(values: list[float]) -> dict[str, Any]:
    wins = [v for v in values if v > 0]
    losses = [v for v in values if v < 0]
    gross_wins = sum(wins)
    gross_losses = -sum(losses)
    return {
        "trades": len(values), "wins": len(wins), "losses": len(losses),
        "breakeven": sum(v == 0 for v in values),
        "win_rate": len(wins) / len(values) if values else 0.0,
        "net_pnl_usd": sum(values),
        "expectancy_usd": sum(values) / len(values) if values else 0.0,
        "profit_factor": gross_wins / gross_losses if gross_losses else None,
        "profit_factor_status": "finite" if gross_losses else "no_losses" if wins else "no_profit",
        "sample_status": "descriptive_only" if len(values) >= 20 else "insufficient_sample",
    }


def _confirmed_kraken_entry_from_ledger(
    ledger: Any, completed: Any, *, user_id: str,
) -> bool:
    """Closed P&L is reportable only with an exact authenticated OPEN leg."""
    position_id = str(completed[0] or "")
    symbol = str(completed[1] or "")
    side = str(completed[2] or "").lower()
    scope = "platform:kraken" if user_id == "platform" else f"user:{user_id}:kraken"
    try:
        with ledger._get_connection() as conn:
            opens = conn.execute(
                """SELECT symbol, side, order_id, price, quantity, size_usd,
                          fee, notes FROM trade_ledger
                   WHERE position_id=? AND user_id=? AND action='OPEN'""",
                (position_id, user_id),
            ).fetchall()
        if len(opens) != 1:
            return False
        entry = opens[0]
        notes = str(entry["notes"] or "")
        oid = str(entry["order_id"] or "")
        if not oid or not notes.startswith("authenticated_kraken_queryorders_entry; "):
            return False
        parts = notes.split("; ")
        if f"account={scope}" not in parts or f"order_id={oid}" not in parts:
            return False
        if (
            (side in {"long", "buy"} and entry["side"] != "BUY")
            or (side in {"short", "sell"} and entry["side"] != "SELL")
            or side not in {"long", "buy", "short", "sell"}
        ):
            return False
        key = lambda v: "".join(
            ch for ch in str(v or "").upper().split(":", 1)[0] if ch.isalnum()
        )
        aliases = {"XXBTZUSD": "BTCUSD", "XBTUSD": "BTCUSD", "XETHZUSD": "ETHUSD"}
        norm = lambda value: aliases.get(key(value), key(value))
        if norm(entry["symbol"]) != norm(symbol):
            return False
        for value, expected in (
            (entry["price"], completed[8]),
            (entry["quantity"], completed[9]),
            (entry["size_usd"], completed[10]),
            (entry["fee"], completed[6]),
        ):
            left, right = float(value), float(expected)
            if not math.isfinite(left) or not math.isfinite(right):
                return False
            if left < 0 or right < 0 or not math.isclose(
                left, right, rel_tol=1e-8, abs_tol=1e-7,
            ):
                return False
        return True
    except Exception as exc:
        LOGGER.warning(
            "CONFIRMED_KRAKEN_ENTRY_V435_UNPROVEN position_id=%s exception_type=%s "
            "historical_pnl_excluded=true",
            position_id, type(exc).__name__,
        )
        return False


def get_confirmed_performance_report(
    ledger: Any, *, broker: str, user_id: str, limit: int = 1000,
) -> dict[str, Any]:
    """Summarize at most ``limit`` confirmed closes for one explicit owner.

    Broker identity comes from the exact broker field in the close transaction's
    ledger notes. Unscoped, manual, fee-inconsistent and ambiguous closes cannot
    enter this report. Strategy attribution requires a distinct authenticated
    entry and account-scoped pipeline intent; unmatched history stays unknown.
    """
    broker = str(broker or "").strip().lower()
    user_id = str(user_id or "").strip()
    if not broker or not user_id or any(ch in broker for ch in ";%_ "):
        raise ValueError("explicit broker and user identity required")
    limit = max(1, min(int(limit), 10_000))
    with ledger._get_connection() as conn:
        # EXISTS avoids counting a position twice when duplicate recovery rows
        # are present. Requiring exactly one recorded broker prevents cross-venue
        # attribution of a reused position id. Account ownership is explicit.
        rows = conn.execute(
            """
            SELECT c.position_id, c.symbol, c.side, c.net_profit, c.gross_profit,
                   c.total_fees, c.entry_fee, c.exit_fee,
                   c.entry_price, c.quantity, c.size_usd
            FROM completed_trades c
            WHERE c.user_id = ? AND c.exit_reason = 'canonical_confirmed_fill'
              AND EXISTS (
                  SELECT 1 FROM trade_ledger l
                  WHERE l.position_id = c.position_id AND l.user_id = c.user_id
                    AND l.action = 'CLOSE' AND COALESCE(l.order_id, '') != ''
                    AND l.notes LIKE ?
              )
              AND NOT EXISTS (
                  SELECT 1 FROM trade_ledger l
                  WHERE l.position_id = c.position_id AND l.user_id = c.user_id
                    AND l.action = 'CLOSE' AND COALESCE(l.notes, '') NOT LIKE ?
              )
            ORDER BY c.exit_time DESC, c.id DESC LIMIT ?
            """,
            (user_id, f"%; broker={broker}; %", f"%; broker={broker}; %", limit),
        ).fetchall()
    buckets: dict[tuple[str, str], list[float]] = defaultdict(list)
    values: list[float] = []
    excluded = 0
    unproven_kraken_entry_count = 0
    verified_closes = []
    for row in rows:
        try:
            if broker == "kraken" and not _confirmed_kraken_entry_from_ledger(
                ledger, row, user_id=user_id,
            ):
                excluded += 1
                unproven_kraken_entry_count += 1
                continue
            net, gross, fees, entry_fee, exit_fee = map(float, row[3:8])
            if not all(math.isfinite(v) for v in (net, gross, fees, entry_fee, exit_fee)):
                raise ValueError("nonfinite P&L")
            if min(fees, entry_fee, exit_fee) < 0:
                raise ValueError("negative fees")
            if not math.isclose(fees, entry_fee + exit_fee, rel_tol=1e-8, abs_tol=1e-6):
                raise ValueError("fee mismatch")
            if not math.isclose(net, gross - fees, rel_tol=1e-8, abs_tol=1e-6):
                raise ValueError("net P&L mismatch")
            side = str(row[2] or "").strip().lower()
            if side in {"buy", "long"}:
                direction = "long"
            elif side in {"sell", "short"}:
                direction = "short"
            else:
                raise ValueError("unproven position direction")
            buckets[(str(row[1]), direction)].append(net)
            values.append(net)
            verified_closes.append({
                "position_id": str(row[0]), "symbol": str(row[1]),
                "direction": direction, "net_pnl_usd": net,
            })
        except (TypeError, ValueError):
            excluded += 1
    # Only an exact pipeline order intent + authenticated Kraken OPEN and
    # confirmed fee-verified CLOSE proves a strategy outcome. All older trades
    # with missing provenance are reported as unattributed, never guessed.
    try:
        from bot.strategy_order_provenance import resolve_confirmed_strategy_attribution
        attribution = resolve_confirmed_strategy_attribution(
            ledger, broker=broker, user_id=user_id, confirmed_closes=verified_closes,
        )
    except Exception:
        attribution = {"status": "unavailable", "attributed": 0,
                       "unattributed": len(verified_closes), "strategies": []}
    symbols = [{"symbol": symbol, "direction": direction, **_metrics(pnl)}
               for (symbol, direction), pnl in buckets.items()]
    storage = getattr(ledger, "storage_verification", None)
    if not isinstance(storage, dict):
        storage = {
            "state": "storage_evidence_unavailable",
            "dedicated_mount_detected": False,
            "restart_persistence_verified": False,
            "migration_integrity_verified": False,
            "backup_restore_verified": False,
            "ready_for_historical_pnl_certification": False,
        }
    pending_count = None
    if broker == "kraken":
        try:
            from bot.pending_kraken_close_audit_v434 import pending_summary
            exact_scope = (
                "platform:kraken" if user_id == "platform"
                else f"user:{user_id}:kraken"
            )
            pending_count = pending_summary(
                ledger, account_scope=exact_scope,
            )["pending_confirmed_closes"]
        except Exception:
            pending_count = None
    return {
        "broker": broker, "user_id": user_id,
        "source": "canonical_confirmed_close_ledger",
        "ledger_storage_evidence": dict(storage),
        "historical_ledger_durability_verified": False,
        "historical_fill_reconciliation_complete": False,
        "pending_confirmed_closes": pending_count,
        "cost_basis": "net_of_recorded_entry_and_exit_fees",
        "carry_costs_verified": False,
        "strategy_attribution": attribution["status"],
        "strategy_attribution_proven_closes": attribution["attributed"],
        "strategy_attribution_unproven_closes": attribution["unattributed"],
        "strategy_metrics": attribution["strategies"],
        "window_limit": limit, "window_may_be_truncated": len(rows) == limit,
        "excluded_invalid_rows": excluded,
        "excluded_kraken_closes_without_authenticated_open": unproven_kraken_entry_count,
        "overall": _metrics(values),
        "winners": sorted((s for s in symbols if s["net_pnl_usd"] > 0),
                          key=lambda s: s["net_pnl_usd"], reverse=True),
        "losers": sorted((s for s in symbols if s["net_pnl_usd"] < 0),
                         key=lambda s: s["net_pnl_usd"]),
        "symbols": symbols, "automatic_trading_changes": False,
    }


def log_confirmed_performance(ledger: Any, *, broker: str, user_id: str) -> None:
    """Emit a scoped report; reporting failures never alter fill or exit truth."""
    try:
        report = get_confirmed_performance_report(ledger, broker=broker, user_id=user_id)
        overall = report["overall"]
        LOGGER.info(
            "CONFIRMED_PERFORMANCE broker=%s user_id=%s trades=%d wins=%d losses=%d "
            "breakeven=%d net_usd=%.8f expectancy_usd=%.8f profit_factor=%s "
            "winners=%s losers=%s source=canonical_close_ledger carry_costs_verified=false",
            broker, user_id, overall["trades"], overall["wins"], overall["losses"],
            overall["breakeven"], overall["net_pnl_usd"], overall["expectancy_usd"],
            overall["profit_factor"],
            [s["symbol"] for s in report["winners"][:3]],
            [s["symbol"] for s in report["losers"][:3]],
        )
    except Exception as exc:
        LOGGER.warning("CONFIRMED_PERFORMANCE_UNAVAILABLE error=%s", type(exc).__name__)
