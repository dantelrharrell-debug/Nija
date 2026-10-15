#!/usr/bin/env python3
"""Offline ledger recovery evidence report. Never changes production readiness.

Run ONLY against a previously transferred off-host archive. The v436 archive
verification pins source bytes, checks the supplied source checksum and exercises
an isolated restore. This tool does not attest the location or custody of the
archive and never authorizes trading.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

try:
    from scripts.nija_trade_ledger_snapshot_v436 import verify_snapshot
except ModuleNotFoundError:
    # Direct invocation from the scripts/ directory also remains supported.
    from nija_trade_ledger_snapshot_v436 import verify_snapshot


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--expected-sha256", required=True)
    args = parser.parse_args(argv)
    try:
        result = verify_snapshot(
            args.archive,
            expected_sha256=args.expected_sha256,
            exercise_restore=True,
        )
    except Exception as exc:
        print(json.dumps({
            "verification": "failed",
            "error_type": type(exc).__name__,
            "backup_restore_verified": False,
            "production_readiness_changed": False,
        }, sort_keys=True))
        return 1
    print(json.dumps({
        "verification": "archive_integrity_and_isolated_restore_passed",
        "off_host_custody_independently_established": False,
        "historical_reconciliation_verified": False,
        "backup_restore_verified": False,
        "production_readiness_changed": False,
        "archive_details": result,
    }, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
