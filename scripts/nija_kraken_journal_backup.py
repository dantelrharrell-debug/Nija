"""Require the durable submission journal in Kraken commissioning backups."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sqlite3
import sys

from scripts import nija_trade_ledger_snapshot_v436 as snapshot


def _require_verified_journal(manifest: dict) -> None:
    if "submission_journal_sqlite_tables" not in manifest:
        raise ValueError("required submission journal is missing from archive")


def capture(source: Path, output_dir: Path) -> dict:
    if not os.getenv("NIJA_KRAKEN_SUBMISSION_JOURNAL_PATH", "").strip():
        raise ValueError("required submission journal is not configured")
    report = snapshot.create_snapshot(source, output_dir)
    manifest = snapshot.verify_snapshot(Path(report["archive"]), expected_sha256=report["sha256"])
    _require_verified_journal(manifest)
    return {**report, "submission_journal_verified": True, "live_trading_eligible": False}


def restore(archive: Path, *, expected_sha256: str) -> dict:
    manifest = snapshot.verify_snapshot(archive, expected_sha256=expected_sha256, exercise_restore=True)
    _require_verified_journal(manifest)
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
    except (OSError, ValueError, sqlite3.Error) as exc:
        print(json.dumps({"status": "FAILED_CLOSED", "error_type": type(exc).__name__}), file=sys.stderr)
        return 1
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
