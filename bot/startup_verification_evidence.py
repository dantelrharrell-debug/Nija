"""Read-only Kraken startup evidence and a durable capital-bearing attempt latch.

The API helpers issue authenticated queries or AddOrder with validate=True only.
They never submit a real order, change readiness or publish execution proof.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import sqlite3
import time
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Mapping, Optional


class StartupEvidenceError(RuntimeError):
    """An exact authenticated broker fact or durable attempt state is unavailable."""


def _decimal(value: Any, *, nonnegative: bool = False) -> Decimal:
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise StartupEvidenceError("invalid_broker_decimal") from exc
    if not parsed.is_finite() or (nonnegative and parsed < 0):
        raise StartupEvidenceError("invalid_broker_decimal")
    return parsed


def _private_read(broker: Any, method: str, params: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    if method not in {"GetApiKeyInfo", "QueryOrders", "QueryTrades", "QueryLedgers", "Ledgers"}:
        raise StartupEvidenceError("private_query_not_allowlisted")
    call = getattr(broker, "_kraken_private_call", None)
    if not callable(call):
        raise StartupEvidenceError("serialized_kraken_query_unavailable")
    try:
        payload = call(method, dict(params or {}))
    except Exception:
        # Adapter exceptions may contain request headers or credential values.
        raise StartupEvidenceError(f"authenticated_query_failed:{method}") from None
    if not isinstance(payload, Mapping) or payload.get("error"):
        raise StartupEvidenceError(f"authenticated_query_rejected:{method}")
    result = payload.get("result")
    if not isinstance(result, Mapping):
        raise StartupEvidenceError(f"authenticated_result_missing:{method}")
    return dict(result)


@dataclass(frozen=True)
class StartupBrokerIdentity:
    """Authenticated account identity; legal owner verification is a separate check."""

    account_fingerprint: str
    api_key_fingerprint: str
    observed_at_epoch: float
    permissions: frozenset[str] = frozenset()


def read_startup_broker_identity(broker: Any) -> StartupBrokerIdentity:
    """Read account IIBAN from the exact adapter without exposing the API key."""
    broker_type = getattr(getattr(broker, "broker_type", None), "value", getattr(broker, "broker_type", ""))
    if str(broker_type).strip().lower() != "kraken":
        raise StartupEvidenceError("startup_identity_requires_kraken")
    info = _private_read(broker, "GetApiKeyInfo")
    iban = str(info.get("iban") or "").strip().upper()
    api_key = str(info.get("apiKey") or "").strip()
    if not iban or not api_key:
        raise StartupEvidenceError("authenticated_account_identity_missing")
    fingerprint = hashlib.sha256(("kraken\0" + iban).encode()).hexdigest()
    permissions = info.get("permissions")
    if not isinstance(permissions, list) or not all(isinstance(value, str) for value in permissions):
        raise StartupEvidenceError("authenticated_key_permissions_missing")
    return StartupBrokerIdentity(
        fingerprint,
        hashlib.scrypt(api_key.encode(), salt=b"NIJA startup key identity v1", n=16384, r=8, p=1).hex(),
        time.time(), frozenset(permissions),
    )


def platform_startup_candidates(candidates: Mapping[Any, Any], canonical: Mapping[Any, Any]) -> dict[Any, Any]:
    """Keep platform-owned startup adapters; an explicit USER role is never eligible."""
    canonical_ids = {id(value) for value in canonical.values() if value is not None}
    output: dict[Any, Any] = {}
    for key, candidate in candidates.items():
        if candidate is None:
            continue
        raw_role = getattr(candidate, "account_type", "")
        role = str(getattr(raw_role, "value", raw_role) or "").strip().lower()
        if role == "platform" or (not role and id(candidate) in canonical_ids):
            output[key] = candidate
    return output


def validate_readonly_startup_order(broker: Any, params: Mapping[str, Any]) -> dict[str, Any]:
    """Validate an order description without creating an order or execution proof."""
    identity = read_startup_broker_identity(broker)
    approved_keys = {"pair", "type", "ordertype", "volume", "price", "price2", "timeinforce",
                     "close[ordertype]", "close[price]", "close[price2]", "oflags", "cl_ord_id"}
    if set(params) - approved_keys - {"validate"}:
        raise StartupEvidenceError("readonly_order_parameter_not_allowlisted")
    data = {key: value for key, value in params.items() if key in approved_keys}
    if not all(data.get(key) for key in ("pair", "type", "ordertype", "volume")):
        raise StartupEvidenceError("readonly_order_description_incomplete")
    data["validate"] = True
    try:
        response = broker._kraken_private_call("AddOrder", data)
    except Exception:
        raise StartupEvidenceError("readonly_order_validation_failed") from None
    if not isinstance(response, Mapping) or response.get("error"):
        raise StartupEvidenceError("readonly_order_validation_rejected")
    result = response.get("result")
    # Even an empty txid is an unexpected response from validate-only AddOrder.
    # Reject the field's presence rather than its truthiness.
    if not isinstance(result, Mapping) or "txid" in result:
        raise StartupEvidenceError("readonly_validation_result_unexpected")
    description = result.get("descr")
    if not isinstance(description, Mapping) or not description.get("order"):
        raise StartupEvidenceError("readonly_validation_description_missing")
    return {
        "account_fingerprint": identity.account_fingerprint,
        "api_key_fingerprint": identity.api_key_fingerprint,
        "observed_at_epoch": identity.observed_at_epoch,
        "validation_only": True,
        "execution_proof": False,
        "orders_submitted": False,
        "conditional_close_validated": bool(description.get("close")),
        "ownership_verified": False,
        "all_in_cost_guaranteed": False,
        "real_money_approval_required": True,
    }


def _attempt_path(path: Optional[Path] = None) -> Path:
    resolved = path or Path(os.environ.get("NIJA_STARTUP_ATTEMPT_DB", "/data/startup_verification_attempts.db"))
    if not resolved.is_absolute():
        raise StartupEvidenceError("startup_attempt_path_must_be_absolute")
    return resolved


def _connect_attempts(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(str(path), timeout=5.0)
    connection.execute("PRAGMA synchronous=FULL")
    connection.execute("""CREATE TABLE IF NOT EXISTS startup_attempts (
        account_fingerprint TEXT PRIMARY KEY, account_alias TEXT NOT NULL, symbol TEXT NOT NULL,
        claimed_at REAL NOT NULL, state TEXT NOT NULL, entry_order_id TEXT NOT NULL DEFAULT '',
        exit_order_id TEXT NOT NULL DEFAULT '', evidence_json TEXT NOT NULL DEFAULT '{}')""")
    connection.commit()
    return connection


def claim_startup_attempt(identity: StartupBrokerIdentity, account_alias: str, symbol: str,
                          *, path: Optional[Path] = None) -> bool:
    """Atomically consume one account-scoped attempt; no automatic reset or expiry."""
    if (len(identity.account_fingerprint) != 64 or not account_alias or not symbol
            or not math.isfinite(identity.observed_at_epoch)
            or not 0 <= time.time() - identity.observed_at_epoch <= 30):
        raise StartupEvidenceError("startup_attempt_identity_invalid_or_stale")
    connection = None
    try:
        connection = _connect_attempts(_attempt_path(path))
        connection.execute("BEGIN IMMEDIATE")
        cursor = connection.execute(
            "INSERT OR IGNORE INTO startup_attempts "
            "(account_fingerprint, account_alias, symbol, claimed_at, state) VALUES (?, ?, ?, ?, ?)",
            (identity.account_fingerprint, account_alias, symbol, time.time(), "claimed"),
        )
        connection.commit()
        return cursor.rowcount == 1
    except (sqlite3.Error, OSError) as exc:
        raise StartupEvidenceError("durable_startup_attempt_unavailable") from exc
    finally:
        if connection is not None:
            connection.close()


def record_startup_attempt(identity: StartupBrokerIdentity, state: str, *, entry_order_id: str = "",
                           exit_order_id: str = "", evidence: Optional[Mapping[str, Any]] = None,
                           path: Optional[Path] = None) -> None:
    """Persist observed outcome without releasing the account's consumed attempt."""
    if state not in {"claimed", "entry_pending", "entry_filled", "exit_pending", "completed", "state_unknown"}:
        raise StartupEvidenceError("startup_attempt_state_invalid")
    target = _attempt_path(path)
    if not target.is_file():
        raise StartupEvidenceError("startup_attempt_record_missing")
    connection = None
    try:
        connection = sqlite3.connect(str(target), timeout=5.0)
        connection.execute("PRAGMA synchronous=FULL")
        cursor = connection.execute(
            "UPDATE startup_attempts SET state=?, "
            "entry_order_id=CASE WHEN ?!='' THEN ? ELSE entry_order_id END, "
            "exit_order_id=CASE WHEN ?!='' THEN ? ELSE exit_order_id END, evidence_json=? "
            "WHERE account_fingerprint=?",
            (state, entry_order_id, entry_order_id, exit_order_id, exit_order_id,
             json.dumps(dict(evidence or {}), allow_nan=False, sort_keys=True), identity.account_fingerprint),
        )
        if cursor.rowcount != 1:
            raise StartupEvidenceError("startup_attempt_record_missing")
        connection.commit()
    except (sqlite3.Error, OSError, ValueError, TypeError) as exc:
        raise StartupEvidenceError("durable_startup_outcome_unavailable") from exc
    finally:
        if connection is not None:
            connection.close()


