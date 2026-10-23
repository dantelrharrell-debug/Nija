#!/usr/bin/env python3
"""Offline, non-authorizing v441 Kraken receipt versus pending-close intake.

Operates on an explicitly supplied private v441 receipt and an existing SQLite
ledger in mode=ro. Does not connect to brokers, change ledger rows, certify
execution, install an attestor, or set any trading readiness flags.
"""
from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import math
import os
from pathlib import Path
import sqlite3
import stat
from typing import Any, Mapping

MAX_RECEIPT_BYTES = 64 * 1024 * 1024
REQUIRED_LEDGER_TABLES = (
    "trade_ledger", "open_positions", "completed_trades", "pending_kraken_closes",
)
HISTORY_FIELDS = ("trades", "closed", "ledger")


class IntakeFailure(ValueError):
    """A fixed non-sensitive failure label, never a brokerage response."""


def _scope_valid(scope: Any) -> bool:
    if not isinstance(scope, str) or not scope or any(c.isspace() for c in scope):
        return False
    if scope == "platform:kraken":
        return True
    parts = scope.split(":")
    return len(parts) == 3 and parts[0] == "user" and bool(parts[1]) and parts[2] == "kraken"


def _unique_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    output: dict[str, Any] = {}
    for key, value in pairs:
        if key in output:
            raise IntakeFailure("receipt_duplicate_key")
        output[key] = value
    return output


def _private_receipt(path: Path) -> dict[str, Any]:
    if not path.is_absolute() or path.is_symlink():
        raise IntakeFailure("receipt_location_invalid")
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except OSError:
        raise IntakeFailure("receipt_unavailable") from None
    try:
        before = os.fstat(fd)
        if (not stat.S_ISREG(before.st_mode) or before.st_uid != os.geteuid()
                or stat.S_IMODE(before.st_mode) & 0o077 or before.st_nlink != 1
                or before.st_size <= 0 or before.st_size > MAX_RECEIPT_BYTES):
            raise IntakeFailure("receipt_not_private_regular")
        raw = os.read(fd, MAX_RECEIPT_BYTES + 1)
        after = os.fstat(fd)
        if (len(raw) != before.st_size or before.st_size != after.st_size
                or before.st_mtime_ns != after.st_mtime_ns
                or before.st_ctime_ns != after.st_ctime_ns):
            raise IntakeFailure("receipt_changed_while_reading")
    finally:
        os.close(fd)
    try:
        document = json.loads(raw, object_pairs_hook=_unique_keys)
    except IntakeFailure:
        raise
    except (UnicodeDecodeError, ValueError, TypeError):
        raise IntakeFailure("receipt_json_invalid") from None
    if not isinstance(document, dict):
        raise IntakeFailure("receipt_schema_invalid")
    return document


def _clock(value: Any) -> float:
    if type(value) not in (float, int) or not math.isfinite(value) or value <= 0:
        raise IntakeFailure("receipt_observation_clock_invalid")
    return float(value)


def _validated_evidence(receipt: Mapping[str, Any], account_scope: str) -> dict[str, Any]:
    identity = receipt.get("request_id")
    if (not isinstance(identity, str) or len(identity) != 32
            or any(c not in "0123456789abcdef" for c in identity)
            or receipt.get("collection_succeeded") is not True
            or receipt.get("trading_authorized") is not False):
        raise IntakeFailure("receipt_claim_invalid")
    evidence = receipt.get("evidence")
    if not isinstance(evidence, Mapping):
        raise IntakeFailure("receipt_evidence_missing")
    if evidence.get("account_scope_asserted_by_caller") != account_scope:
        raise IntakeFailure("receipt_scope_mismatch")
    expected_flags = {
        "repeat_read_consistent": True,
        "atomic_broker_snapshot_verified": False,
        "authenticated_identity_independently_verified": False,
        "ledger_links_verified": False,
        "protective_exit_coverage_verified": False,
        "entry_exit_reconciliation_verified": False,
        "trading_authorized": False,
        "side_effects": "read_only_api_calls",
    }
    if any(evidence.get(key) is not expected if isinstance(expected, bool)
           else evidence.get(key) != expected
           for key, expected in expected_flags.items()):
        raise IntakeFailure("receipt_provenance_invalid")

    history, balance, open_orders = (
        evidence.get("history"), evidence.get("balance"), evidence.get("open_orders")
    )
    if (not isinstance(history, Mapping) or not isinstance(balance, Mapping)
            or not isinstance(open_orders, Mapping)
            or any(not isinstance(history.get(key), Mapping) for key in HISTORY_FIELDS)):
        raise IntakeFailure("receipt_history_invalid")
    for collection in (history["trades"], history["closed"], history["ledger"], open_orders):
        if any(not isinstance(key, str) or not key or not isinstance(row, Mapping)
               for key, row in collection.items()):
            raise IntakeFailure("receipt_history_row_invalid")
    observations = evidence.get("open_orders_observations")
    if not isinstance(observations, list) or len(observations) != 2:
        raise IntakeFailure("receipt_observation_missing")
    intervals = []
    for row in observations:
        if not isinstance(row, Mapping):
            raise IntakeFailure("receipt_observation_invalid")
        start = _clock(row.get("request_started_at"))
        end = _clock(row.get("response_finished_at"))
        if end < start:
            raise IntakeFailure("receipt_observation_clock_invalid")
        intervals.append((start, end))
    started = _clock(receipt.get("collection_started_at"))
    finished = _clock(receipt.get("collection_finished_at"))
    if not (started <= intervals[0][0] <= intervals[0][1]
            <= intervals[1][0] <= intervals[1][1] <= finished):
        raise IntakeFailure("receipt_observation_clock_invalid")

    envelope = {
        "account_scope_asserted_by_caller": account_scope,
        "history": history,
        "balance": balance,
        "open_orders": open_orders,
        "open_orders_observations": observations,
    }
    digest = evidence.get("evidence_sha256")
    if (not isinstance(digest, str) or len(digest) != 64
            or any(c not in "0123456789abcdef" for c in digest)):
        raise IntakeFailure("receipt_digest_invalid")
    try:
        calculated = hashlib.sha256(
            json.dumps(envelope, sort_keys=True, separators=(",", ":"), allow_nan=False)
            .encode("utf-8")
        ).hexdigest()
    except (TypeError, ValueError):
        raise IntakeFailure("receipt_history_invalid") from None
    if not hmac.compare_digest(digest, calculated):
        raise IntakeFailure("receipt_digest_mismatch")
    # This unsigned checksum is an integrity check, NOT authenticated ownership.
    return dict(evidence)


