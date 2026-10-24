"""Single-use exact Kraken order/trade readback for existing pending ledger rows.

Never creates a broker or nonce owner, alters orders or ledger, certifies account
ownership, changes safety flags, or authorizes trading. Requires a private
expiring exact_request.json and the already running authenticated Kraken client.
"""
from __future__ import annotations

import fcntl
import json
import logging
import math
import os
from pathlib import Path
import re
import sqlite3
import stat
import time
from typing import Any, Iterable, Mapping

from bot.durable_recovery_state import write_recovery_state
from bot.kraken_live_history_recovery import _private_regular, _request
from scripts.nija_kraken_readonly_history_collector_v441 import _broker_account_scope

LOGGER = logging.getLogger(__name__)
_ORDER_ID = re.compile(r"[A-Z0-9]{5,8}-[A-Z0-9]{4,8}-[A-Z0-9]{5,8}\Z")


class ExactReadDenied(ValueError):
    """Non-secret, fixed failure label."""


def _symbol(value: Any) -> str:
    raw = "".join(x for x in str(value or "").upper() if x.isalnum())
    return {"XETHZUSD": "ETHUSD", "XXBTZUSD": "BTCUSD",
            "XBTUSD": "BTCUSD"}.get(raw, raw)


def _pending(ledger: Path) -> dict[str, tuple[str, str]]:
    if (not ledger.is_absolute() or ledger.is_symlink()
            or not ledger.is_file()):
        raise ExactReadDenied("ledger_missing_or_unsafe")
    try:
        with sqlite3.connect(ledger.resolve().as_uri() + "?mode=ro",
                             uri=True, timeout=3) as db:
            db.execute("PRAGMA query_only=ON")
            db.execute("BEGIN")
            if db.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise ExactReadDenied("ledger_integrity_failed")
            columns = {r[1] for r in db.execute(
                'PRAGMA table_info("pending_kraken_closes")')}
            required = {"broker", "account_scope", "user_id", "order_id",
                        "state", "symbol", "side"}
            if not required.issubset(columns):
                raise ExactReadDenied("pending_schema_missing")
            rows = db.execute(
                "SELECT broker,account_scope,user_id,order_id,state,symbol,side "
                "FROM pending_kraken_closes"
            ).fetchall()
    except (sqlite3.Error, OSError):
        raise ExactReadDenied("ledger_read_failed") from None
    pending: dict[str, tuple[str, str]] = {}
    for broker, scope, owner, oid, state, symbol, side in rows:
        if broker != "kraken" or not isinstance(scope, str):
            raise ExactReadDenied("ledger_owner_ambiguous")
        parts = scope.split(":")
        if scope == "platform:kraken":
            expected = "platform"
        elif (len(parts) == 3 and parts[0] == "user"
              and parts[1] and parts[2] == "kraken"):
            expected = parts[1]
        else:
            raise ExactReadDenied("ledger_scope_ambiguous")
        if owner != expected or state not in ("pending", "reconciled"):
            raise ExactReadDenied("ledger_owner_or_state_invalid")
        if not isinstance(oid, str) or not _ORDER_ID.fullmatch(oid):
            raise ExactReadDenied("ledger_order_id_invalid")
        if scope != "platform:kraken" or state != "pending":
            continue
        if side not in ("buy", "sell") or not _symbol(symbol):
            raise ExactReadDenied("ledger_pair_side_invalid")
        if oid in pending:
            raise ExactReadDenied("duplicate_pending_order")
        pending[oid] = (_symbol(symbol), side)
    if not 1 <= len(pending) <= 30:
        raise ExactReadDenied("pending_count_outside_budget")
    return pending


def _query(broker: Any, category: Any, scope: str,
           endpoint: str, txids: list[str]) -> dict[str, Any]:
    if endpoint not in ("QueryOrders", "QueryTrades"):
        raise ExactReadDenied("endpoint_not_readonly")
    if not 1 <= len(txids) <= 50 or not all(_ORDER_ID.fullmatch(x) for x in txids):
        raise ExactReadDenied("query_id_budget_invalid")
    if _broker_account_scope(broker) != scope:
        raise ExactReadDenied("broker_scope_mismatch")
    call = getattr(broker, "_kraken_private_call", None)
    if not callable(call) or category is None:
        raise ExactReadDenied("broker_private_read_unavailable")
    params = {"txid": ",".join(txids), "trades": endpoint == "QueryOrders"}
    payload = call(endpoint, params, category=category)
    if _broker_account_scope(broker) != scope:
        raise ExactReadDenied("broker_scope_changed")
    if not isinstance(payload, Mapping) or payload.get("error") != []:
        raise ExactReadDenied("broker_read_failed")
    rows = payload.get("result")
    if not isinstance(rows, Mapping) or set(rows) != set(txids):
        raise ExactReadDenied("broker_exact_id_set_incomplete")
    try:
        return json.loads(json.dumps(dict(rows), allow_nan=False, sort_keys=True))
    except (ValueError, TypeError):
        raise ExactReadDenied("broker_result_not_json") from None


