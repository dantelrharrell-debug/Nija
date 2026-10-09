"""Private, read-only confirmed trade history for users in any permitted region.

Country of residence never grants broker permissions. This reporting layer does
not place orders, convert currencies or change live execution authority.
"""
from __future__ import annotations

import math
import re
from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

BROKERS = ("kraken", "coinbase", "okx", "alpaca")
_BROKER_FIELD = re.compile(r"(?:^|;\s*)broker=([a-z0-9_]+)(?=;|$)")


def _timestamp(value: Any, zone: ZoneInfo) -> tuple[str, str]:
    stamp = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if stamp.tzinfo is None:
        # The canonical ledger writes datetime.utcnow() without an offset.
        stamp = stamp.replace(tzinfo=timezone.utc)
    return stamp.astimezone(timezone.utc).isoformat(), stamp.astimezone(zone).isoformat()


def get_user_confirmed_history(
    ledger: Any, *, user_id: str, limit: int = 50, offset: int = 0,
    timezone_name: str = "UTC", broker: str | None = None,
) -> dict[str, Any]:
    """Read only one authenticated owner's canonical confirmed closed trades.

    Pagination applies to eligible close rows before validation. Invalid rows are
    explicitly counted; next_offset advances over them so they cannot trap a
    client on a page. Raw notes and other owners' records are never returned.
    """
    user_id = str(user_id or "").strip()
    if not user_id or user_id == "platform":
        raise ValueError("customer identity required")
    if isinstance(limit, bool) or isinstance(offset, bool):
        raise ValueError("invalid pagination")
    limit, offset = int(limit), int(offset)
    if not 1 <= limit <= 200 or not 0 <= offset <= 100000:
        raise ValueError("limit must be 1..200 and offset 0..100000")
    if broker is not None and broker not in BROKERS:
        raise ValueError("unsupported broker")
    try:
        zone = ZoneInfo(timezone_name)
    except (ZoneInfoNotFoundError, ValueError, TypeError) as exc:
        raise ValueError("invalid IANA timezone") from exc
    with ledger._get_connection() as conn:
        rows = conn.execute(
            """SELECT c.* FROM completed_trades c
               WHERE c.user_id = ? AND c.exit_reason = 'canonical_confirmed_fill'
                 AND EXISTS (SELECT 1 FROM trade_ledger l
                     WHERE l.user_id = c.user_id AND l.position_id = c.position_id
                       AND l.action = 'CLOSE' AND COALESCE(l.order_id, '') != '')
               ORDER BY c.exit_time DESC, c.id DESC LIMIT ? OFFSET ?""",
            (user_id, limit + 1, offset),
        ).fetchall()
        selected = [dict(row) for row in rows[:limit]]
        proofs = {}
        for row in selected:
            proofs[row["position_id"]] = conn.execute(
                """SELECT order_id, notes FROM trade_ledger
                   WHERE user_id = ? AND position_id = ? AND action = 'CLOSE'""",
                (user_id, row["position_id"]),
            ).fetchall()
    trades = []
    excluded = 0
    for row in selected:
        try:
            identities = set()
            orders = set()
            for proof in proofs[row["position_id"]]:
                fields = _BROKER_FIELD.findall(str(proof[1] or ""))
                if len(fields) != 1 or fields[0] not in BROKERS or not str(proof[0] or "").strip():
                    raise ValueError("unproven close identity")
                identities.add(fields[0])
                orders.add(str(proof[0]))
            if len(identities) != 1:
                raise ValueError("ambiguous close identity")
            venue = identities.pop()
            if broker is not None and venue != broker:
                continue
            numbers = {key: float(row[key]) for key in (
                "entry_price", "exit_price", "quantity", "entry_fee", "exit_fee",
                "total_fees", "gross_profit", "net_profit",
            )}
            if not all(math.isfinite(v) for v in numbers.values()):
                raise ValueError("nonfinite trade")
            if any(numbers[k] < 0 for k in ("entry_fee", "exit_fee", "total_fees")):
                raise ValueError("invalid fees")
            if not math.isclose(numbers["total_fees"], numbers["entry_fee"] + numbers["exit_fee"], abs_tol=1e-6):
                raise ValueError("fee mismatch")
            if not math.isclose(numbers["net_profit"], numbers["gross_profit"] - numbers["total_fees"], abs_tol=1e-6):
                raise ValueError("net mismatch")
            if min(numbers[k] for k in ("entry_price", "exit_price", "quantity")) <= 0:
                raise ValueError("invalid execution values")
            side = str(row["side"]).lower()
            if side not in {"long", "short", "buy", "sell"}:
                raise ValueError("unknown direction")
            entry_utc, entry_local = _timestamp(row["entry_time"], zone)
            exit_utc, exit_local = _timestamp(row["exit_time"], zone)
            symbol = str(row["symbol"])
            quote = symbol.rsplit("-", 1)[-1] if "-" in symbol else "USD" if venue == "alpaca" else None
            trades.append({
                "position_id": row["position_id"], "symbol": symbol, "broker": venue,
                "direction": "long" if side in {"buy", "long"} else "short",
                **numbers, "price_currency": quote, "pnl_currency": None, "pnl_currency_verified": False,
                "pnl_basis": "recorded_execution_fees", "fx_conversion_verified": False,
                "carry_costs_verified": False, "execution_status": "confirmed_closed",
                "close_order_ids": sorted(orders), "entry_time_utc": entry_utc,
                "exit_time_utc": exit_utc, "entry_time_local": entry_local,
                "exit_time_local": exit_local,
            })
        except (ValueError, TypeError, KeyError, OverflowError):
            excluded += 1
    return {
        "user_id": user_id, "trades": trades, "count": len(trades),
        "limit": limit, "offset": offset, "next_offset": offset + len(selected),
        "has_more": len(rows) > limit, "timezone": timezone_name,
        "excluded_unverified_rows": excluded,
        "source": "canonical_confirmed_close_ledger", "orders_submitted": False,
        "country_eligibility_verified": False,
    }


def get_user_access_status(user_id: str) -> dict[str, Any]:
    """Report entitlement separately from unproven account execution readiness.

    An API/gateway process does not possess the trading writer's account-scoped
    fresh broker permissions and execution proof. Entitlement alone is never
    advertised as a running international trading account.
    """
    from user_live_trading_access import evaluate_live_trading_access

    decision = evaluate_live_trading_access(user_id)
    return {
        "user_id": user_id, "trading_enabled": False, "engine_status": "unverified",
        "entitlement_allowed": decision.allowed,
        "blocker": decision.blocker if not decision.allowed else "account_execution_readiness_unverified",
        "connected_brokers": list(decision.brokers),
        "account_execution_readiness_verified": False,
        "country_eligibility_verified": False,
        "international_access": "broker_account_and_product_permissions_required",
    }
