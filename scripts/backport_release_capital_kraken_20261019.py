#!/usr/bin/env python3
"""Fail-closed, operator-invoked backport for NIJA's pinned release branch.

By default this script only checks the source tree. --apply makes *source*
changes to two specific files in the checked-out working tree; it never calls
brokers, modifies ledgers, deploys services, or grants trading authority.

Use on a clean checkout of release/justcall-handoff-only-20261017 after review.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import sys


MANAGER = Path("bot/multi_account_broker_manager.py")
KRAKEN = Path("bot/runtime_kraken_cost_basis_history_pagination_v304_patch.py")
ANCHOR = "            # ── Derive return dict from snapshot or fall back to legacy read ──\n"
OLD_FALLBACK = "                # Coordinator not available or rejected snapshot — read CA directly."
NEW_FALLBACK = "                # No canonical coordinator configured: use legacy read path."
OLD_PAIR = "if pair not in pair_set and currency not in pair:"
NEW_PAIR = "if pair not in pair_set:"
GUARD = '''            # Canonical coordinator owns capital publication. A None snapshot
            # may indicate in-flight, rejected, or failed refresh. Never run
            # the legacy writer when the canonical coordinator is configured.
            if _CAPITAL_FSM_AVAILABLE and self._capital_coordinator is not None and snapshot is None:
                logger.warning(
                    "[CapitalAuthorityRefresh] trigger=%s coordinator_snapshot_missing "
                    "legacy_fallback_skipped=true ready=false capital_publication_unchanged=true",
                    trigger,
                )
                with self._capital_state_lock:
                    self._capital_ready = False
                return {
                    "ready": 0.0,
                    "total_capital": 0.0,
                    "valid_brokers": 0.0,
                    "pending": 1.0,
                    "coordinator_snapshot_missing": 1.0,
                }

            # Legacy authority refresh is available only when no canonical
            # coordinator is configured. No second capital writer.
'''


def _exactly_one(text: str, needle: str, path: Path) -> None:
    count = text.count(needle)
    if count != 1:
        raise ValueError(f"{path}: expected exactly one anchor, got {count}: {needle[:80]}")


def plan(root: Path) -> tuple[dict[Path, str], list[str]]:
    manager = root / MANAGER
    kraken = root / KRAKEN
    a = manager.read_text(encoding="utf-8")
    b = kraken.read_text(encoding="utf-8")
    changed: dict[Path, str] = {}
    statuses: list[str] = []

    if "coordinator_snapshot_missing" in a:
        if GUARD.strip() not in a and "legacy_fallback_skipped=true" not in a:
            raise ValueError("capital guard looks unfamiliar; manual review required")
        statuses.append("capital: guard already present")
    else:
        _exactly_one(a, ANCHOR, MANAGER)
        _exactly_one(a, OLD_FALLBACK, MANAGER)
        a = a.replace(ANCHOR, GUARD, 1).replace(OLD_FALLBACK, NEW_FALLBACK, 1)
        changed[manager] = a
        statuses.append("capital: single-writer fail-closed guard required")

    if NEW_PAIR in b and OLD_PAIR not in b:
        statuses.append("kraken: exact pair matching already present")
    else:
        _exactly_one(b, OLD_PAIR, KRAKEN)
        b = b.replace(OLD_PAIR, NEW_PAIR, 1)
        changed[kraken] = b
        statuses.append("kraken: reject substring-matched foreign pairs")
    return changed, statuses


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--apply", action="store_true", help="write source changes after review")
    args = parser.parse_args()
    try:
        changes, statuses = plan(args.root)
        for status in statuses:
            print(status)
        if not args.apply:
            print(f"CHECK_ONLY: {len(changes)} files need a reviewed backport")
            return 0
        for path, content in changes.items():
            path.write_text(content, encoding="utf-8")
            print(f"UPDATED: {path.relative_to(args.root)}")
        print("SOURCE_BACKPORT_ONLY: run tests, code review, and controlled release procedure")
        return 0
    except (OSError, ValueError) as exc:
        print(f"BACKPORT_ABORTED: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
