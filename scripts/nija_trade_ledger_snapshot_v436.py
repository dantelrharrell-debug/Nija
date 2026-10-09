#!/usr/bin/env python3
"""Create and verify a read-only SQLite ledger snapshot before Render migration.

This script does not submit trades, contact brokers, alter the source ledger,
change runtime flags, or declare that a local backup survived a redeploy.

Run it INSIDE THE CURRENT LIVE CONTAINER, before attaching a Render disk.
Copy the resulting encrypted-transport archive off the host with SCP/SFTP,
then use the verify subcommand against the independently saved copy.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import io
import json
import os
import shutil
import sqlite3
import sys
import tarfile
import tempfile
from pathlib import Path
from typing import Any


CHUNK_SIZE = 1024 * 1024
MAX_COMPANION_BYTES = 128 * 1024 * 1024
MANDATORY_TABLES = ("trade_ledger", "open_positions", "completed_trades")
OPTIONAL_FILES = (
    ("pending_kraken_fills.json", "NIJA_KRAKEN_PENDING_FILL_PROOF_PATH",
     "./data/kraken_pending_fill_proof.json"),
    ("execution_journal.jsonl", "NIJA_EXECUTION_JOURNAL_PATH",
     "./data/execution_journal.jsonl"),
    ("open_positions.json", "NIJA_POSITIONS_FILE",
     "./data/open_positions.json"),
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while True:
            chunk = source.read(CHUNK_SIZE)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _counts(connection: sqlite3.Connection) -> dict[str, int]:
    tables = [
        row[0] for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        )
    ]
    output: dict[str, int] = {}
    for table in sorted(tables):
        # Identifiers originate in sqlite_master, not user input. Quote safely.
        safe_name = '"' + table.replace('"', '""') + '"'
        output[table] = int(
            connection.execute("SELECT COUNT(*) FROM " + safe_name).fetchone()[0]
        )
    return output


def _validate_database(path: Path) -> dict[str, int]:
    if not path.is_file() or path.is_symlink():
        raise ValueError("snapshot SQLite file missing or is a symlink")
    connection = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=15)
    try:
        check = connection.execute("PRAGMA integrity_check").fetchall()
        if check != [("ok",)]:
            raise RuntimeError("SQLite integrity_check did not return ok")
        tables = _counts(connection)
        missing = set(MANDATORY_TABLES) - set(tables)
        if missing:
            raise RuntimeError("trading-ledger tables missing: " + ",".join(sorted(missing)))
        return tables
    finally:
        connection.close()


def _snapshot_sqlite(source: Path, destination: Path) -> dict[str, int]:
    if not source.is_file() or source.is_symlink():
        raise FileNotFoundError("source SQLite ledger is missing or is a symlink")
    if source.resolve() == destination.resolve():
        raise ValueError("source and destination cannot be the same file")
    # Online SQLite backup API captures one transactional snapshot, including
    # records residing in a WAL, without modifying the source connection.
    reader = sqlite3.connect(source.resolve().as_uri() + "?mode=ro", uri=True, timeout=15)
    writer = sqlite3.connect(str(destination), timeout=15)
    try:
        reader.backup(writer, pages=256, sleep=0.1)
        writer.commit()
    finally:
        writer.close()
        reader.close()
    return _validate_database(destination)


def _copy_companion(source: Path, destination: Path) -> bool:
    if not source.is_file() or source.is_symlink():
        return False
    before = source.stat()
    if before.st_size > MAX_COMPANION_BYTES:
        raise ValueError("companion file exceeds maximum safe snapshot size")
    with source.open("rb") as incoming, destination.open("xb") as outgoing:
        shutil.copyfileobj(incoming, outgoing, length=CHUNK_SIZE)
        outgoing.flush()
        os.fsync(outgoing.fileno())
    after = source.stat()
    # A changing JSONL/journal requires a further quiescent backup. We still
    # preserve the copied evidence but must NOT mark the set fully consistent.
    return (
        before.st_size == after.st_size
        and before.st_mtime_ns == after.st_mtime_ns
        and destination.stat().st_size == before.st_size
    )


def create_snapshot(source: Path, output_dir: Path) -> dict[str, Any]:
    """Create an integrity-checked local archive; require an off-host copy."""
    os.umask(0o077)
    output_dir.mkdir(parents=True, exist_ok=True)
    if output_dir.is_symlink() or not output_dir.is_dir():
        raise ValueError("unsafe output directory")
    with tempfile.TemporaryDirectory(prefix="nija-ledger-stage-", dir=output_dir) as stage:
        stage_dir = Path(stage)
        ledger_copy = stage_dir / "trade_ledger.db"
        counts = _snapshot_sqlite(source, ledger_copy)
        members: dict[str, dict[str, Any]] = {}
        sources = [("trade_ledger.db", ledger_copy, True)]
        companions_stable = True
        missing_companions: list[str] = []
        for name, variable, fallback in OPTIONAL_FILES:
            candidate = Path(os.getenv(variable) or fallback)
            destination = stage_dir / name
            if not candidate.is_file() or candidate.is_symlink():
                missing_companions.append(name)
                continue
            stable = _copy_companion(candidate, destination)
            companions_stable = companions_stable and stable
            sources.append((name, destination, stable))
        for name, file, stable in sources:
            members[name] = {
                "bytes": file.stat().st_size,
                "sha256": _sha256(file),
                "read_stable": stable,
            }
        manifest = {
            "format_version": 1,
            "created_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
            "source_is_not_mutated": True,
            "snapshot_sqlite_integrity_ok": True,
            "sqlite_tables": counts,
            "members": members,
            "missing_companions": missing_companions,
            "companions_stable": companions_stable,
            "off_host_backup_verified": False,
            "restore_test_verified": False,
            "historical_fill_completeness_verified": False,
            "restart_persistence_verified": False,
        }
        manifest_file = stage_dir / "manifest.json"
        manifest_file.write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        identity = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        suffix = os.urandom(5).hex()
        final_name = "nija-trading-ledger-" + identity + "-" + suffix + ".tar.gz"
        temp_path = output_dir / (final_name + ".part")
        archive_path = output_dir / final_name
        try:
            with tarfile.open(temp_path, mode="w:gz") as archive:
                for name in sorted(members):
                    archive.add(stage_dir / name, arcname=name, recursive=False)
                archive.add(manifest_file, arcname="manifest.json", recursive=False)
            with temp_path.open("rb") as stream:
                os.fsync(stream.fileno())
            temp_path.replace(archive_path)
        finally:
            if temp_path.exists():
                temp_path.unlink()
    verified = verify_snapshot(archive_path)
    result = {
        "archive": str(archive_path),
        "sha256": _sha256(archive_path),
        "archive_bytes": archive_path.stat().st_size,
        "verified_sqlite_tables": verified["sqlite_tables"],
        "companions_stable": verified["companions_stable"],
        "off_host_backup_verified": False,
        "restore_test_verified": False,
        "ACTION_REQUIRED": "Copy archive off this Render instance using SCP/SFTP before redeploy.",
    }
    return result


def verify_snapshot(archive_path: Path) -> dict[str, Any]:
    """Check member hashes and SQLite structure without extracting unsafe paths."""
    if not archive_path.is_file() or archive_path.is_symlink():
        raise ValueError("archive missing or is a symlink")
    with tempfile.TemporaryDirectory(prefix="nija-ledger-verify-") as stage:
        stage_dir = Path(stage)
        with tarfile.open(archive_path, mode="r:gz") as archive:
            names = [entry.name for entry in archive.getmembers()]
            if len(names) != len(set(names)):
                raise ValueError("archive contains duplicate paths")
            if "manifest.json" not in names or "trade_ledger.db" not in names:
                raise ValueError("manifest or trading ledger missing")
            if any("/" in n or "\\" in n or n.startswith(".") for n in names):
                raise ValueError("archive contains an unsafe path")
            if any(not obj.isfile() for obj in archive.getmembers()):
                raise ValueError("archive contains a nonfile entry")
            manifest_data = archive.extractfile("manifest.json")
            if manifest_data is None:
                raise ValueError("manifest cannot be read")
            manifest = json.load(io.TextIOWrapper(manifest_data, encoding="utf-8"))
            if manifest.get("format_version") != 1:
                raise ValueError("unsupported snapshot version")
            tracked = manifest.get("members")
            if not isinstance(tracked, dict) or set(names) != (set(tracked) | {"manifest.json"}):
                raise ValueError("archive inventory does not match manifest")
            for name, record in tracked.items():
                if name not in ("trade_ledger.db",) + tuple(item[0] for item in OPTIONAL_FILES):
                    raise ValueError("unapproved snapshot member")
                target = stage_dir / name
                file_reader = archive.extractfile(name)
                if file_reader is None:
                    raise ValueError("snapshot member cannot be read")
                with target.open("xb") as output:
                    shutil.copyfileobj(file_reader, output, length=CHUNK_SIZE)
                if target.stat().st_size != int(record["bytes"]):
                    raise ValueError("snapshot member size mismatch: " + name)
                if _sha256(target) != record["sha256"]:
                    raise ValueError("snapshot member digest mismatch: " + name)
        counts = _validate_database(stage_dir / "trade_ledger.db")
        if counts != manifest.get("sqlite_tables"):
            raise ValueError("SQLite counts do not match manifest")
    return manifest


def main() -> int:
    """Parse CLI arguments; only create read-only snapshots or verify copies."""
    parser = argparse.ArgumentParser(description=__doc__)
    actions = parser.add_subparsers(dest="action", required=True)
    backup = actions.add_parser("backup", help="Create verified local snapshot")
    backup.add_argument(
        "--source",
        default=os.getenv("NIJA_TRADE_LEDGER_DB_PATH", "./data/trade_ledger.db"),
    )
    backup.add_argument("--output-dir", required=True)
    check = actions.add_parser("verify", help="Verify archive copied off host")
    check.add_argument("--archive", required=True)
    args = parser.parse_args()
    try:
        if args.action == "backup":
            result = create_snapshot(Path(args.source), Path(args.output_dir))
        else:
            manifest = verify_snapshot(Path(args.archive))
            result = {
                "integrity": "verified",
                "sqlite_tables": manifest["sqlite_tables"],
                "off_host_backup_verified": False,
                "restore_test_verified": False,
                "NOTE": "Verify an independent off-host copy, not the live container copy.",
            }
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    except Exception as exc:
        # Never include database contents or environment secret values in logs.
        print(
            json.dumps({"status": "FAILED_CLOSED", "error_type": type(exc).__name__,
                        "detail": str(exc)[:160]}),
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
