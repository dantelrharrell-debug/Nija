#!/usr/bin/env python3
"""Value-free read-only PostgreSQL identity, connectivity and table preflight.

This is exclusively for the isolated Nija TIQ72 sandbox Render workspace.
Never prints raw exceptions, credentials, URLs, query results or customer data.
Never executes DDL/DML and never certifies payment or database backup safety.
"""
import json
import os
import socket
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


def blocked(reason, exit_code=3):
    print(json.dumps({"status": "blocked", "reason": reason}, sort_keys=True))
    return exit_code


def classify_connect_failure(error, resolve=None, dial=None):
    """Return *only* known-safe codes. Do not emit raw driver exceptions."""
    state = getattr(error, "pgcode", None)
    if state in ("28P01", "28000"):
        return "private_db_credentials_rejected"
    if state == "3D000":
        return "private_db_database_unavailable"
    if state in ("53300", "57P03"):
        return "private_db_server_unavailable"
    resolve = resolve or socket.getaddrinfo
    dial = dial or socket.create_connection
    try:
        resolve(EXPECTED_HOST, 5432)
    except OSError:
        return "private_db_dns_unavailable"
    try:
        connection = dial((EXPECTED_HOST, 5432), timeout=3)
        connection.close()
    except OSError:
        return "private_db_tcp_unavailable"
    return "private_db_tls_or_auth_rejected"


def verified_private_url(url):
    try:
        u = urlsplit(url)
        return (
            u.scheme in ("postgres", "postgresql")
            and u.hostname == EXPECTED_HOST
            and unquote(u.username or "") == EXPECTED_USER
            and unquote(u.path.lstrip("/")) == EXPECTED_DB
            and bool(u.password)
            and (u.port or 5432) == 5432
            and u.query in ("", "sslmode=require")
            and not u.fragment
        )
    except (ValueError, TypeError):
        return False


def main():
    url = os.getenv("TIQ72_TEST_DATABASE_URL", "")
    if not verified_private_url(url):
        return blocked("private_database_identity_mismatch", 2)

    try:
        import psycopg2
    except (ImportError, OSError):
        return blocked("private_db_driver_unavailable")

    try:
        db = psycopg2.connect(url, connect_timeout=8, sslmode="require")
    except psycopg2.OperationalError as exc:
        return blocked(classify_connect_failure(exc))
    except Exception:
        return blocked("private_db_connection_failed")

    try:
        db.set_session(readonly=True, autocommit=False)
        with db.cursor() as cur:
            cur.execute("SELECT current_database(), current_user")
            if cur.fetchone() != (EXPECTED_DB, EXPECTED_USER):
                return blocked("connected_database_identity_mismatch", 2)
            cur.execute(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema='public' AND table_name = ANY(%s)",
                (list(TABLES),),
            )
            found = {row[0] for row in cur.fetchall()}
        missing = sorted(set(TABLES) - found)
        print(json.dumps({
            "status": "identity_verified_read_only",
            "expected_tables_present": sorted(found),
            "expected_tables_missing": missing,
            "migration_applied": not missing,
        }, sort_keys=True))
        return 0
    except Exception:
        return blocked("private_db_readonly_catalog_query_failed")
    finally:
        try:
            db.rollback()
        except Exception:
            pass
        db.close()


if __name__ == "__main__":
    sys.exit(main())
