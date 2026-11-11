"""Validate pinned GuardDog verify output without publishing package payloads."""
from __future__ import annotations

import json
from pathlib import Path
import sys


def check_report(path: Path, scanner_status: int) -> int:
    """Deny findings, partial scans, malformed reports and scanner failures."""
    try:
        if type(scanner_status) is not int or not 0 <= scanner_status <= 255:
            raise ValueError("invalid_status")
        rows = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(rows, list) or not rows:
            raise ValueError("missing_package_results")
        issues = errors = 0
        for row in rows:
            result = row.get("result") if isinstance(row, dict) else None
            if not isinstance(result, dict):
                raise ValueError("invalid_package_result")
            count, failures = result.get("issues"), result.get("errors")
            if type(count) is not int or count < 0 or not isinstance(failures, dict):
                raise ValueError("invalid_package_summary")
            issues += count
            errors += len(failures)
    except (OSError, ValueError, TypeError):
        print("GuardDog: missing or invalid report; scan denied.")
        return scanner_status if type(scanner_status) is int and 0 < scanner_status <= 255 else 2
    print(f"GuardDog: packages={len(rows)} findings={issues} "
          f"error_entries={errors} scanner_exit={scanner_status}")
    if scanner_status:
        return scanner_status
    return 1 if issues else 2 if errors else 0


if __name__ == "__main__":
    if len(sys.argv) != 3 or not sys.argv[2].isdigit():
        print("GuardDog: report path and scanner status required; scan denied.")
        raise SystemExit(2)
    raise SystemExit(check_report(Path(sys.argv[1]), int(sys.argv[2])))
