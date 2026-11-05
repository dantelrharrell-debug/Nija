"""Prepare a separate SQLite schema candidate from a closed private backup.

Never opens the source writable, overwrites an existing destination, fills in
exchange IDs, resolves pending closes, or authorizes production migration.
This is a schema rehearsal, not broker reconciliation or backup certification.
"""
from __future__ import annotations

import argparse
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import stat
import tempfile
import time

MAX_BYTES = 128 * 1024 * 1024
MAX_ROWS = 100000
MAPPING_COLUMNS = ("stop_order_id", "take_profit_order_id")
REQUIRED_TABLES = {"open_positions", "trade_ledger", "completed_trades", "pending_kraken_closes"}


class RehearsalDenied(ValueError):
    """A fixed, non-sensitive refusal code."""


def _private_parent(path: Path) -> None:
    if not path.is_absolute() or any(part == ".." for part in path.parts):
        raise RehearsalDenied("absolute_private_path_required")
    if any(item.is_symlink() for item in (path, *path.parents)):
        raise RehearsalDenied("symlink_refused")
    parent = path.parent.stat()
    if (not stat.S_ISDIR(parent.st_mode) or parent.st_uid != os.geteuid()
            or stat.S_IMODE(parent.st_mode) & 0o077):
        raise RehearsalDenied("private_owned_parent_required")


def _identity(info: os.stat_result) -> tuple:
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def _file_digest(path: Path) -> str:
    result = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(chunk)
    return result.hexdigest()


