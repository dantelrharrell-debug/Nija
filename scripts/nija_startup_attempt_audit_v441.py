#!/usr/bin/env python3
"""Read-only inspection of durable startup attempts; never changes trading state."""
import argparse
import json
import os
from pathlib import Path
import sqlite3


def inspect(path: Path) -> dict:
    result = {"database_present": path.is_file(), "readable": False,
              "proof_admissible_by_attempt_state": False,
              "state_counts": {}, "unresolved_count": None, "error": None}
    if not path.is_file():
        # Absence permits the startup-attempt check but is not execution proof.
        result["proof_admissible_by_attempt_state"] = True
        result["unresolved_count"] = 0
        return result
    try:
        uri = path.resolve().as_uri() + "?mode=ro"
        with sqlite3.connect(uri, uri=True, timeout=2.0) as connection:
            connection.execute("PRAGMA query_only=ON")
            rows = connection.execute(
                "SELECT state, COUNT(*) FROM startup_attempts GROUP BY state"
            ).fetchall()
        counts = {str(state): int(count) for state, count in rows}
        unresolved = sum(count for state, count in counts.items() if state != "completed")
        result.update(readable=True, state_counts=counts, unresolved_count=unresolved,
                      proof_admissible_by_attempt_state=(unresolved == 0))
    except (sqlite3.Error, OSError, ValueError) as exc:
        result["error"] = type(exc).__name__
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=Path(
        os.environ.get("NIJA_STARTUP_ATTEMPT_DB", "/data/startup_verification_attempts.db")))
    args = parser.parse_args()
    if not args.db.is_absolute():
        parser.error("--db must be an absolute path")
    result = inspect(args.db)
    print(json.dumps(result, sort_keys=True))
    return 0 if result["error"] is None else 2


if __name__ == "__main__":
    raise SystemExit(main())
