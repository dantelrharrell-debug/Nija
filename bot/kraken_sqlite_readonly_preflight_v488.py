"""Read-only preflight of the *actual* NIJA SQLite trading ledger (v488).

This is NOT an independent ledger attestation or an exchange reconciliation.
It never returns verified=True, does not install a collector, does not read
broker credentials, and does not create/repair local database records.

Run only with authorized access to the existing mounted /data disk. The
returned report contains counters and fixed refusal codes, never holdings,
secrets, user identifiers, or raw order/position IDs.
"""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from pathlib import Path
from typing import Any

ORDER_ID = re.compile(r"O[A-Z0-9]{5}-[A-Z0-9]{5}-[A-Z0-9]{6}\Z")
_TABLE_COLUMNS = {
    "trade_ledger": {"user_id", "position_id", "action", "order_id"},
    "open_positions": {"position_id", "user_id", "status", "quantity", "entry_price"},
    "completed_trades": {"position_id", "user_id"},
    "strategy_order_intents": {"broker", "account_scope", "order_id"},
    "pending_kraken_closes": {"broker", "account_scope", "state", "order_id"},
}
_MAX_ROWS = 10000


def _unattributed_closes(db: sqlite3.Connection) -> dict:
    """Identify pending closes by immutable fill terms; omit replay timestamps."""
    rows = db.execute(
        "SELECT order_id, symbol, side, fill_price, filled_usd, exit_fee, "
        "user_id, verification_level FROM pending_kraken_closes "
        "WHERE account_scope='platform:kraken' AND broker='kraken' "
        "AND state='pending' AND reason='missing_position' "
        "AND matched_position_id IS NULL LIMIT ?", (_MAX_ROWS + 1,)
    ).fetchall()
    if len(rows) > _MAX_ROWS:
        raise ValueError("historical_close_budget_exceeded")
    result = {}
    for oid, *terms in rows:
        if not isinstance(oid, str) or not ORDER_ID.fullmatch(oid) or oid in result:
            raise ValueError("ambiguous_historical_order")
        result[oid] = tuple(terms)
    return result


def _compare_history(db: sqlite3.Connection, backup: Path, expected: str) -> dict:
    """Read a closed standalone SQLite backup into memory; never restore in place."""
    if not re.fullmatch(r"[a-f0-9]{64}", expected) or backup.is_symlink():
        raise ValueError("invalid_historical_backup")
    if not backup.is_file() or any(Path(str(backup) + suffix).exists()
                                   for suffix in ("-wal", "-journal")):
        raise ValueError("standalone_backup_required")
    with backup.open("rb") as stream:
        data = stream.read(32 * 1024 * 1024 + 1)
    if len(data) > 32 * 1024 * 1024 or hashlib.sha256(data).hexdigest() != expected:
        raise ValueError("historical_backup_digest_mismatch")
    reference = sqlite3.connect(":memory:")
    try:
        reference.deserialize(data)
        reference.execute("PRAGMA trusted_schema=OFF")
        reference.execute("PRAGMA query_only=ON")
        if reference.execute("PRAGMA integrity_check").fetchone() != ("ok",):
            raise ValueError("historical_backup_integrity_failed")
        historical = _unattributed_closes(reference)
    finally:
        reference.close()
    current = _unattributed_closes(db)
    same = sum(oid in historical and historical[oid] == terms
               for oid, terms in current.items())
    return {
        "historical_unattributed_unchanged": same,
        "current_unattributed_new_or_changed": len(current) - same,
        "historical_unattributed_absent_or_changed": len(historical) - same,
    }