def _collect(broker: Any, category: Any,
             pending: dict[str, tuple[str, str]]) -> dict[str, Any]:
    orders = _query(broker, category, "platform:kraken", "QueryOrders", sorted(pending))
    tids: set[str] = set()
    for oid, order in orders.items():
        if not isinstance(order, dict) or not isinstance(order.get("descr"), dict):
            raise ExactReadDenied("order_metadata_missing")
        descr = order["descr"]
        if (descr.get("type") != pending[oid][1]
                or _symbol(descr.get("pair")) != pending[oid][0]):
            raise ExactReadDenied("order_identity_mismatch")
        try:
            quantity = float(order["vol_exec"])
        except (KeyError, TypeError, ValueError):
            raise ExactReadDenied("order_volume_missing") from None
        if not math.isfinite(quantity) or quantity <= 0:
            raise ExactReadDenied("order_unfilled")
        ids = order.get("trades")
        if not isinstance(ids, list) or not ids:
            raise ExactReadDenied("order_trades_missing")
        for tid in ids:
            if (not isinstance(tid, str) or not _ORDER_ID.fullmatch(tid)
                    or tid in tids):
                raise ExactReadDenied("trade_id_invalid_or_duplicate")
            tids.add(tid)
    if not 1 <= len(tids) <= 50:
        raise ExactReadDenied("trade_count_exceeds_budget")
    trades = _query(broker, category, "platform:kraken", "QueryTrades", sorted(tids))
    for tid, trade in trades.items():
        if not isinstance(trade, dict) or trade.get("ordertxid") not in pending:
            raise ExactReadDenied("trade_order_link_missing")
        oid = trade["ordertxid"]
        if (tid not in orders[oid]["trades"]
                or trade.get("type") != pending[oid][1]
                or _symbol(trade.get("pair")) != pending[oid][0]):
            raise ExactReadDenied("trade_identity_mismatch")
        try:
            numbers = [float(trade[k]) for k in ("price", "vol", "fee")]
        except (KeyError, ValueError, TypeError):
            raise ExactReadDenied("trade_price_quantity_fee_missing") from None
        if (not all(math.isfinite(x) for x in numbers)
                or numbers[0] <= 0 or numbers[1] <= 0 or numbers[2] < 0):
            raise ExactReadDenied("trade_price_quantity_fee_invalid")
    return {
        "orders": orders, "trades": trades,
        "order_count": len(orders), "trade_count": len(trades),
        "exact_trade_links_read": True,
        "broker_account_identity_independently_verified": False,
        "atomic_broker_ledger_snapshot_verified": False,
        "historical_lots_fees_reconciled": False,
        "protective_exits_verified": False,
        "execution_authorized": False,
    }


def collect_requested_exact_pending_orders(
    directory: Path, brokers: Iterable[Any], *, monitoring_category: Any,
    ledger_path: Path = Path("/data/trade_ledger.db"),
    now: float | None = None,
) -> bool:
    root = Path(directory)
    if not root.is_absolute() or root.is_symlink() or root.resolve() != root:
        raise ExactReadDenied("recovery_root_not_canonical")
    state = root.stat()
    if (not stat.S_ISDIR(state.st_mode) or state.st_uid != os.geteuid()
            or stat.S_IMODE(state.st_mode) & 0o077):
        raise ExactReadDenied("recovery_root_not_private")
    fd = os.open(root / "collector.lock",
                 os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        _private_regular(fd)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return False
        stamp = time.time() if now is None else now
        row = _request(root, stamp, filename="exact_request.json")
        if row is None:
            return False
        if row["account_scope"] != "platform:kraken" or row["max_pages"] != 1:
            raise ExactReadDenied("exact_request_scope_or_budget_invalid")
        matches = []
        for broker in brokers:
            try:
                if (_broker_account_scope(broker) == "platform:kraken"
                        and getattr(broker, "connected", False) is True
                        and all(broker is not prior for prior in matches)):
                    matches.append(broker)
            except (ValueError, AttributeError):
                continue
        if len(matches) != 1 or monitoring_category is None:
            return False
        identity = row["request_id"]
        claimed = root / (identity + ".exact.claimed.json")
        evidence = root / (identity + ".exact.evidence.json")
        if claimed.exists() or claimed.is_symlink() or evidence.exists() or evidence.is_symlink():
            raise ExactReadDenied("exact_request_replay")
        os.link(root / "exact_request.json", claimed, follow_symlinks=False)
        (root / "exact_request.json").unlink()
        dirfd = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(dirfd)
        finally:
            os.close(dirfd)
        if _request(root, stamp, filename=claimed.name) != row:
            raise ExactReadDenied("exact_claim_changed")
        try:
            pending = _pending(Path(ledger_path))
            report = _collect(matches[0], monitoring_category, pending)
            write_recovery_state(evidence, {
                "request_id": identity, "collection_succeeded": True,
                "account_scope": "platform:kraken",
                "evidence": report, "trading_authorized": False,
            })
            LOGGER.info("KRAKEN_EXACT_PENDING_EVIDENCE_VERIFIED orders=%d trades=%d "
                        "trading_authorized=false",
                        report["order_count"], report["trade_count"])
        except Exception as exc:
            code = str(exc) if type(exc) is ExactReadDenied else "unexpected_failure"
            write_recovery_state(evidence, {
                "request_id": identity, "collection_succeeded": False,
                "failure_code": code, "trading_authorized": False,
            })
            LOGGER.warning("KRAKEN_EXACT_PENDING_EVIDENCE_DENIED reason=%s "
                           "trading_authorized=false", code)
        return True
    finally:
        os.close(fd)
