#!/usr/bin/env python3
"""Print a read-only, evidence-limited review of a paper account JSON file."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from scripts.paper_trade_review import review_paper_account


def main() -> int:
    """Read a paper account and print its review without changing state."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True, help="PaperTradingAccount JSON state")
    parser.add_argument("--recent", type=int, default=20, help="Maximum recent closed fills to include")
    args = parser.parse_args()
    try:
        with args.input.open(encoding="utf-8") as handle:
            state = json.load(handle)
        report = review_paper_account(state, recent_limit=args.recent)
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        parser.error(f"Cannot review paper account: {exc}")
    print(json.dumps(report, indent=2, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