def _quoted(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def _snapshot(db: sqlite3.Connection, columns: dict | None = None) -> dict:
    """Fingerprint every original table/cell; serialize no financial rows."""
    definitions = db.execute("SELECT name,sql FROM sqlite_master WHERE type='table'").fetchall()
    if not REQUIRED_TABLES <= {row[0] for row in definitions}:
        raise RehearsalDenied("canonical_tables_missing")
    result = {}
    budget = MAX_ROWS
    for name, sql in definitions:
        if "VIRTUAL TABLE" in (sql or "").upper():
            raise RehearsalDenied("virtual_table_refused")
        fields = db.execute("PRAGMA table_xinfo(" + _quoted(name) + ")").fetchall()
        if any(row[6] for row in fields):
            raise RehearsalDenied("generated_or_hidden_column_refused")
        selected = columns[name]["columns"] if columns is not None else tuple(row[1] for row in fields)
        cursor = db.execute("SELECT " + ",".join(map(_quoted, selected)) + " FROM " + _quoted(name))
        digests = []
        for row in cursor:
            budget -= 1
            if budget < 0:
                raise RehearsalDenied("rehearsal_row_budget_exceeded")
            digests.append(hashlib.sha256(repr(tuple(row)).encode("utf-8")).digest())
        result[name] = {"columns": selected, "rows_sha256": hashlib.sha256(b"".join(sorted(digests))).hexdigest()}
    return result


def _add_columns(db: sqlite3.Connection, missing: list[str]) -> None:
    for name in missing:
        if name not in MAPPING_COLUMNS:
            raise RehearsalDenied("unapproved_schema_change")
        db.execute("ALTER TABLE open_positions ADD COLUMN " + _quoted(name) + " TEXT")


def _schema_except_positions(db: sqlite3.Connection) -> list:
    return db.execute(
        "SELECT type,name,tbl_name,sql FROM sqlite_master "
        "WHERE name != 'open_positions' ORDER BY type,name"
    ).fetchall()


def prepare_candidate(backup: Path, candidate: Path, expected_backup_sha256: str) -> dict:
    """Rehearse transactional schema additions in a new, private candidate file.

    The caller must provide a verified closed backup; a matching checksum alone
    does not establish its provenance or off-host recoverability. There is no
    in-place/apply mode and no startup hook.
    """
    if (os.environ.get("RENDER_SERVICE_ID") or os.environ.get("RAILWAY_DEPLOYMENT_ID")
            or any(root == path or root in path.parents
                   for path in (backup, candidate) for root in (Path("/app"), Path("/data")))):
        raise RehearsalDenied("isolated_review_environment_required")
    if not re.fullmatch(r"[0-9a-f]{64}", expected_backup_sha256):
        raise RehearsalDenied("exact_backup_digest_required")
    _private_parent(backup)
    _private_parent(candidate)
    if candidate.exists() or candidate == backup:
        raise RehearsalDenied("new_candidate_required")
    if any(Path(str(backup) + suffix).exists() for suffix in ("-wal", "-shm", "-journal")):
        raise RehearsalDenied("closed_backup_without_sidecars_required")
    before = backup.stat()
    if (not stat.S_ISREG(before.st_mode) or before.st_uid != os.geteuid()
            or before.st_nlink != 1 or stat.S_IMODE(before.st_mode) & 0o077
            or not 0 < before.st_size <= MAX_BYTES):
        raise RehearsalDenied("private_bounded_backup_required")
    if _file_digest(backup) != expected_backup_sha256:
        raise RehearsalDenied("backup_digest_mismatch")
    started = time.monotonic()
    def progress(status: int, remaining: int, total: int) -> None:
        if time.monotonic() - started > 15:
            raise RehearsalDenied("rehearsal_deadline_exceeded")
    handle, temporary_name = tempfile.mkstemp(prefix=".ledger-candidate-", dir=candidate.parent)
    os.close(handle)
    temporary = Path(temporary_name)
    try:
        with closing(sqlite3.connect(backup.as_uri() + "?mode=ro&immutable=1", uri=True)) as source:
            source.execute("PRAGMA query_only=ON")
            source.execute("PRAGMA trusted_schema=OFF")
            if source.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
                raise RehearsalDenied("backup_integrity_unverified")
            original = _snapshot(source)
            schema = _schema_except_positions(source)
            with closing(sqlite3.connect(temporary, isolation_level=None)) as target:
                source.backup(target, pages=1024, progress=progress)
                target.execute("PRAGMA trusted_schema=OFF")
                fields = target.execute("PRAGMA table_info(open_positions)").fetchall()
                if not {"position_id", "user_id", "quantity", "entry_price", "status"} <= {r[1] for r in fields}:
                    raise RehearsalDenied("canonical_position_columns_missing")
                if any(r[1] in MAPPING_COLUMNS and r[2].upper() != "TEXT" for r in fields):
                    raise RehearsalDenied("mapping_column_type_conflict")
                missing = [name for name in MAPPING_COLUMNS if name not in {r[1] for r in fields}]
                target.execute("BEGIN IMMEDIATE")
                try:
                    _add_columns(target, missing)
                    if _snapshot(target, original) != original:
                        raise RehearsalDenied("original_records_changed")
                    if _schema_except_positions(target) != schema:
                        raise RehearsalDenied("unapproved_schema_change")
                    if target.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
                        raise RehearsalDenied("candidate_integrity_unverified")
                    if target.execute("PRAGMA foreign_key_check").fetchall():
                        raise RehearsalDenied("foreign_keys_unverified")
                    for name in missing:
                        if target.execute("SELECT COUNT(*) FROM open_positions WHERE " + _quoted(name)
                                          + " IS NOT NULL").fetchone()[0]:
                            raise RehearsalDenied("fabricated_mapping_refused")
                    target.execute("COMMIT")
                except Exception:
                    target.execute("ROLLBACK")
                    raise
        if (_identity(backup.stat()) != _identity(before)
                or _file_digest(backup) != expected_backup_sha256):
            raise RehearsalDenied("backup_changed_during_rehearsal")
        with temporary.open("rb") as stream:
            os.fsync(stream.fileno())
        digest = _file_digest(temporary)
        # Hard-link publication fails if any existing file occupies candidate.
        if any(os.path.lexists(str(candidate) + suffix)
               for suffix in ("-wal", "-shm", "-journal")):
            raise RehearsalDenied("new_candidate_without_sidecars_required")
        os.link(temporary, candidate, follow_symlinks=False)
        directory = os.open(candidate.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
        return {
            "format": "nija-protective-mapping-schema-rehearsal-v1",
            "backup_sha256": expected_backup_sha256, "candidate_sha256": digest,
            "columns_added": missing, "original_records_preserved": True,
            "pending_closes_preserved": True, "candidate_integrity_ok": True,
            "backup_origin_verified": False, "offhost_restore_certified": False,
            "broker_reconciled": False, "protective_coverage_verified": False,
            "production_apply_authorized": False, "allow_new_orders": False,
        }
    finally:
        temporary.unlink(missing_ok=True)


def main() -> int:
    """Print only fixed failure codes and a non-authorizing digest report."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backup", required=True, type=Path)
    parser.add_argument("--candidate", required=True, type=Path)
    parser.add_argument("--expected-backup-sha256", required=True)
    args = parser.parse_args()
    try:
        result = prepare_candidate(args.backup, args.candidate, args.expected_backup_sha256)
    except RehearsalDenied as exc:
        print(json.dumps({"status": "BLOCKED", "reason": str(exc), "allow_new_orders": False}))
        return 2
    except (OSError, sqlite3.Error, ValueError, KeyError):
        print(json.dumps({"status": "BLOCKED", "reason": "rehearsal_io_or_schema_invalid", "allow_new_orders": False}))
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
