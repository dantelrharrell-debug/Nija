#!/usr/bin/env python3
"""Read-only, fail-closed preflight for the existing isolated TIQ72 Render DB.

Run only from a process in the confirmed Render workspace/region.
Never prints credentials, connection strings, row contents, or PII.
"""
import json
import os
import sys
from urllib.parse import unquote, urlsplit

EXPECTED_DB = "nija_tiq72_upgrade6_isolated_test"
EXPECTED_USER = "nija_tiq72_upgrade6_isolated_test_user"
EXPECTED_HOST = "dpg-dbqeq90ae00c7386p970-a"
TABLES = (
    "tiq72_v515_runs",
    "tiq72_v515_reservations",
    "tiq72_v515_reports",
    "tiq72_v515_verified_events",
)

def main():
    url = os.getenv("TIQ72_TEST_DATABASE_URL", "")
    try:
        parsed = urlsplit(url)
        if (
            parsed.scheme not in ("postgres", "postgresql")
            or parsed.hostname != EXPECTED_HOST
            or unquote(parsed.username or "") != EXPECTED_USER
            or unquote(parsed.path.lstrip("/")) != EXPECTED_DB
            or not parsed.password
            or (parsed.port or 5432) != 5432
            or parsed.query not in ("", "sslmode=require")
            or parsed.fragment
        ):
            raise ValueError("identity")
    except (ValueError, TypeError):
        print(json.dumps({"status": "blocked", "reason": "private_database_identity_mismatch"}))
        return 2

    try:
        import psycopg2
        with psycopg2.connect(url, connect_timeout=8, sslmode="require") as db:
            db.set_session(readonly=True, autocommit=False)
            with db.cursor() as cur:
                cur.execute("SELECT current_database(), current_user")
                if cur.fetchone() != (EXPECTED_DB, EXPECTED_USER):
                    raise ValueError("connected_identity")
                cur.execute(
                    "SELECT table_name FROM information_schema.tables "
                    "WHERE table_schema='public' AND table_name = ANY(%s)",
                    (list(TABLES),),
                )
                found = {row[0] for row in cur.fetchall()}
            db.rollback()
        print(json.dumps({
            "status": "identity_verified_read_only",
            "expected_tables_present": sorted(found),
            "expected_tables_missing": sorted(set(TABLES) - found),
            "migration_applied": len(found) == len(TABLES),
        }, sort_keys=True))
        return 0
    except Exception:
        print(json.dumps({"status": "blocked", "reason": "private_read_only_preflight_failed"}))
        return 3

if __name__ == "__main__":
    sys.exit(main())
