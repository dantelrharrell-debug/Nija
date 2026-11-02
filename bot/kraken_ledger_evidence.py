"""Opt-in authoritative ledger evidence; no startup, registration or write paths.

The current TradeLedgerDB schema CANNOT certify this evidence: its fills lack
broker/account/API provenance and exchange trade IDs. This module never infers
those from user_id, notes, strategy intents or exchange-looking internal IDs.
It performs no migration. A separately reviewed persistence implementation must
populate the following additive contract before this reader can succeed:

* Every table below has broker, account_scope, api_key_sha256, account_sha256.
* trade_ledger retains user_id, symbol, side, action, quantity, size_usd, fee,
  position_id and adds exchange_trade_id, exchange_order_id. order_id is INTERNAL
  and is deliberately never used for exchange matching. One row per fill.
* open_positions retains user_id, position_id, symbol, side, quantity, status and
  adds stop_order_id, take_profit_order_id (actual exchange IDs, not price levels).
* ledger_open_orders stores exchange_order_id, pair, side, ordertype, price,
  volume, executed: independently persisted outstanding order intentions.
* pending_kraken_closes retains user_id, order_id, state, symbol, side and adds
  exchange_order_id, position_id, quantity, executed, fee. order_id is internal.
  Active 'pending' rows must still be open; 'reconciled' rows must be terminal,
  fully represented by persisted fills. Unknown states deny.
* ledger_evidence_state stores schema_version=1, revision, observed_at_epoch,
  history_from_genesis=1 and unresolved_submission_count=0. Its source timestamp
  is written by the persistence owner, NEVER refreshed by this reader.

The strict initial contract supports fully attributed long BTC/USD and ETH/USD
spot lots and quote-currency fees only. Deposited base assets, margin, other pairs, missing
opening basis and unknown assets deny rather than invent accounting. Full
authenticated Ledgers must balance from genesis and corroborate every fill.
The persistent root is an externally reviewed mount, not a durability claim;
backup/restore, P&L, and atomic exchange snapshots are NOT certified.

An out-of-band reviewer MUST approve the exact frozen binding object (including
the existing nonce-owning broker object and persistent path). A provider ID,
pins, a self-reported verified flag, or a configuration boolean is insufficient.
The review callback is a trusted application boundary, not a cryptographic
proof: an untrusted caller controlling it cannot establish reviewed identity.
No binding or reviewer is supplied by this module.

offline_ledger_schema_sql() exposes inert DDL for a SEPARATE certification
database, never a migration of the production trade ledger. It inserts no rows:
genesis, provenance, source revisions and history must be populated by a
separately reviewed offline persistence process, not this evidence reader.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import math
import re
import sqlite3
import time
import uuid
from collections import defaultdict
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, localcontext
from pathlib import Path
from typing import Any

MAX_ROWS = 10000
MAX_PAGES = 10
MAX_AGE = 60.0
_ORDER_ID = re.compile(r"O[A-Z0-9]{5}-[A-Z0-9]{5}-[A-Z0-9]{6}\Z")
_SCOPE_COLUMNS = {"broker", "account_scope", "api_key_sha256", "account_sha256"}
_COLUMNS = {
    "trade_ledger": {
        "user_id", "symbol", "side", "action", "quantity", "size_usd", "fee",
        "position_id", "exchange_trade_id", "exchange_order_id",
    },
    "open_positions": {
        "user_id", "position_id", "symbol", "side", "quantity", "status",
        "stop_order_id", "take_profit_order_id",
    },
    "ledger_open_orders": {
        "exchange_order_id", "pair", "side", "ordertype", "price", "volume", "executed",
    },
    "pending_kraken_closes": {
        "user_id", "exchange_order_id", "state", "symbol", "side", "position_id",
        "quantity", "executed", "fee",
    },
    "ledger_evidence_state": {
        "schema_version", "revision", "observed_at_epoch",
        "history_from_genesis", "unresolved_submission_count",
    },
}


def offline_ledger_schema_sql() -> tuple[str, ...]:
    """Return inert DDL for a separate offline certification SQLite database.

    This function performs no I/O and does not initialize, migrate, or populate
    TradeLedgerDB. Callers must never execute these statements against the
    production ledger. The isolated database reuses accounting table names so
    the read-only reader can inspect it without aliases or inferred provenance.

    All financial values are decimal TEXT, preserving exact authenticated
    amounts. Exchange identifiers are distinct from optional internal order_id.
    No defaults certify account ownership, history completeness or freshness.
    In particular, creating these tables alone never produces evidence: a
    separately reviewed persistence implementation must establish full history,
    lot allocation, outstanding intents, pending closes and authentic source
    timestamps before writing a ledger_evidence_state row transactionally.

    The returned statements intentionally contain no INSERT, PRAGMA, migration,
    attachment, connection, filesystem operation, or execution hook.
    """
    scope = (
        "broker TEXT NOT NULL, account_scope TEXT NOT NULL, "
        "api_key_sha256 TEXT NOT NULL, account_sha256 TEXT NOT NULL, "
    )
    schemas = {
        "trade_ledger": (
            "user_id TEXT NOT NULL, symbol TEXT NOT NULL, side TEXT NOT NULL, action TEXT NOT NULL, "
            "quantity TEXT NOT NULL, size_usd TEXT NOT NULL, fee TEXT NOT NULL, "
            "position_id TEXT NOT NULL, exchange_trade_id TEXT NOT NULL, exchange_order_id TEXT NOT NULL, "
            "order_id TEXT, "
            "PRIMARY KEY (broker, account_scope, api_key_sha256, account_sha256, exchange_trade_id)"
        ),
        "open_positions": (
            "user_id TEXT NOT NULL, position_id TEXT NOT NULL, symbol TEXT NOT NULL, side TEXT NOT NULL, "
            "quantity TEXT NOT NULL, status TEXT NOT NULL, stop_order_id TEXT NOT NULL, "
            "take_profit_order_id TEXT NOT NULL, "
            "PRIMARY KEY (broker, account_scope, api_key_sha256, account_sha256, position_id)"
        ),
        "ledger_open_orders": (
            "exchange_order_id TEXT NOT NULL, pair TEXT NOT NULL, side TEXT NOT NULL, ordertype TEXT NOT NULL, "
            "price TEXT NOT NULL, volume TEXT NOT NULL, executed TEXT NOT NULL, "
            "PRIMARY KEY (broker, account_scope, api_key_sha256, account_sha256, exchange_order_id)"
        ),
        "pending_kraken_closes": (
            "user_id TEXT NOT NULL, exchange_order_id TEXT NOT NULL, state TEXT NOT NULL, symbol TEXT NOT NULL, "
            "side TEXT NOT NULL, position_id TEXT NOT NULL, quantity TEXT NOT NULL, executed TEXT NOT NULL, "
            "fee TEXT NOT NULL, order_id TEXT, "
            "PRIMARY KEY (broker, account_scope, api_key_sha256, account_sha256, exchange_order_id)"
        ),
        "ledger_evidence_state": (
            "schema_version INTEGER NOT NULL, revision TEXT NOT NULL, observed_at_epoch REAL NOT NULL, "
            "history_from_genesis INTEGER NOT NULL, unresolved_submission_count INTEGER NOT NULL, "
            "PRIMARY KEY (broker, account_scope, api_key_sha256, account_sha256)"
        ),
    }
    return tuple(f'CREATE TABLE "{table}" ({scope}{columns})' for table, columns in schemas.items())


class KrakenLedgerDenied(ValueError):
    """Bounded non-sensitive refusal; transport and SQL exceptions are discarded."""


@dataclass(frozen=True, eq=False)
class ReviewedLedgerBinding:
    """Exact objects and pins for an external, independently reviewed binding."""

    broker: Any
    account: str
    provider_id: str
    api_key_sha256: str
    account_sha256: str
    ledger_path: Path
    persistent_root: Path
    monitoring_category: Any


def _require(condition: bool, code: str) -> None:
    if not condition:
        raise KrakenLedgerDenied(code)


def _number(value: Any, *, signed: bool = False) -> Decimal:
    _require(not isinstance(value, bool) and isinstance(value, (str, int, float, Decimal))
             and len(str(value)) <= 128, "amount_invalid")
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise KrakenLedgerDenied("amount_invalid") from None
    _require(number.is_finite() and (signed or number >= 0)
             and (not number or abs(number.adjusted()) <= 30), "amount_invalid")
    return number


def _stamp(value: Any, now: float) -> float:
    _require(not isinstance(value, bool) and isinstance(value, (float, int))
             and math.isfinite(value) and value > 0
             and 0 <= now - value <= MAX_AGE, "source_timestamp_invalid_or_stale")
    return float(value)


def _identifier(value: Any) -> bool:
    return (isinstance(value, str) and 0 < len(value) <= 128
            and all(32 < ord(char) < 127 for char in value))


def _exchange_id(value: Any) -> str:
    _require(isinstance(value, str) and _ORDER_ID.fullmatch(value) is not None,
             "exchange_order_id_required")
    return value


def _canonical_scope(value: Any) -> bool:
    if value == "platform:kraken":
        return True
    if not _identifier(value):
        return False
    parts = value.split(":")
    return len(parts) == 3 and parts[0] == "user" and bool(parts[1]) and parts[2] == "kraken"


def _pair(value: Any) -> str:
    _require(isinstance(value, str), "pair_invalid")
    pair = value.upper().replace("-", "").replace("/", "")
    pair = {"XXBTZUSD": "BTCUSD", "XBTUSD": "BTCUSD", "XETHZUSD": "ETHUSD"}.get(pair, pair)
    _require(pair in {"BTCUSD", "ETHUSD"}, "unsupported_spot_pair")
    return pair


def _asset(value: Any) -> str:
    aliases = {"XXBT": "BTC", "XBT": "BTC", "BTC": "BTC",
               "XETH": "ETH", "ETH": "ETH", "ZUSD": "USD", "USD": "USD"}
    _require(isinstance(value, str) and value in aliases, "unsupported_balance_asset")
    return aliases[value]


def _orders(rows: Mapping, *, from_broker: bool) -> dict:
    output = {}
    for oid, row in rows.items():
        _exchange_id(oid)
        if from_broker:
            _require(row["status"] == "open", "open_order_state_invalid")
            desc = row["descr"]
            pair, side, kind, price = desc["pair"], desc["type"], desc["ordertype"], desc["price"]
            volume, executed = row["vol"], row["vol_exec"]
        else:
            pair, side, kind, price = row["pair"], row["side"], row["ordertype"], row["price"]
            volume, executed = row["volume"], row["executed"]
        qty, filled = _number(volume), _number(executed)
        _require(side in ("buy", "sell") and _identifier(kind) and qty > 0 and filled <= qty,
                 "open_order_terms_invalid")
        output[oid] = (_pair(pair), side, kind, _number(price), qty, filled)
    return output


def _routing_scope(broker: Any) -> str:
    kind, account_type = getattr(broker, "broker_type", None), getattr(broker, "account_type", None)
    kind, account_type = getattr(kind, "value", kind), getattr(account_type, "value", account_type)
    owner = getattr(broker, "user_id", object())
    _require(kind == "kraken" and getattr(broker, "connected", False) is True,
             "authenticated_client_unavailable")
    if account_type == "platform" and owner is None:
        return "platform:kraken"
    _require(account_type == "user" and _identifier(owner) and ":" not in owner,
             "broker_scope_unverified")
    return "user:" + owner + ":kraken"


def _private_reader(binding: ReviewedLedgerBinding) -> Callable:
    """Pin only the existing nonce-owning transport; never instantiate a client."""
    transport = getattr(binding.broker, "_kraken_private_call", None)
    _require(callable(transport) and binding.monitoring_category is not None, "authenticated_transport_required")

    def read(endpoint: str, params: dict) -> Mapping:
        history = endpoint in {"TradesHistory", "ClosedOrders", "Ledgers", "OpenOrders"}
        valid_keys = {"with_cursor", "cursor"}
        if endpoint in {"OpenOrders", "ClosedOrders"}:
            valid_keys.add("trades")
        if endpoint == "OpenOrders":
            valid_keys.add("limit")
        _require((history and set(params) <= valid_keys and params.get("with_cursor") is True)
                 or (endpoint in {"Balance", "GetApiKeyInfo"} and not params),
                 "non_read_only_request_denied")
        _require(_routing_scope(binding.broker) == binding.account
                 and getattr(binding.broker, "_kraken_private_call", None) == transport,
                 "broker_scope_or_transport_changed")
        wire = dict(params)
        # Match the inspected direct krakenex form wire contract (v490).
        if history and getattr(binding.broker, "_gateway_url", None) == "" \
                and getattr(binding.broker, "_gateway_only_mode", False) is not True:
            wire["with_cursor"] = "true"
            if type(wire.get("trades")) is bool:
                wire["trades"] = "true" if wire["trades"] else "false"
        response = transport(endpoint, wire, category=binding.monitoring_category)
        _require(_routing_scope(binding.broker) == binding.account
                 and getattr(binding.broker, "_kraken_private_call", None) == transport,
                 "broker_scope_or_transport_changed")
        _require(isinstance(response, Mapping) and response.get("error") == []
                 and isinstance(response.get("result"), Mapping), "authenticated_response_invalid")
        # Freeze transport-owned data, rejecting NaNs and arbitrary objects.
        return json.loads(json.dumps(response["result"], allow_nan=False))

    return read


def _identity(read: Callable, binding: ReviewedLedgerBinding, now: float) -> None:
    row = read("GetApiKeyInfo", {})
    key, iban = row.get("apiKey"), row.get("iban")
    _require(isinstance(key, str) and 0 < len(key) <= 512
             and isinstance(iban, str) and 0 < len(iban) <= 128
             and all(32 <= ord(char) < 127 for char in iban), "authenticated_identity_invalid")
    key_hash = hashlib.sha256(key.encode()).hexdigest()
    account_hash = hashlib.sha256(("kraken\0" + iban.strip().upper()).encode()).hexdigest()
    _require(hmac.compare_digest(key_hash, binding.api_key_sha256)
             and hmac.compare_digest(account_hash, binding.account_sha256),
             "authenticated_identity_pin_mismatch")
    expiry = row.get("validUntil")
    _require(not isinstance(expiry, bool) and isinstance(expiry, (str, int))
             and len(str(expiry)) <= 20 and str(expiry).isdigit()
             and (int(expiry) == 0 or int(expiry) > now), "authenticated_key_expired_or_invalid")


def _collect(read: Callable, max_pages: int) -> dict:
    """Full cursor exhaustion, repeated history/orders, balance brackets (v441)."""
    def pages(endpoint: str, field: str) -> dict:
        rows, seen = {}, set()
        params = {"with_cursor": True}
        if endpoint in {"ClosedOrders", "OpenOrders"}:
            params["trades"] = True
        if endpoint == "OpenOrders":
            params["limit"] = 50
        for _ in range(max_pages):
            payload = read(endpoint, params)
            batch, cursor = payload.get(field), payload.get("cursor")
            _require(isinstance(batch, Mapping) and len(batch) <= 50
                     and isinstance(cursor, Mapping) and not set(cursor) - {"next"},
                     "history_pagination_invalid")
            for identifier, row in batch.items():
                _require(_identifier(identifier) and isinstance(row, Mapping)
                         and identifier not in rows, "history_record_invalid_or_duplicate")
                rows[identifier] = row
            nxt = cursor.get("next")
            if nxt is None or nxt == "":
                return rows
            _require(_identifier(nxt) and nxt not in seen and bool(batch), "history_pagination_invalid")
            seen.add(nxt)
            params = {**params, "cursor": nxt}
        raise KrakenLedgerDenied("history_page_budget_exceeded")

    def history() -> dict:
        return {field: pages(endpoint, field) for endpoint, field in (
            ("TradesHistory", "trades"), ("ClosedOrders", "closed"), ("Ledgers", "ledger"),
        )}

    balance = read("Balance", {})
    first = history()
    _require(first == history(), "authenticated_history_changed")
    orders = pages("OpenOrders", "open")
    _require(orders == pages("OpenOrders", "open"), "authenticated_open_orders_changed")
    _require(balance == read("Balance", {}), "authenticated_balances_changed")
    return {"history": first, "open_orders": orders, "balance": balance}


def _file_identity(path: Path) -> tuple[int, int, int, int]:
    stat = path.stat()
    return stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns


def _open(binding: ReviewedLedgerBinding) -> tuple[sqlite3.Connection, Path, tuple]:
    path, root = Path(binding.ledger_path), Path(binding.persistent_root)
    _require(path.is_absolute() and root.is_absolute() and not path.is_symlink(),
             "persistent_ledger_path_unverified")
    resolved, root = path.resolve(strict=True), root.resolve(strict=True)
    _require(path == resolved and root in resolved.parents and resolved.is_file(),
             "persistent_ledger_path_unverified")
    before = _file_identity(resolved)
    db = sqlite3.connect(resolved.as_uri() + "?mode=ro", uri=True, timeout=1)
    try:
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA query_only=ON")
        # Bound integrity checking and unexpected pathological schemas.
        steps = [0]

        def budget() -> int:
            steps[0] += 1
            return int(steps[0] > 20000)

        db.set_progress_handler(budget, 1000)
        _require(db.execute("PRAGMA quick_check").fetchone()[0] == "ok", "ledger_integrity_failed")
        return db, resolved, before
    except Exception:
        db.close()
        raise


def _snapshot(db: sqlite3.Connection, binding: ReviewedLedgerBinding, now: float) -> dict:
    """Read the real scoped tables atomically, without initializing TradeLedgerDB."""
    output = {}
    db.execute("BEGIN")
    try:
        tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        # Report absent provenance explicitly even on a legacy empty ledger.
        for table, fields in _COLUMNS.items():
            _require(table in tables, "ledger_schema_contract_missing")
            columns = {row[1] for row in db.execute(f'PRAGMA table_info("{table}")')}
            _require(_SCOPE_COLUMNS <= columns, "ledger_broker_account_api_provenance_missing")
            _require(fields <= columns, "ledger_schema_contract_missing")
            # Null/blank provenance cannot safely be assigned to any account.
            invalid = db.execute(
                f'SELECT 1 FROM "{table}" WHERE broker IS NULL OR broker="" '  # nosec B608 -- static schema identifiers
                'OR account_scope IS NULL OR account_scope="" OR api_key_sha256 IS NULL '
                'OR api_key_sha256="" OR account_sha256 IS NULL OR account_sha256="" LIMIT 1'
            ).fetchone()
            _require(invalid is None, "ledger_row_provenance_missing")
            # A row belonging to this scope with another key is NOT silently filtered.
            wrong = db.execute(
                f'SELECT 1 FROM "{table}" WHERE account_scope=? AND '  # nosec B608 -- static schema identifiers
                '(broker<>? OR api_key_sha256<>? OR account_sha256<>?) LIMIT 1',
                (binding.account, "kraken", binding.api_key_sha256, binding.account_sha256),
            ).fetchone()
            _require(wrong is None, "ledger_scope_fingerprint_conflict")
            rows = db.execute(
                f'SELECT {",".join(sorted(fields))} FROM "{table}" '  # nosec B608 -- static schema identifiers
                'WHERE broker=? AND account_scope=? AND api_key_sha256=? AND account_sha256=? LIMIT ?',
                ("kraken", binding.account, binding.api_key_sha256, binding.account_sha256, MAX_ROWS + 1),
            ).fetchall()
            _require(len(rows) <= MAX_ROWS, "ledger_row_budget_exceeded")
            output[table] = sorted(
                [dict(row) for row in rows],
                key=lambda row: json.dumps(row, sort_keys=True, allow_nan=False),
            )
        states = output["ledger_evidence_state"]
        _require(len(states) == 1, "ledger_snapshot_state_missing_or_duplicate")
        state = states[0]
        _require(state["schema_version"] == 1 and state["history_from_genesis"] == 1
                 and state["unresolved_submission_count"] == 0
                 and _identifier(state["revision"]), "ledger_snapshot_state_unverified")
        _stamp(state["observed_at_epoch"], now)
        owner = "platform" if binding.account == "platform:kraken" else binding.account.split(":")[1]
        for table in ("trade_ledger", "open_positions", "pending_kraken_closes"):
            _require(all(row["user_id"] == owner for row in output[table]), "ledger_user_assignment_conflict")
        return output
    finally:
        db.execute("ROLLBACK")


def _reconcile(local: Mapping, observed: Mapping) -> tuple[dict, dict]:
    history, broker_open = observed["history"], observed["open_orders"]
    trades, closed = history["trades"], history["closed"]
    _require(not set(closed) & set(broker_open), "broker_order_state_conflict")
    all_orders = {**closed, **broker_open}
    fills = {}
    per_order = defaultdict(list)
    lots = defaultdict(lambda: Decimal("0"))
    lot_pairs = {}
    for row in local["trade_ledger"]:
        tid, oid, lot = row["exchange_trade_id"], _exchange_id(row["exchange_order_id"]), row["position_id"]
        _require(_identifier(tid) and tid.startswith("T") and tid not in fills
                 and _identifier(lot), "fill_or_position_identity_invalid")
        _require((row["side"], row["action"]) in {("BUY", "OPEN"), ("SELL", "CLOSE")},
                 "ledger_side_action_invalid")
        pair, qty = _pair(row["symbol"]), _number(row["quantity"])
        _require(qty > 0, "fill_quantity_invalid")
        terms = (oid, pair, row["side"].lower(), qty, _number(row["size_usd"]), _number(row["fee"]))
        fills[tid] = terms
        per_order[oid].append(tid)
        _require(lot not in lot_pairs or lot_pairs[lot] == pair, "position_pair_conflict")
        lot_pairs[lot] = pair
        lots[lot] += qty if row["side"] == "BUY" else -qty
    _require(set(fills) == set(trades), "ledger_broker_fill_set_mismatch")
    for tid, trade in trades.items():
        expected = fills[tid]
        _require(_number(trade.get("margin", "0")) == 0, "margin_history_unsupported")
        actual = (
            _exchange_id(trade["ordertxid"]), _pair(trade["pair"]), trade["type"],
            _number(trade["vol"]), _number(trade["cost"]), _number(trade["fee"]),
        )
        _require(actual == expected, "ledger_broker_fill_terms_mismatch")
        _require(actual[0] in all_orders, "fill_order_missing")
    for oid, order in all_orders.items():
        _exchange_id(oid)
        ids = order.get("trades", [])
        _require(isinstance(ids, list) and all(_identifier(tid) for tid in ids)
                 and len(set(ids)) == len(ids) and set(ids) == set(per_order[oid]),
                 "broker_order_fill_links_mismatch")
        qty = sum((fills[tid][3] for tid in ids), Decimal("0"))
        cost = sum((fills[tid][4] for tid in ids), Decimal("0"))
        fee = sum((fills[tid][5] for tid in ids), Decimal("0"))
        desc = order["descr"]
        pair, side = _pair(desc["pair"]), desc["type"]
        _require(desc.get("leverage", "none") in ("none", "0", 0), "margin_history_unsupported")
        _require(side in ("buy", "sell") and all(fills[tid][1:3] == (pair, side) for tid in ids),
                 "broker_order_fill_identity_mismatch")
        _require(qty == _number(order["vol_exec"]) and qty <= _number(order["vol"])
                 and cost == _number(order["cost"]) and fee == _number(order["fee"]),
                 "broker_order_fill_totals_mismatch")
        _require(order["status"] in ({"open"} if oid in broker_open else {"closed", "canceled", "expired"}),
                 "broker_order_status_invalid")
    expected_orders = {}
    for row in local["ledger_open_orders"]:
        oid = _exchange_id(row["exchange_order_id"])
        _require(oid not in expected_orders, "duplicate_ledger_open_order")
        expected_orders[oid] = {key: value for key, value in row.items() if key != "exchange_order_id"}
    _require(_orders(expected_orders, from_broker=False) == _orders(broker_open, from_broker=True),
             "ledger_broker_open_orders_mismatch")

    # Full authenticated balance ledger, including deposits/withdrawals. Never
    # equate a historical fill's time with the freshness of this observation.
    asset_totals = defaultdict(lambda: Decimal("0"))
    trade_cash = defaultdict(lambda: defaultdict(lambda: [Decimal("0"), Decimal("0")]))
    for entry in history["ledger"].values():
        asset, amount, fee = _asset(entry["asset"]), _number(entry["amount"], signed=True), _number(entry["fee"])
        asset_totals[asset] += amount - fee
        if entry["type"] == "trade":
            tid = entry["refid"]
            _require(tid in fills, "exchange_ledger_trade_link_missing")
            trade_cash[tid][asset][0] += amount
            trade_cash[tid][asset][1] += fee
    for tid, (_oid, pair, side, qty, cost, fee) in fills.items():
        base = pair[:-3]
        expected = {base: [qty if side == "buy" else -qty, Decimal("0")],
                    "USD": [-cost if side == "buy" else cost, fee]}
        _require(dict(trade_cash[tid]) == expected, "exchange_ledger_fill_amounts_or_fees_mismatch")
    balances = defaultdict(lambda: Decimal("0"))
    seen_assets = set()
    for raw_asset, amount in observed["balance"].items():
        asset = _asset(raw_asset)
        _require(asset not in seen_assets, "duplicate_balance_asset_alias")
        seen_assets.add(asset)
        balances[asset] = _number(amount)
    _require(all(asset_totals[asset] == balances[asset] for asset in set(asset_totals) | set(balances)),
             "exchange_ledger_balance_mismatch")
    positions, base_totals, used = {}, defaultdict(lambda: Decimal("0")), set()
    for row in local["open_positions"]:
        lot = row["position_id"]
        _require(_identifier(lot) and lot not in positions and row["status"] == "open"
                 and row["side"] == "long", "position_identity_or_state_invalid")
        qty, pair = _number(row["quantity"]), _pair(row["symbol"])
        _require(qty > 0 and lots[lot] == qty and lot_pairs.get(lot) == pair,
                 "ledger_position_fill_quantity_mismatch")
        stop, profit = _exchange_id(row["stop_order_id"]), _exchange_id(row["take_profit_order_id"])
        _require(stop != profit and not used & {stop, profit}, "protective_id_missing_or_reused")
        used.update((stop, profit))
        for oid, kinds in ((stop, {"stop-loss", "stop-loss-limit", "trailing-stop", "trailing-stop-limit"}),
                           (profit, {"take-profit", "take-profit-limit"})):
            order = broker_open.get(oid)
            _require(isinstance(order, Mapping), "protective_order_not_open")
            desc = order["descr"]
            _require(_pair(desc["pair"]) == pair and desc["type"] == "sell"
                     and desc["ordertype"] in kinds
                     and _number(order["vol"]) - _number(order["vol_exec"]) >= qty,
                     "protective_order_coverage_mismatch")
        positions[lot] = {"pair": pair, "side": "long", "quantity": str(qty),
                          "stop_order_id": stop, "take_profit_order_id": profit}
        base_totals[pair[:-3]] += qty
    _require(all(qty >= 0 and (qty == 0 or lot in positions) for lot, qty in lots.items()),
             "unaccounted_ledger_position")
    _require(all(base_totals[asset] == balances[asset] for asset in {"BTC", "ETH"}),
             "position_broker_balance_mismatch")
    pending_seen = set()
    for row in local["pending_kraken_closes"]:
        oid, lot = _exchange_id(row["exchange_order_id"]), row["position_id"]
        _require(oid not in pending_seen and lot in lots and row["side"] == "sell",
                 "pending_close_identity_invalid")
        pending_seen.add(oid)
        order = all_orders.get(oid)
        _require(isinstance(order, Mapping), "pending_close_order_missing")
        _require(_pair(row["symbol"]) == lot_pairs[lot] == _pair(order["descr"]["pair"])
                 and order["descr"]["type"] == "sell", "pending_close_identity_mismatch")
        _require(_number(row["quantity"]) == _number(order["vol"])
                 and _number(row["executed"]) == _number(order["vol_exec"])
                 and _number(row["fee"]) == _number(order["fee"]), "pending_close_terms_mismatch")
        _require((row["state"] == "pending" and oid in broker_open)
                 or (row["state"] == "reconciled" and oid in closed),
                 "pending_close_state_unresolved")
        if row["state"] == "pending":
            _require(lot in positions and _number(row["quantity"]) - _number(row["executed"]) <= lots[lot],
                     "pending_close_exceeds_position")
        for tid in per_order[oid]:
            _require(any(fill["exchange_trade_id"] == tid and fill["position_id"] == lot
                         for fill in local["trade_ledger"]), "pending_close_lot_mismatch")
    return positions, expected_orders


def make_kraken_ledger_evidence_provider(
    binding: ReviewedLedgerBinding, *,
    review_binding: Callable[[ReviewedLedgerBinding], bool],
    max_pages: int = MAX_PAGES,
    clock: Callable[[], float] = time.time,
) -> Callable[[], Mapping[str, Any]]:
    """Return one non-authorizing v452 ledger producer; never register it.

    review_binding must consult an out-of-band approved object binding, not
    merely inspect its strings. It is rechecked at observation time. No private
    requests occur during construction. All observation failures are redacted.
    """
    try:
        _require(type(binding) is ReviewedLedgerBinding and callable(review_binding)
                 and review_binding(binding) is True, "explicit_reviewed_binding_required")
        _require(_canonical_scope(binding.account) and _identifier(binding.provider_id)
                 and type(max_pages) is int and 1 <= max_pages <= MAX_PAGES
                 and callable(clock), "binding_or_read_budget_invalid")
        _require(all(isinstance(pin, str) and re.fullmatch(r"[a-f0-9]{64}", pin)
                     for pin in (binding.api_key_sha256, binding.account_sha256)), "reviewed_pins_required")
        read = _private_reader(binding)
    except KrakenLedgerDenied:
        raise
    except Exception:
        raise KrakenLedgerDenied("reviewed_binding_invalid") from None

    def observe() -> Mapping[str, Any]:
        db = None
        try:
            _require(review_binding(binding) is True, "reviewed_binding_revoked")
            started = _stamp(clock(), clock())
            db, path, file_before = _open(binding)
            version = db.execute("PRAGMA data_version").fetchone()[0]
            local = _snapshot(db, binding, clock())
            _identity(read, binding, clock())
            observed = _collect(read, max_pages)
            _identity(read, binding, clock())
            # Preserve exact small fees/partial fills even beside large balances.
            with localcontext() as decimal_context:
                decimal_context.prec = 256
                positions, orders = _reconcile(local, observed)
            finished = clock()
            _stamp(started, finished)
            _require(local == _snapshot(db, binding, finished)
                     and version == db.execute("PRAGMA data_version").fetchone()[0]
                     and file_before == _file_identity(path), "concurrent_ledger_change")
            _require(review_binding(binding) is True, "reviewed_binding_revoked")
            source_stamp = min(started, local["ledger_evidence_state"][0]["observed_at_epoch"])
            digest = hashlib.sha256(json.dumps(local, sort_keys=True, allow_nan=False).encode()).hexdigest()
            return {
                "account": binding.account, "verified": True, "read_only": True,
                "scope_verified": True, "source": "independent_ledger",
                "provider_id": binding.provider_id, "evidence_id": uuid.uuid4().hex,
                "observed_at_epoch": source_stamp, "authorizes_orders": False,
                "snapshot_id": digest, "snapshot_complete": True,
                "fills_reconciled": True, "positions_reconciled": True,
                "pending_closes_reconciled": True, "outstanding_intents_reconciled": True,
                "unresolved_submission_count": 0, "positions": positions, "orders": orders,
                "atomic_broker_snapshot_verified": False,
                "provenance": {
                    "account_scope_verified": True, "collector_identity_verified": True,
                    "snapshot_complete": True, "ledger_snapshot_verified": True,
                    "complete_pagination_verified": True,
                },
            }
        except KrakenLedgerDenied:
            raise
        except Exception:
            raise KrakenLedgerDenied("ledger_evidence_unavailable") from None
        finally:
            if db is not None:
                db.close()

    return observe


__all__ = [
    "KrakenLedgerDenied", "ReviewedLedgerBinding", "make_kraken_ledger_evidence_provider",
    "offline_ledger_schema_sql",
]
