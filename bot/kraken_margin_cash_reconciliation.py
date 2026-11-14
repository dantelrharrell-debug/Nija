"""Offline comparison of margin cash records, never collector certification.

Kraken margin P&L and opening/trading fees belong to `margin` ledger rows;
financing fees belong to `rollover` rows. They must not be reconstructed as
spot base/quote transfers or inferred from TradesHistory's fee field.

Inputs must already be collected and independently persisted. This pure helper
does not establish their identity, pagination, freshness, provenance, position
allocation or protective coverage. Matching two copies of the same archive
does not establish independent reconciliation. No database/network/startup I/O.
"""
from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal, localcontext
import re
from typing import Any

MAX_ROWS = 10000
_CASH_TYPES = frozenset({"margin", "rollover"})
_OTHER_TYPES = frozenset({
    "trade", "deposit", "withdrawal", "transfer", "settled", "staking",
    "spend", "receive", "sale", "credit", "adjustment", "dividend", "nft_trade",
    "nft_creator_fee", "custodytransfer", "invite_bonus", "reward", "conversion",
})
_PIN = re.compile(r"[0-9a-f]{64}\Z")
_DECIMAL = re.compile(r"-?[0-9]{1,32}(?:\.[0-9]{1,32})?\Z")


class MarginCashReconciliationDenied(ValueError):
    """Fixed error code, without financial records or identifiers."""


def _require(condition: bool, code: str) -> None:
    if not condition:
        raise MarginCashReconciliationDenied(code)


def _identifier(value: Any) -> bool:
    return (type(value) is str and 0 < len(value) <= 128
            and value.isascii() and all(c.isalnum() or c in "_:-." for c in value))


def _amount(value: Any, *, signed: bool = False) -> Decimal:
    # Financial values remain decimal strings. Reject floats and exponent
    # notation rather than accidentally rounding or allocating huge integers.
    _require(type(value) is str and _DECIMAL.fullmatch(value) is not None,
             "invalid_cash_decimal")
    number = Decimal(value)
    _require(signed or number >= 0, "negative_cash_fee")
    return number


def _normalize(row: Mapping[str, Any]) -> tuple:
    _require(all(_identifier(row.get(k)) for k in ("refid", "asset", "aclass")),
             "cash_identity_missing")
    _require(row["aclass"] == "currency", "cash_asset_class_unsupported")
    subtype = row.get("subtype", "")
    _require(subtype == "" or _identifier(subtype), "cash_subtype_invalid")
    stamp = row.get("time")
    _require(type(stamp) in (str, int, float), "cash_timestamp_invalid")
    timestamp = _amount(str(stamp))
    _require(timestamp > 0, "cash_timestamp_invalid")
    amount, fee, balance = (_amount(row.get("amount"), signed=True),
                            _amount(row.get("fee")), _amount(row.get("balance"), signed=True))
    _require(row["type"] != "rollover" or amount == 0, "rollover_amount_nonzero")
    return (row["refid"], row["type"], subtype, row["asset"], row["aclass"],
            timestamp, amount, fee, balance)


def compare_margin_cash_records(
    exchange_ledger: Mapping[str, Mapping[str, Any]],
    persisted_rows: list[Mapping[str, Any]], *, account_scope: str,
    account_sha256: str, api_key_sha256: str,
) -> dict[str, Any]:
    """Require exact margin/rollover row sets and terms within supplied inputs.

    Local rows retain Kraken fields and add exchange_ledger_id, broker,
    account_scope, account_sha256 and api_key_sha256. They must come from the
    persistence owner, not be populated by this comparison. Asset codes and
    references are compared exactly, without guessing aliases or trade links.
    Other known entry types are excluded from this *margin-only* comparison;
    settlements and spot balances need their own reconciliation. Unknown types
    deny to avoid silently dropping new financing events.
    """
    _require(type(account_scope) is str and (
        account_scope == "platform:kraken" or (
            account_scope.startswith("user:") and account_scope.endswith(":kraken")
            and len(account_scope.split(":")) == 3 and _identifier(account_scope.split(":")[1]))),
        "cash_scope_invalid")
    _require(all(type(p) is str and _PIN.fullmatch(p) for p in (account_sha256, api_key_sha256)),
             "cash_scope_pins_invalid")
    _require(isinstance(exchange_ledger, Mapping) and type(persisted_rows) is list,
             "cash_records_invalid")
    _require(len(exchange_ledger) <= MAX_ROWS and len(persisted_rows) <= MAX_ROWS,
             "cash_record_budget_exceeded")
    observed, local = {}, {}
    excluded = 0
    for identity, row in exchange_ledger.items():
        _require(_identifier(identity) and isinstance(row, Mapping), "cash_row_invalid")
        kind = row.get("type")
        _require(type(kind) is str and kind in _CASH_TYPES | _OTHER_TYPES, "cash_type_unsupported")
        if kind not in _CASH_TYPES:
            excluded += 1
            continue
        observed[identity] = _normalize(row)
    for row in persisted_rows:
        _require(isinstance(row, Mapping), "cash_row_invalid")
        _require((row.get("broker"), row.get("account_scope"), row.get("account_sha256"),
                  row.get("api_key_sha256")) == ("kraken", account_scope, account_sha256, api_key_sha256),
                 "cash_provenance_mismatch")
        identity = row.get("exchange_ledger_id")
        _require(_identifier(identity) and identity not in local, "cash_id_missing_or_duplicate")
        _require(type(row.get("type")) is str and row["type"] in _CASH_TYPES, "local_cash_type_invalid")
        local[identity] = _normalize(row)
    _require(observed.keys() == local.keys(), "cash_entry_set_mismatch")
    _require(observed == local, "cash_entry_terms_mismatch")
    totals: dict[str, dict[str, Decimal]] = {}
    with localcontext() as context:
        # 64 decimal digits per input plus at most 4 digits of accumulation.
        context.prec = 160
        for row in observed.values():
            _, kind, _, asset, _, _, amount, fee, _ = row
            total = totals.setdefault(asset, {k: Decimal(0) for k in (
                "realized_pnl", "opening_and_trading_fees", "rollover_fees", "net_cash_change")})
            if kind == "margin":
                total["realized_pnl"] += amount
                total["opening_and_trading_fees"] += fee
            else:
                total["rollover_fees"] += fee
            total["net_cash_change"] += amount - fee
    return {
        "input_rows_match": True, "matched_entry_count": len(observed),
        "excluded_non_margin_entry_count": excluded,
        "totals_by_asset": {a: {k: format(v, "f") for k, v in t.items()} for a, t in sorted(totals.items())},
        "complete_history_verified": False, "account_identity_verified": False,
        "positions_reconciled": False, "protective_exits_verified": False,
        "collector_certified": False, "authorizes_orders": False,
    }
