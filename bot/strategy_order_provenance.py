"""Account-scoped strategy intent attached to a genuine pipeline order identifier.

The pipeline ACK is never fill evidence.  This table is an audit breadcrumb
only; confirmed performance requires a separate authenticated broker OPEN and
fee-verified CLOSE in the canonical trade ledger. No orders or risk mutations.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Any, Mapping

LOGGER = logging.getLogger("nija.strategy_order_provenance")
_STRATEGY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,79}$")


def _owner_scope(account: Any, broker: str) -> tuple[str, str]:
    raw = str(account or "").strip()
    if raw.lower() in {"platform", "master", "platform:" + broker}:
        return "platform:" + broker, "platform"
    parts = raw.split(":")
    if (
        len(parts) == 3 and parts[0].lower() == "user"
        and parts[1].strip() and parts[2].lower() == broker
    ):
        return raw, parts[1].strip()
    return "", ""


def record_pipeline_order_intent(request: Any, result: Any, *, ledger: Any = None) -> bool:
    """Record an immutable pipeline strategy claim; do not assert actual fills.

    The strategy label originates in the accepted execution request. Exact
    broker order and owner identity are required. Retried/conflicting order IDs
    are not reassigned to a new strategy. Missing ledger means no attribution.
    """
    if getattr(result, "success", None) is not True:
        return False
    meta = getattr(request, "metadata", None)
    meta = meta if isinstance(meta, Mapping) else {}
    intent_type = str(getattr(request, "intent_type", "") or meta.get("intent_type") or "").lower()
    effect = str(getattr(request, "position_effect", "") or meta.get("position_effect") or "").lower()
    if intent_type in {"exit", "close"} or effect in {"close", "reduce"}:
        return False

    broker = str(getattr(result, "broker", "") or getattr(request, "preferred_broker", "") or "").strip().lower()
    if broker != "kraken":
        # Only Kraken's authenticated QueryOrders OPEN path is certified here.
        return False
    order_id = str(getattr(result, "order_id", "") or "").strip()
    strategy = str(getattr(request, "strategy", "") or "").strip()
    symbol = str(getattr(request, "symbol", "") or "").strip().upper()
    side = str(getattr(request, "side", "") or "").strip().lower()
    if (
        not order_id or not symbol or side not in {"buy", "sell"}
        or not _STRATEGY.fullmatch(strategy)
        or strategy.lower() in {"unknown", "unknown_strategy", "heartbeat_trade", "manual"}
    ):
        return False
    account = getattr(request, "account_id", None)
    account_scope, user_id = _owner_scope(account, broker)
    if not account_scope:
        account_scope, user_id = _owner_scope(meta.get("account_scope"), broker)
    if not account_scope:
        LOGGER.info("STRATEGY_PROVENANCE_SKIPPED reason=account_scope_unproven broker=%s", broker)
        return False
    version_obj = getattr(request, "strategy_metadata", None)
    version_obj = version_obj if isinstance(version_obj, Mapping) else {}
    version = str(version_obj.get("strategy_version") or version_obj.get("version") or "").strip()
    if version and not _STRATEGY.fullmatch(version):
        version = ""
    signal_id = str(getattr(request, "intent_id", "") or "").strip()[:128]

    if ledger is None:
        from bot.trade_ledger_db import get_trade_ledger_db
        ledger = get_trade_ledger_db()
    if not callable(getattr(ledger, "_get_connection", None)):
        return False
    captured = datetime.now(timezone.utc).isoformat()
    try:
        with ledger._get_connection() as conn:
            conn.execute(
                """INSERT OR IGNORE INTO strategy_order_intents
                   (broker, account_scope, user_id, order_id, symbol, side,
                    strategy_id, strategy_version, signal_id, captured_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (broker, account_scope, user_id, order_id, symbol, side,
                 strategy, version, signal_id, captured),
            )
            current = conn.execute(
                """SELECT broker, account_scope, user_id, order_id, symbol, side,
                          strategy_id, strategy_version
                   FROM strategy_order_intents
                   WHERE broker = ? AND account_scope = ? AND order_id = ?""",
                (broker, account_scope, order_id),
            ).fetchone()
        same = current is not None and tuple(current) == (
            broker, account_scope, user_id, order_id, symbol, side, strategy, version,
        )
        if not same:
            LOGGER.error(
                "STRATEGY_PROVENANCE_CONFLICT broker=%s account=%s order_id=%s "
                "claim_overwrite=false realized_pnl_unchanged=true",
                broker, account_scope, order_id,
            )
            return False
        LOGGER.info(
            "STRATEGY_PROVENANCE_INTENT_RECORDED broker=%s account=%s order_id=%s "
            "strategy=%s version=%s confirmed_fill=false realized_pnl_unproven=true",
            broker, account_scope, order_id, strategy, version or "unversioned",
        )
        return True
    except Exception as exc:
        LOGGER.warning("STRATEGY_PROVENANCE_UNAVAILABLE reason=%s", type(exc).__name__)
        return False



