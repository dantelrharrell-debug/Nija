"""Offline comparison of a proposed platform Kraken opening. Never writes a ledger."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import runpy
import sqlite3
import sys
from decimal import Decimal
from pathlib import Path
from typing import Any

# The preflight is stdlib-only. Loading its fixed path avoids bot package startup hooks.
_compare_history = runpy.run_path(str(Path(__file__).resolve().parents[1] / "bot" /
                                      "kraken_sqlite_readonly_preflight_v488.py"))["_compare_history"]

SCOPE = "platform:kraken"
ASSETS = {"ZUSD": "USD", "USD": "USD", "XXBT": "BTC", "XBT": "BTC", "BTC": "BTC", "BABY": "BABY"}
HASH = re.compile(r"[0-9a-f]{64}")
LIMIT = 8 * 1024 * 1024


def require(condition: bool, reason: str) -> None:
    """Deny the rehearsal using a non-sensitive diagnostic."""
    if not condition:
        raise ValueError(reason)


def historical_exceptions(ledger: Path, backup: Path, backup_sha256: str) -> int:
    """Compare immutable close terms on two standalone offline database copies."""
    require(not ledger.is_symlink() and ledger.is_file() and not ledger.samefile(backup), "distinct_copies_required")
    require(not any(Path(str(ledger) + s).exists() for s in ("-wal", "-journal")), "standalone_ledger_required")
    db = sqlite3.connect(ledger.resolve().as_uri() + "?mode=ro&immutable=1", uri=True)
    try:
        db.execute("PRAGMA trusted_schema=OFF")
        db.execute("PRAGMA query_only=ON")
        db.execute("BEGIN")
        require(db.execute("PRAGMA integrity_check").fetchone() == ("ok",), "ledger_integrity_failed")
        counts = _compare_history(db, backup, backup_sha256)
        require(counts == {"historical_unattributed_unchanged": 13, "current_unattributed_new_or_changed": 0,
                           "historical_unattributed_absent_or_changed": 0}, "historical_exceptions_changed")
        total = db.execute("SELECT count(*) FROM pending_kraken_closes WHERE broker=? AND account_scope=?",
                           ("kraken", SCOPE)).fetchone()[0]
        require(total == 13, "unexpected_pending_closes")
        require(db.execute("SELECT count(*) FROM open_positions WHERE user_id=? AND status=?",
                           ("platform", "open")).fetchone()[0] == 0, "local_open_positions")
        return total
    finally:
        db.close()


def amount(raw: Any) -> Decimal:
    """Parse bounded exact nonnegative decimal strings without float rounding."""
    require(isinstance(raw, str) and len(raw) <= 100 and re.fullmatch(r"[0-9]+(?:\.[0-9]+)?", raw) is not None,
            "invalid_amount")
    return Decimal(raw)


def timestamp(raw: Any) -> float:
    """Require an epoch time supplied by a recorded source."""
    require(type(raw) in (int, float) and math.isfinite(raw) and raw > 0, "invalid_observation_time")
    return raw


def observe(report: dict) -> tuple[float, float, dict]:
    """Check all three individual reads in their recorded sequence."""
    require(report["inventory_read_succeeded"] is True and report["trading_authorized"] is False
            and report["diagnostic_only"] is True and report["account_scope_asserted_by_caller"] == SCOPE,
            "inventory_scope_or_status")
    obs = report["observations"]
    previous = 0
    for name in ("BalanceEx", "OpenOrders", "OpenPositions"):
        start, end = (timestamp(obs[name][k]) for k in ("started_at", "finished_at"))
        require(previous <= start <= end, "unordered_observations")
        previous = end
    orders = obs["OpenOrders"]["result"]
    if "request_mode" in obs["OpenOrders"]:
        require(obs["OpenOrders"]["request_mode"] == "all_unfiltered_no_limit" and orders == {"open": {}},
                "open_orders_or_unverified_request_mode")
    else:
        require(orders in ({"open": {}, "cursor": {}}, {"open": {}, "cursor": {"next": None}},
                       {"open": {}, "cursor": {"next": ""}}), "open_orders_or_incomplete_cursor")
    require(obs["OpenPositions"]["result"] == {}, "open_margin_positions")
    rows = obs["BalanceEx"]["result"]
    require(isinstance(rows, dict) and len(rows) <= 4096, "invalid_balance_rows")
    balances = {}
    for asset, row in rows.items():
        require(isinstance(row, dict) and set(row) in ({"balance", "hold_trade"},
                {"balance", "hold_trade", "credit", "credit_used"}), "wallet_fields_invalid")
        require(all(amount(v) == 0 for k, v in row.items() if k != "balance"), "held_or_borrowed_balance")
        value = amount(row["balance"])
        if asset not in ASSETS:
            require(value == 0, "unsupported_asset")
            continue
        symbol = ASSETS[asset]
        require(symbol not in balances, "ambiguous_asset_alias")
        balances[symbol] = value
    return obs["BalanceEx"]["started_at"], previous, balances


def read_pinned(path: Path, digest: str) -> dict:
    """Read JSON matching an externally supplied digest, rejecting duplicate keys."""
    def unique(pairs: list) -> dict:
        obj = dict(pairs)
        require(len(obj) == len(pairs), "duplicate_json_key")
        return obj

    require(HASH.fullmatch(digest) is not None and path.is_file() and not path.is_symlink(), "source_pin_invalid")
    with path.open("rb") as stream:
        data = stream.read(LIMIT + 1)
    require(len(data) <= LIMIT and hashlib.sha256(data).hexdigest() == digest, "source_digest_mismatch")
    return json.loads(data, object_pairs_hook=unique)


def rehearse(boundary: dict, before: dict, after: dict, ledger: Path, backup: Path, backup_sha256: str) -> dict:
    """Compare supplied observations only; a matching rehearsal cannot approve a cutover."""
    exceptions = historical_exceptions(ledger, backup, backup_sha256)
    require(boundary["account_scope"] == SCOPE and boundary["wallet"] == "default", "boundary_scope_mismatch")
    require(before["request_id"] != after["request_id"] and all(
        re.fullmatch(r"[a-f0-9]{32}", r["request_id"]) for r in (before, after)), "distinct_reads_required")
    left, first_end, first = observe(before)
    second_start, right, second = observe(after)
    cutoff = timestamp(boundary["cutoff"])
    require(first_end <= cutoff <= second_start and first_end < second_start, "cutoff_not_bracketed")
    require(timestamp(boundary["coverage_start"]) <= left and timestamp(boundary["coverage_end"]) >= right,
            "movement_coverage_incomplete")
    require(boundary["history_cursor_exhausted"] is True and boundary["writer_fenced_through_interval"] is True
            and boundary["intent_inventory_complete"] is True, "boundary_evidence_incomplete")
    require(boundary["movements"] == [] and boundary["outstanding_intents"] == [], "boundary_activity")
    require(set(boundary["opening_balances"]) == {"USD", "BTC", "BABY"}, "opening_asset_set")
    expected = {asset: amount(value) for asset, value in boundary["opening_balances"].items()}
    require(first == second == expected, "opening_balances_disagree")
    opening_entries = {asset: {"quantity": str(quantity), "strategy_id": None, "cost_basis": None}
                       for asset, quantity in expected.items()}
    return {"opening_inventory": opening_entries, "comparison": "supplied_inputs_match", "historical_exceptions_preserved": exceptions,
            "strategy_pnl_attributed": False, "period_created": False, "authorizes_orders": False}


def main() -> int:
    """Run locally against private copies; print only the comparison outcome."""
    parser = argparse.ArgumentParser(description=__doc__)
    for key in ("boundary", "before", "after", "backup"):
        parser.add_argument("--" + key, required=True, type=Path)
        parser.add_argument("--" + key + "-sha256", required=True)
    parser.add_argument("--ledger", required=True, type=Path)
    args = parser.parse_args()
    try:
        inputs = [read_pinned(getattr(args, k), getattr(args, k + "_sha256")) for k in ("boundary", "before", "after")]
        require(inputs[0]["inventory_sha256"] == [args.before_sha256, args.after_sha256]
                and inputs[0]["historical_sha256"] == args.backup_sha256, "boundary_pin_mismatch")
        result = rehearse(*inputs, args.ledger, args.backup, args.backup_sha256)
    except (OSError, ValueError, KeyError, TypeError, AttributeError, OverflowError, sqlite3.Error, ArithmeticError):
        print('{"comparison":"denied","period_created":false,"authorizes_orders":false}')
        return 2
    del result["opening_inventory"]  # Exact quantities stay inside the private rehearsal.
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
