"""Read-only counts of canonical NIJA lead-intake records.

This audit exposes only aggregate counts; it does not export contact details,
mark events as conversions, or claim a complete source inventory.
"""
import argparse
import json
import re
import sqlite3
from pathlib import Path


def count_saved_submissions(database, period):
    if not isinstance(period, str) or not re.fullmatch(r"[0-9]{4}-(?:0[1-9]|1[0-2])", period):
        raise ValueError("reporting period must be YYYY-MM")
    source = Path(database).expanduser().resolve(strict=True)
    if not source.is_file():
        raise ValueError("missing private database")
    conn = sqlite3.connect(source.as_uri() + "?mode=ro", uri=True, timeout=5)
    try:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(website_leads)")}
        if not {"event_key", "form_name", "received_at"}.issubset(columns):
            raise RuntimeError("canonical lead table unavailable")
        totals = conn.execute(
            "SELECT COUNT(*), COUNT(DISTINCT event_key) FROM website_leads "
            "WHERE substr(received_at,1,7)=?", (period,)
        ).fetchone()
        groups = conn.execute(
            "SELECT form_name, COUNT(*) FROM website_leads "
            "WHERE substr(received_at,1,7)=? GROUP BY form_name "
            "ORDER BY COUNT(*) DESC, form_name", (period,)
        ).fetchall()
    finally:
        conn.close()
    return {
        "reporting_period": period,
        "source": "server_receipt_timestamp_utc",
        "persisted_submissions": totals[0],
        "distinct_submission_ids": totals[1],
        "forms": [{"form": name, "submissions": count} for name, count in groups],
        "qualified_leads_verified": False,
        "complete_source_inventory": False,
        "status": "observed_not_certified",
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", required=True)
    parser.add_argument("--period", required=True)
    args = parser.parse_args()
    print(json.dumps(count_saved_submissions(args.database, args.period), sort_keys=True))