def startup_attempts_allow_execution_proof(*, path: Optional[Path] = None) -> bool:
    """Withhold activation proof until every consumed startup attempt is reconciled."""
    connection = None
    try:
        target = _attempt_path(path)
        if not target.exists():
            return True
        connection = sqlite3.connect(target.as_uri() + "?mode=ro", uri=True, timeout=1.0)
        connection.execute("PRAGMA query_only=ON")
        # A bare 'completed' flag is not execution evidence. Both genuine
        # broker order IDs must be recorded before the startup attempt can
        # stop vetoing activation. This predicate does not itself create proof:
        # the canonical fill/ledger and protective-exit gates remain required.
        row = connection.execute(
            "SELECT COUNT(*) FROM startup_attempts "
            "WHERE state != 'completed' "
            "OR TRIM(entry_order_id) = '' "
            "OR TRIM(exit_order_id) = ''"
        ).fetchone()
        return row is not None and row[0] == 0
    except (StartupEvidenceError, sqlite3.Error, OSError):
        return False
    finally:
        if connection is not None:
            connection.close()


@dataclass(frozen=True)
class StartupFillEvidence:
    """Exact order/trade/ledger facts from one authenticated Kraken account."""

    order_id: str
    side: str
    gross_base_quantity: Decimal
    net_base_delta: Decimal
    quote_delta: Decimal
    execution_epoch: float