def inspect_kraken_ledger(
    ledger_path: Path, *, persistent_root: Path = Path("/data"),
    historical_backup: Path | None = None, historical_sha256: str | None = None,
) -> dict[str, Any]:
    """Inspect current persistent SQLite without writes or readiness assertions."""
    issues: list[str] = []
    counts: dict[str, int] = {}
    report: dict[str, Any] = {
        "account_scope": "platform:kraken",
        "source": "readonly_local_ledger_preflight",
        "read_only": True,
        "authorizes_orders": False,
        "independent_ledger_certified": False,
        "backup_restore_certified": False,
        "broker_history_reconciled": False,
        "protective_exits_broker_verified": False,
        "collector_install_allowed": False,
        "issues": issues,
        "counts": counts,
    }
    try:
        root = Path(persistent_root).resolve(strict=True)
        raw = Path(ledger_path)
        actual = raw.resolve(strict=True)
        if (not root.is_dir() or not actual.is_file() or raw.is_symlink()
                or root not in actual.parents):
            issues.append("persistent_ledger_path_unverified")
            return report
    except (OSError, RuntimeError, TypeError, ValueError):
        issues.append("persistent_ledger_path_unverified")
        return report

    # sqlite URI mode=ro and query_only prevent schema initialization or
    # accidental modification; do not instantiate TradeLedgerDB here.
    connection = None
    try:
        connection = sqlite3.connect(
            actual.as_uri() + "?mode=ro", uri=True, timeout=3
        )
        connection.execute("PRAGMA query_only=ON")
        version_before = connection.execute("PRAGMA data_version").fetchone()[0]
        connection.execute("BEGIN")
        if connection.execute("PRAGMA integrity_check").fetchone() != ("ok",):
            issues.append("sqlite_integrity_unverified")
            return report
        report["sqlite_integrity_ok"] = True
        for table, required in _TABLE_COLUMNS.items():
            cols = {str(row[1]) for row in connection.execute(
                'PRAGMA table_info("' + table + '")'
            )}
            if not required.issubset(cols):
                issues.append("required_table_or_columns_missing:" + table)
                continue
            counts[table] = int(connection.execute(
                'SELECT COUNT(*) FROM "' + table + '"'
            ).fetchone()[0])
        if any(v > _MAX_ROWS for v in counts.values()):
            issues.append("ledger_audit_row_budget_exceeded")
            return report

        if "open_positions" in counts:
            positions = connection.execute(
                "SELECT position_id,quantity,entry_price FROM open_positions "
                "WHERE user_id='platform' AND status='open'"
            ).fetchall()
            counts["platform_open_positions"] = len(positions)
            if any(not isinstance(pid, str) or not pid
                   or not isinstance(qty, (int, float)) or qty <= 0
                   or not isinstance(price, (int, float)) or price <= 0
                   for pid, qty, price in positions):
                issues.append("open_position_entry_basis_unverified")
            if "trade_ledger" in counts:
                openings = connection.execute(
                    "SELECT position_id,order_id FROM trade_ledger "
                    "WHERE user_id='platform' AND action='OPEN'"
                ).fetchall()
                by_position: dict[str, list[str]] = {}
                for pid, oid in openings:
                    by_position.setdefault(str(pid), []).append(oid)
                missing = sum(
                    len(by_position.get(pid, [])) != 1 or
                    not isinstance(by_position[pid][0], str) or
                    ORDER_ID.fullmatch(by_position[pid][0]) is None
                    for pid, _qty, _price in positions
                )
                counts["platform_positions_without_exact_opening"] = missing
                if missing:
                    issues.append("opening_ledger_order_links_unverified")
            cols = {str(row[1]) for row in connection.execute(
                'PRAGMA table_info("open_positions")'
            )}
            if not {"stop_order_id", "take_profit_order_id"}.issubset(cols):
                issues.append("exchange_protective_order_id_mapping_missing")
            else:
                linked = connection.execute(
                    "SELECT stop_order_id,take_profit_order_id FROM open_positions "
                    "WHERE user_id='platform' AND status='open'"
                ).fetchall()
                found: set[str] = set()
                invalid = 0
                for stop, profit in linked:
                    if (not isinstance(stop, str) or not isinstance(profit, str)
                            or ORDER_ID.fullmatch(stop) is None
                            or ORDER_ID.fullmatch(profit) is None
                            or stop == profit or stop in found or profit in found):
                        invalid += 1
                    else:
                        found.update((stop, profit))
                counts["platform_positions_without_unique_exchange_exits"] = invalid
                if invalid:
                    issues.append("exchange_protective_order_ids_unverified")

        if "pending_kraken_closes" in counts:
            counts["pending_kraken_closes_total"] = counts["pending_kraken_closes"]
            pending = int(connection.execute(
                "SELECT COUNT(*) FROM pending_kraken_closes "
                "WHERE broker='kraken' AND account_scope='platform:kraken' "
                "AND state='pending'"
            ).fetchone()[0])
            counts["pending_kraken_closes"] = pending
            if pending:
                issues.append("pending_kraken_closes_require_reconciliation")
                if "trade_ledger" in counts:
                    booked = connection.execute(
                        "SELECT COUNT(DISTINCT p.order_id) FROM pending_kraken_closes p "
                        "JOIN trade_ledger l ON l.order_id=p.order_id "
                        "WHERE p.broker='kraken' AND p.account_scope='platform:kraken' "
                        "AND p.state='pending' AND l.user_id='platform' AND l.action='CLOSE'"
                    ).fetchone()[0]
                    counts["pending_platform_orders_already_booked"] = booked
                    if booked:
                        issues.append("pending_kraken_close_already_in_trade_ledger")

        if historical_backup is not None or historical_sha256 is not None:
            if historical_backup is None or historical_sha256 is None:
                issues.append("distinct_pinned_historical_backup_required")
            else:
                try:
                    if historical_backup.samefile(actual):
                        issues.append("distinct_pinned_historical_backup_required")
                    else:
                        counts.update(_compare_history(connection, historical_backup, historical_sha256))
                except (sqlite3.Error, ValueError, OSError):
                    issues.append("historical_backup_comparison_unverified")

        connection.execute("COMMIT")
        if connection.execute("PRAGMA data_version").fetchone()[0] != version_before:
            issues.append("ledger_changed_during_readonly_audit")
    except (sqlite3.Error, OSError, ValueError, TypeError):
        issues.append("readonly_ledger_query_failed")
    finally:
        if connection is not None:
            connection.close()
    # Even zero local issues are not a broker history, backup, exit or
    # account/key/IIBAN proof. Keep collector installation disallowed.
    report["requires"] = [
        "authenticated_full_kraken_order_and_fill_reconciliation",
        "independent_account_key_iiban_binding",
        "authenticated_protective_exit_order_readback",
        "offhost_backup_custody_and_isolated_restore_receipt",
        "independent_writer_operator_risk_authority",
    ]
    return report


def main() -> int:
    """CLI emits only redacted counters and fixed blockers; never succeeds as certification."""
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ledger", required=True, type=Path)
    parser.add_argument("--persistent-root", type=Path, default=Path("/data"))
    parser.add_argument("--historical-backup", type=Path)
    parser.add_argument("--historical-sha256")
    args = parser.parse_args()
    print(json.dumps(inspect_kraken_ledger(
        args.ledger, persistent_root=args.persistent_root,
        historical_backup=args.historical_backup, historical_sha256=args.historical_sha256,
    ), sort_keys=True))
    return 2  # Forbid treating a local audit as a production certificate.


if __name__ == "__main__":
    raise SystemExit(main())
