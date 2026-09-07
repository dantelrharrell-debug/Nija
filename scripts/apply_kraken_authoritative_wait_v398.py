#!/usr/bin/env python3
"""Extend only the Kraken authoritative-position join window.

The v286 worker performs a genuine authenticated Balance read. Production logs
show read-only Kraken prewaits of roughly 9-10 seconds, so a worker queued behind
other legitimate monitoring reads can exceed v286's historical 15-second caller
join budget even though the authenticated read is still progressing normally.

v398 changes only that join budget: callers wait 30-45 seconds for the existing
single flight. It does not create another private read, reuse stale snapshots,
extend snapshot TTL, change Kraken rate limits or transport timeouts, or grant
position/capital/execution readiness. If the genuine worker still does not
finish, the existing timeout/fail-closed path remains authoritative.
"""
from __future__ import annotations

import py_compile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "bot" / "runtime_kraken_position_refresh_liveness_v286_patch.py"
MARKER = "20260907-kraken-authoritative-wait-v398"

OLD = '''def _auth_wait_s() -> float:\n    try:\n        value = float(os.environ.get("NIJA_KRAKEN_AUTHORITATIVE_POSITION_WAIT_S", "5") or 5.0)\n    except (TypeError, ValueError):\n        value = 5.0\n    return max(1.0, min(15.0, value))\n'''

NEW = '''def _auth_wait_s() -> float:\n    # v398: this is a caller join budget for the already-running authenticated\n    # Balance single-flight, not a freshness TTL or Kraken transport timeout.\n    # Production read prewaits can legitimately consume ~9-10s each; waiting\n    # at least 30s prevents false readiness revocation while preserving the\n    # original fail-closed timeout if the genuine worker does not complete.\n    try:\n        value = float(os.environ.get("NIJA_KRAKEN_AUTHORITATIVE_POSITION_WAIT_S", "35") or 35.0)\n    except (TypeError, ValueError):\n        value = 35.0\n    return max(30.0, min(45.0, value))\n'''


def main() -> int:
    text = TARGET.read_text(encoding="utf-8")
    if NEW in text:
        print(
            f"KRAKEN_AUTHORITATIVE_WAIT_V398_READY marker={MARKER} "
            "join_min_s=30 join_max_s=45 duplicate_private_call=false "
            "snapshot_ttl_unchanged=true transport_timeout_unchanged=true "
            "rate_interval_unchanged=true readiness_fabricated=false "
            "safety_gates_bypassed=false"
        )
        return 0
    if text.count(OLD) != 1:
        raise SystemExit("v398 expected exactly one v286 _auth_wait_s block")
    TARGET.write_text(text.replace(OLD, NEW, 1), encoding="utf-8")
    py_compile.compile(str(TARGET), doraise=True)
    print(
        f"KRAKEN_AUTHORITATIVE_WAIT_V398_READY marker={MARKER} "
        "join_min_s=30 join_max_s=45 duplicate_private_call=false "
        "snapshot_ttl_unchanged=true transport_timeout_unchanged=true "
        "rate_interval_unchanged=true readiness_fabricated=false "
        "safety_gates_bypassed=false"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