def _asset_variants(asset: str) -> set[str]:
    asset = asset.upper()
    return {"BTC", "XBT", "XXBT"} if asset == "BTC" else {asset, "Z" + asset, "X" + asset}


def _read_ids(broker: Any, method: str, ids: list[str], **params: Any) -> dict[str, Any]:
    """Respect Kraken's maximum 20 IDs per authenticated query."""
    rows: dict[str, Any] = {}
    id_parameter = "id" if method == "QueryLedgers" else "txid"
    for offset in range(0, len(ids), 20):
        batch = _private_read(broker, method, {id_parameter: ",".join(ids[offset:offset + 20]), **params})
        rows.update(batch)
    return rows


def _read_trade_ledgers(broker: Any, trade_ids: list[str], epochs: list[float]) -> dict[str, Any]:
    """Read bounded ledger history and retain only exact authenticated trade references."""
    start = math.floor(min(epochs)) - 60
    end = math.ceil(max(epochs)) + 60
    if end - start > 900:
        raise StartupEvidenceError("startup_ledger_time_range_exceeded")
    offset = 0
    expected_count: Optional[int] = None
    seen: set[str] = set()
    matched: dict[str, Any] = {}
    for _ in range(8):
        page = _private_read(broker, "Ledgers", {"type": "trade", "start": start, "end": end, "ofs": offset})
        rows = page.get("ledger")
        count = page.get("count")
        if (not isinstance(rows, Mapping) or isinstance(count, bool) or not isinstance(count, int)
                or count < 0 or count > 400 or len(rows) > 50):
            raise StartupEvidenceError("startup_ledger_page_invalid")
        if expected_count is not None and count != expected_count:
            raise StartupEvidenceError("startup_ledger_pagination_changed")
        expected_count = count
        if set(rows) & seen or (not rows and offset < count):
            raise StartupEvidenceError("startup_ledger_pagination_incomplete")
        for ledger_id, row in rows.items():
            if not isinstance(ledger_id, str) or not isinstance(row, Mapping):
                raise StartupEvidenceError("startup_ledger_row_invalid")
            seen.add(ledger_id)
            if row.get("refid") in trade_ids:
                epoch = float(row.get("time") or 0)
                if not math.isfinite(epoch) or not start < epoch <= end:
                    raise StartupEvidenceError("startup_ledger_time_invalid")
                matched[ledger_id] = dict(row)
        offset += len(rows)
        if offset == count:
            if not matched:
                raise StartupEvidenceError("startup_trade_ledger_links_missing")
            return matched
        if offset > count:
            raise StartupEvidenceError("startup_ledger_count_inconsistent")
    raise StartupEvidenceError("startup_ledger_pagination_limit_exceeded")