def _pending_order_ids(database: Path, account_scope: str) -> set[str]:
    if not database.is_absolute() or database.is_symlink() or not database.is_file():
        raise IntakeFailure("ledger_location_invalid")
    try:
        conn = sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True, timeout=15)
    except sqlite3.Error:
        raise IntakeFailure("ledger_open_failed") from None
    try:
        conn.execute("PRAGMA query_only=ON")
        if conn.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
            raise IntakeFailure("ledger_integrity_unverified")
        tables = {row[0] for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )}
        if not set(REQUIRED_LEDGER_TABLES).issubset(tables):
            raise IntakeFailure("ledger_schema_missing")
        columns = {row[1] for row in conn.execute('PRAGMA table_info("pending_kraken_closes")')}
        if not {"broker", "account_scope", "order_id", "state"}.issubset(columns):
            raise IntakeFailure("ledger_schema_missing")
        records = conn.execute(
            "SELECT order_id FROM pending_kraken_closes "
            "WHERE broker=? AND account_scope=? AND state='pending'",
            ("kraken", account_scope),
        ).fetchall()
        ids: set[str] = set()
        for (order_id,) in records:
            if (not isinstance(order_id, str) or not order_id
                    or order_id != order_id.strip() or any(c.isspace() for c in order_id)
                    or order_id in ids):
                raise IntakeFailure("ledger_order_identity_invalid")
            ids.add(order_id)
        return ids
    except sqlite3.Error:
        raise IntakeFailure("ledger_read_failed") from None
    finally:
        conn.close()


def inspect_intake(receipt_path: Path, ledger_path: Path, account_scope: str) -> dict[str, Any]:
    """Inventory exact pending close IDs; never assert reconciliation or readiness."""
    report: dict[str, Any] = {
        "status": "FAILED_CLOSED",
        "failure_code": "unverified",
        "account_scope_checked": False,
        "receipt_integrity_consistent": False,
        "pending_confirmed_closes": None,
        "closed_order_ids_present": None,
        "trade_order_ids_present": None,
        "both_order_and_trade_ids_present": None,
        "pending_closes_still_unresolved": None,
        "authenticated_account_owner_certified": False,
        "fills_and_fees_reconciled": False,
        "protective_exits_broker_verified": False,
        "offhost_backup_restore_certified": False,
        "execution_ready": False,
        "execution_authority": False,
        "authorizes_orders": False,
        "writes_performed": False,
    }
    try:
        if not _scope_valid(account_scope):
            raise IntakeFailure("account_scope_invalid")
        receipt = _private_receipt(Path(receipt_path))
        evidence = _validated_evidence(receipt, account_scope)
        ids = _pending_order_ids(Path(ledger_path), account_scope)
        closed = evidence["history"]["closed"]
        trades = evidence["history"]["trades"]
        trade_order_ids: set[str] = set()
        for row in trades.values():
            order_id = row.get("ordertxid")
            if not isinstance(order_id, str) or not order_id:
                raise IntakeFailure("trade_order_identity_invalid")
            trade_order_ids.add(order_id)
        present_closed = ids & set(closed)
        present_trades = ids & trade_order_ids
        report.update({
            "status": "READ_ONLY_INTAKE_COMPLETE",
            "failure_code": None,
            "account_scope_checked": True,
            "receipt_integrity_consistent": True,
            "pending_confirmed_closes": len(ids),
            "closed_order_ids_present": len(present_closed),
            "trade_order_ids_present": len(present_trades),
            "both_order_and_trade_ids_present": len(present_closed & present_trades),
            "pending_closes_still_unresolved": len(ids),
        })
    except IntakeFailure as exc:
        report["failure_code"] = str(exc)
    except Exception:
        # Never output broker rows, SQL values, credentials or exception text.
        report["failure_code"] = "unexpected_read_failure"
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--ledger", type=Path, required=True)
    parser.add_argument("--account-scope", required=True)
    options = parser.parse_args()
    report = inspect_intake(options.receipt, options.ledger, options.account_scope)
    print(json.dumps(report, sort_keys=True, separators=(",", ":")))
    return 0 if report["status"] == "READ_ONLY_INTAKE_COMPLETE" else 1


if __name__ == "__main__":
    raise SystemExit(main())
