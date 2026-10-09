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


__all__ = ["record_pipeline_order_intent"]