def read_startup_fill_evidence(broker: Any, order_id: str, symbol: str, side: str) -> StartupFillEvidence:
    """Resolve actual base quantity and fees through exact authenticated ledger links."""
    if not order_id or side not in {"buy", "sell"} or symbol.count("-") != 1:
        raise StartupEvidenceError("startup_fill_request_invalid")
    base, quote = symbol.upper().split("-")
    orders = _private_read(broker, "QueryOrders", {"txid": order_id, "trades": True})
    order = orders.get(order_id)
    if not isinstance(order, Mapping) or str(order.get("status") or "").lower() != "closed":
        raise StartupEvidenceError("startup_order_not_terminal_filled")
    description = order.get("descr")
    if not isinstance(description, Mapping) or description.get("type") != side:
        raise StartupEvidenceError("startup_order_side_unproven")
    pair = str(description.get("pair") or "").upper().replace("/", "").replace("-", "")
    if pair not in {a + b for a in _asset_variants(base) for b in _asset_variants(quote)}:
        raise StartupEvidenceError("startup_order_pair_mismatch")
    if str(description.get("leverage") or "none").lower() not in {"none", "1", "1:1"}:
        raise StartupEvidenceError("startup_fill_requires_spot")
    volume = _decimal(order.get("vol_exec"), nonnegative=True)
    trade_ids = order.get("trades")
    if (volume <= 0 or not isinstance(trade_ids, list) or not trade_ids
            or not all(isinstance(x, str) for x in trade_ids)):
        raise StartupEvidenceError("startup_order_fills_unproven")
    if len(set(trade_ids)) != len(trade_ids):
        raise StartupEvidenceError("startup_trade_ids_duplicated")
    trades = _read_ids(broker, "QueryTrades", trade_ids)
    epochs: list[float] = []
    total_volume = Decimal(0)
    latest_epoch = 0.0
    for trade_id in trade_ids:
        trade = trades.get(trade_id)
        if not isinstance(trade, Mapping) or trade.get("ordertxid") != order_id or trade.get("type") != side:
            raise StartupEvidenceError("startup_trade_order_link_missing")
        total_volume += _decimal(trade.get("vol"), nonnegative=True)
        epoch = float(trade.get("time") or 0)
        if not math.isfinite(epoch) or not 0 < epoch <= time.time() + 60:
            raise StartupEvidenceError("startup_trade_time_invalid")
        latest_epoch = max(latest_epoch, epoch)
        epochs.append(epoch)
    if total_volume != volume:
        raise StartupEvidenceError("startup_trade_volume_inconsistent")
    ledgers = _read_trade_ledgers(broker, trade_ids, epochs)
    gross_base = Decimal(0)
    base_fees = Decimal(0)
    quote_delta = Decimal(0)
    base_trade_refs: set[str] = set()
    quote_trade_refs: set[str] = set()
    for ledger_id, row in ledgers.items():
        if (not isinstance(row, Mapping) or row.get("refid") not in trade_ids
                or row.get("type") != "trade"):
            raise StartupEvidenceError("startup_exact_ledger_row_missing")
        amount = _decimal(row.get("amount"))
        fee = _decimal(row.get("fee"), nonnegative=True)
        asset = str(row.get("asset") or "").upper()
        if asset in _asset_variants(base):
            if (side == "buy" and amount <= 0) or (side == "sell" and amount >= 0):
                raise StartupEvidenceError("startup_base_ledger_direction_invalid")
            gross_base += amount
            base_fees += fee
            base_trade_refs.add(str(row["refid"]))
        elif asset in _asset_variants(quote):
            if (side == "buy" and amount >= 0) or (side == "sell" and amount <= 0):
                raise StartupEvidenceError("startup_quote_ledger_direction_invalid")
            quote_delta += amount - fee
            quote_trade_refs.add(str(row["refid"]))
        else:
            raise StartupEvidenceError("startup_unexpected_fee_or_ledger_asset")
    if (base_trade_refs != set(trade_ids) or quote_trade_refs != set(trade_ids)
            or abs(gross_base) != volume):
        raise StartupEvidenceError("startup_base_or_quote_ledger_completeness_unproven")
    net_base = gross_base - base_fees
    if (side == "buy" and net_base <= 0) or (side == "sell" and net_base >= 0):
        raise StartupEvidenceError("startup_net_base_delta_invalid")
    return StartupFillEvidence(order_id, side, volume, net_base, quote_delta, latest_epoch)