def _canonical_symbol(symbol: Any) -> str:
    raw = str(symbol or "").strip().upper().split(":", 1)[0]
    compact = "".join(char for char in raw if char.isalnum())
    return {
        "XXBTZUSD": "BTCUSD", "XBTUSD": "BTCUSD",
        "XETHZUSD": "ETHUSD",
    }.get(compact, compact)


def resolve_confirmed_strategy_attribution(
    ledger: Any, *, broker: str, user_id: str, confirmed_closes: list[dict[str, Any]],
) -> dict[str, Any]:
    """Join validated confirmed closes with authenticated entry + pipeline intent.

    All missing, duplicated, inconsistent or historically untraceable strategy
    identities remain unattributed. The function does not write any accounting
    state and does not promote a pipeline ACK to fill evidence.
    """
    grouped: dict[tuple[str, str], list[float]] = {}
    unproven = 0
    counted = 0
    if broker != "kraken":
        return {"status": "unavailable", "attributed": 0,
                "unattributed": len(confirmed_closes), "strategies": []}
    try:
        with ledger._get_connection() as conn:
            for close in confirmed_closes:
                entry_rows = conn.execute(
                    """SELECT order_id, symbol, side, notes FROM trade_ledger
                       WHERE position_id = ? AND user_id = ? AND action = 'OPEN'
                         AND COALESCE(order_id, '') != ''""",
                    (str(close["position_id"]), user_id),
                ).fetchall()
                if len(entry_rows) != 1:
                    unproven += 1
                    continue
                entry = entry_rows[0]
                entry_id = str(entry["order_id"] or "")
                notes = str(entry["notes"] or "")
                if not notes.startswith("authenticated_kraken_queryorders_entry; "):
                    unproven += 1
                    continue
                direction = str(close["direction"] or "").lower()
                if (direction == "long" and entry["side"] != "BUY") or (
                    direction == "short" and entry["side"] != "SELL"
                ):
                    unproven += 1
                    continue
                if _canonical_symbol(entry["symbol"]) != _canonical_symbol(close["symbol"]):
                    unproven += 1
                    continue
                rows = conn.execute(
                    """SELECT account_scope, user_id, symbol, side,
                              strategy_id, strategy_version
                       FROM strategy_order_intents
                       WHERE broker = ? AND user_id = ? AND order_id = ?""",
                    (broker, user_id, entry_id),
                ).fetchall()
                if len(rows) != 1:
                    unproven += 1
                    continue
                provenance = rows[0]
                scope = str(provenance["account_scope"])
                if (
                    f"order_id={entry_id}" not in notes.split("; ")
                    or f"account={scope}" not in notes.split("; ")
                    or str(provenance["user_id"]) != user_id
                    or _canonical_symbol(provenance["symbol"]) != _canonical_symbol(close["symbol"])
                    or str(provenance["side"]).lower() != str(entry["side"]).lower()
                ):
                    unproven += 1
                    continue
                sid = str(provenance["strategy_id"] or "")
                version = str(provenance["strategy_version"] or "")
                if not _STRATEGY.fullmatch(sid):
                    unproven += 1
                    continue
                net = float(close["net_pnl_usd"])
                if not __import__("math").isfinite(net):
                    unproven += 1
                    continue
                grouped.setdefault((sid, version), []).append(net)
                counted += 1
    except Exception as exc:
        LOGGER.warning("STRATEGY_ATTRIBUTION_REPORT_UNAVAILABLE reason=%s", type(exc).__name__)
        return {"status": "unavailable", "attributed": 0,
                "unattributed": len(confirmed_closes), "strategies": []}
    result = []
    for (sid, version), values in grouped.items():
        wins = [v for v in values if v > 0]
        losses = [v for v in values if v < 0]
        result.append({
            "strategy_id": sid,
            "strategy_version": version or None,
            "provenance": "pipeline_order_id_joined_to_authenticated_open_and_confirmed_close",
            "trades": len(values),
            "wins": len(wins), "losses": len(losses),
            "net_pnl_usd": sum(values),
            "win_rate": len(wins) / len(values),
            "average_pnl_usd": sum(values) / len(values),
            "profit_factor": sum(wins) / -sum(losses) if losses else None,
        })
    result.sort(key=lambda row: (row["net_pnl_usd"], row["trades"]), reverse=True)
    return {
        "status": "verified_subset" if counted else "unavailable",
        "attributed": counted, "unattributed": unproven,
        "strategies": result,
        "performance_guaranteed": False,
        "missing_historical_provenance_imputed": False,
    }


__all__ = ["record_pipeline_order_intent", "resolve_confirmed_strategy_attribution"]
