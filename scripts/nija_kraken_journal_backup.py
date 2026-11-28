"""Require the durable submission journal in Kraken commissioning backups."""
from __future__ import annotations

import argparse
from contextlib import closing
import json
import os
from pathlib import Path
import sqlite3
import stat
import sys
from tempfile import TemporaryDirectory

from scripts import nija_trade_ledger_snapshot_v436 as snapshot
from scripts.nija_kraken_submission_validation import has_invalid_terminal_metadata


def _verify_account_journal(archive: Path, *, expected_sha256: str, exercise_restore: bool) -> None:
    max_archive = (
        snapshot.MAX_SQLITE_BYTES + snapshot.MAX_MANIFEST_BYTES
        + (len(snapshot.OPTIONAL_FILES) + 1) * snapshot.MAX_COMPANION_BYTES + 2 * 1024 * 1024
    )
    with TemporaryDirectory(prefix="nija-journal-verify-") as temporary:
        stage = Path(temporary)
        pinned = stage / "input.tar.gz"
        fd = os.open(archive, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(fd, "rb") as source, pinned.open("xb") as target:
            info = os.fstat(source.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_size > max_archive:
                raise ValueError("unsafe or oversized source archive")
            remaining = info.st_size
            while remaining:
                chunk = source.read(min(remaining, snapshot.CHUNK_SIZE))
                if not chunk:
                    raise ValueError("source archive changed during snapshot")
                target.write(chunk)
                remaining -= len(chunk)
            if source.read(1):
                raise ValueError("source archive changed during snapshot")

        manifest = snapshot.verify_snapshot(
            pinned, expected_sha256=expected_sha256, exercise_restore=exercise_restore,
        )
        if "submission_journal_sqlite_tables" not in manifest:
            raise ValueError("required submission journal is missing from archive")
        snapshot._unpack_bounded_archive(pinned, stage)
        journal = stage / snapshot.SUBMISSION_JOURNAL
        with closing(sqlite3.connect(journal.as_uri() + "?mode=ro&immutable=1", uri=True)) as db:
            if db.execute("SELECT scope FROM account LIMIT 2").fetchall() != [("platform:kraken",)]:
                raise ValueError("submission journal account scope mismatch")
            if db.execute("PRAGMA foreign_key_check").fetchone() is not None:
                raise ValueError("submission journal contains invalid references")
            # A structurally valid backup must also satisfy the runtime journal's
            # requirement that terminal evidence names the reserved broker order.
            if db.execute(
                """SELECT 1 FROM submission_resolution AS r
                   JOIN submission AS s ON s.intent_id=r.intent_id
                   WHERE typeof(s.broker_order_id) != 'text'
                      OR trim(s.broker_order_id, char(9,10,11,12,13,32)) = ''
                   LIMIT 1"""
            ).fetchone() is not None:
                raise ValueError("submission journal contains terminal evidence without a broker order reference")
            if has_invalid_terminal_metadata(db):
                raise ValueError("submission journal contains invalid terminal evidence metadata")


def capture(source: Path, output_dir: Path) -> dict:
    if not os.getenv("NIJA_KRAKEN_SUBMISSION_JOURNAL_PATH", "").strip():
        raise ValueError("required submission journal is not configured")
    output_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    if output_dir.is_symlink() or not output_dir.is_dir():
        raise ValueError("unsafe output directory")
    with TemporaryDirectory(prefix=".nija-capture-", dir=output_dir) as temporary:
        report = snapshot.create_snapshot(source, Path(temporary))
        staged = Path(report["archive"])
        _verify_account_journal(staged, expected_sha256=report["sha256"], exercise_restore=False)
        archive = output_dir / staged.name
        # Publish only verified bytes. An existing backup with this name wins.
        os.link(staged, archive)
    return {**report, "archive": str(archive), "submission_journal_verified": True, "live_trading_eligible": False}


def restore(archive: Path, *, expected_sha256: str) -> dict:
    if not isinstance(expected_sha256, str) or not expected_sha256.strip():
        raise ValueError("independently recorded archive SHA-256 is required")
    expected = expected_sha256.strip().lower()
    if len(expected) != 64 or any(ch not in "0123456789abcdef" for ch in expected):
        raise ValueError("expected archive SHA-256 must be 64 hex characters")
    _verify_account_journal(archive, expected_sha256=expected, exercise_restore=True)
    return {
        "expected_archive_sha256_matched": True,
        "isolated_restore_test_verified": True,
        "submission_journal_verified": True,
        "off_host_backup_verified": False,
        "live_trading_eligible": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    backup = commands.add_parser("backup")
    backup.add_argument("--source", type=Path, required=True)
    backup.add_argument("--output-dir", type=Path, required=True)
    recovery = commands.add_parser("restore-test")
    recovery.add_argument("--archive", type=Path, required=True)
    recovery.add_argument("--expected-sha256", required=True)
    args = parser.parse_args()
    try:
        if args.command == "backup":
            report = capture(args.source, args.output_dir)
        else:
            report = restore(args.archive, expected_sha256=args.expected_sha256)
    except (OSError, ValueError, RuntimeError, sqlite3.Error) as exc:
        print(json.dumps({"status": "FAILED_CLOSED", "error_type": type(exc).__name__}), file=sys.stderr)
        return 1
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