@dataclass(frozen=True)
class StartupRoundTripEvidence:
    """Broker-authenticated terminal round trip; not permission to trade."""

    entry_order_id: str
    exit_order_id: str
    account_fingerprint: str
    plan_digest: str
    net_base_delta: Decimal
    net_quote_delta: Decimal
    verified_at_epoch: float
    execution_ready: bool = False


def verify_startup_terminal_round_trip(
    broker: Any,
    plan: Any,
    *,
    entry_order_id: str,
    exit_order_id: str,
    max_age_seconds: float = 1800.0,
) -> StartupRoundTripEvidence:
    """Fail closed unless genuine Kraken trade and ledger facts close the lot.

    This read-only verifier cannot submit orders, mint a heartbeat marker, or
    authorize unattended execution. A caller must independently establish
    protective-exit coverage and reconcile all account exposure.
    """
    plan.validate()
    if (not isinstance(entry_order_id, str) or not entry_order_id.strip()
            or not isinstance(exit_order_id, str) or not exit_order_id.strip()
            or entry_order_id == exit_order_id):
        raise StartupEvidenceError("startup_roundtrip_order_ids_invalid")
    now = time.time()
    if not math.isfinite(max_age_seconds) or not 0 < max_age_seconds <= 1800:
        raise StartupEvidenceError("startup_roundtrip_freshness_bound_invalid")
    identity = read_startup_broker_identity(broker)
    if (identity.account_fingerprint != plan.account_fingerprint
            or identity.api_key_fingerprint != plan.api_key_fingerprint):
        raise StartupEvidenceError("startup_roundtrip_account_or_key_mismatch")
    entry = read_startup_fill_evidence(broker, entry_order_id, plan.symbol, "buy")
    exit_fill = read_startup_fill_evidence(broker, exit_order_id, plan.symbol, "sell")
    if (entry.gross_base_quantity != _decimal(plan.base_quantity)
            or entry.net_base_delta <= 0
            or exit_fill.net_base_delta >= 0
            or entry.net_base_delta + exit_fill.net_base_delta != 0):
        raise StartupEvidenceError("startup_roundtrip_quantity_not_reconciled")
    if (exit_fill.execution_epoch < entry.execution_epoch
            or not 0 <= now - exit_fill.execution_epoch <= max_age_seconds
            or not 0 <= now - entry.execution_epoch <= max_age_seconds):
        raise StartupEvidenceError("startup_roundtrip_fill_stale_or_reversed")
    if (-entry.quote_delta > _decimal(plan.budget_usd)
            or entry.quote_delta >= 0 or exit_fill.quote_delta <= 0):
        raise StartupEvidenceError("startup_roundtrip_cash_budget_or_direction_invalid")
    return StartupRoundTripEvidence(
        entry_order_id, exit_order_id, identity.account_fingerprint,
        plan.digest(), entry.net_base_delta + exit_fill.net_base_delta,
        entry.quote_delta + exit_fill.quote_delta, now,
    )
