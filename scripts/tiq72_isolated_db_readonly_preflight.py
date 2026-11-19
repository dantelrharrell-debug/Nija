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


# Only catalog metadata is read: no run, payment, owner, or report rows.
# Names/types mirror the reviewed v515 ledger SQL, including test-only checks.
COLUMNS = {
    "tiq72_v515_runs": {
        "run_id": ("text", "NO"), "owner_id": ("text", "NO"),
        "canonical_run": ("jsonb", "NO"),
        "canonical_digest": ("text", "NO"),
        "attempt_key": ("text", "NO"), "version": ("text", "NO"),
    },
    "tiq72_v515_reservations": {
        "reservation_id": ("text", "NO"), "run_id": ("text", "NO"),
        "owner_id": ("text", "NO"), "stripe_session": ("text", "YES"),
        "state": ("text", "NO"),
    },
    "tiq72_v515_reports": {
        "run_id": ("text", "NO"), "reservation_id": ("text", "NO"),
        "owner_id": ("text", "NO"), "stripe_session": ("text", "NO"),
        "report": ("jsonb", "NO"),
    },
    "tiq72_v515_verified_events": {
        "event_id": ("text", "NO"), "event_type": ("text", "NO"),
        "reservation_id": ("text", "NO"),
        "stripe_session": ("text", "NO"),
    },
}
# Each entry is (table, constraint_name, PostgreSQL constraint type,
# referenced table for a foreign key or None).
CONSTRAINTS = (
    ("tiq72_v515_runs", "tiq72_v515_runs_pkey", "p", None),
    ("tiq72_v515_runs", "tiq72_v515_unique_attempt", "u", None),
    ("tiq72_v515_runs", "tiq72_v515_run_version", "c", None),
    ("tiq72_v515_runs", "tiq72_v515_owner_nonempty", "c", None),
    ("tiq72_v515_reservations", "tiq72_v515_reservations_pkey", "p", None),
    ("tiq72_v515_reservations", "tiq72_v515_reservations_run_id_key", "u", None),
    ("tiq72_v515_reservations", "tiq72_v515_reservations_stripe_session_key", "u", None),
    ("tiq72_v515_reservations", "tiq72_v515_reservations_run_id_fkey", "f", "tiq72_v515_runs"),
    ("tiq72_v515_reservations", "tiq72_v515_state", "c", None),
    ("tiq72_v515_reservations", "tiq72_v515_owner_nonempty", "c", None),
    ("tiq72_v515_reservations", "tiq72_v515_session_test_only", "c", None),
    ("tiq72_v515_reports", "tiq72_v515_reports_pkey", "p", None),
    ("tiq72_v515_reports", "tiq72_v515_reports_reservation_id_key", "u", None),
    ("tiq72_v515_reports", "tiq72_v515_reports_stripe_session_key", "u", None),
    ("tiq72_v515_reports", "tiq72_v515_reports_run_id_fkey", "f", "tiq72_v515_runs"),
    ("tiq72_v515_reports", "tiq72_v515_reports_reservation_id_fkey", "f", "tiq72_v515_reservations"),
    ("tiq72_v515_verified_events", "tiq72_v515_verified_events_pkey", "p", None),
    ("tiq72_v515_verified_events", "tiq72_v515_verified_events_reservation_id_fkey", "f", "tiq72_v515_reservations"),
    ("tiq72_v515_verified_events", "tiq72_v515_event_type", "c", None),
    ("tiq72_v515_verified_events", "tiq72_v515_event_test_session", "c", None),
)
INDEXES = (
    ("tiq72_v515_reservations", "tiq72_v515_res_owner_run"),
    ("tiq72_v515_verified_events", "tiq72_v515_events_reservation"),
)


def schema_contract_verified(cursor):
    """Check checked-in ledger structure using read-only system catalogs.

    A set of matching table names alone is not migration proof. This function
    returns a single boolean and never returns customer data or raw SQL.
    """
    cursor.execute(
        "SELECT table_name, column_name, data_type, is_nullable "
        "FROM information_schema.columns "
        "WHERE table_schema='public' AND table_name = ANY(%s)",
        (list(TABLES),),
    )
    columns = {
        (table, column): (data_type, nullable)
        for table, column, data_type, nullable in cursor.fetchall()
    }
    if any(
        columns.get((table, column)) != spec
        for table, specs in COLUMNS.items()
        for column, spec in specs.items()
    ):
        return False

    cursor.execute(
        "SELECT t.relname, con.conname, con.contype, ref.relname "
        "FROM pg_catalog.pg_constraint con "
        "JOIN pg_catalog.pg_class t ON t.oid=con.conrelid "
        "JOIN pg_catalog.pg_namespace ns ON ns.oid=t.relnamespace "
        "LEFT JOIN pg_catalog.pg_class ref ON ref.oid=con.confrelid "
        "WHERE ns.nspname='public' AND t.relname = ANY(%s)",
        (list(TABLES),),
    )
    constraints = {
        (table, name): (kind, foreign)
        for table, name, kind, foreign in cursor.fetchall()
    }
    if any(
        constraints.get((table, name)) != (kind, reference)
        for table, name, kind, reference in CONSTRAINTS
    ):
        return False

    cursor.execute(
        "SELECT t.relname, i.relname, ix.indisvalid, ix.indisready "
        "FROM pg_catalog.pg_index ix "
        "JOIN pg_catalog.pg_class t ON t.oid=ix.indrelid "
        "JOIN pg_catalog.pg_class i ON i.oid=ix.indexrelid "
        "JOIN pg_catalog.pg_namespace ns ON ns.oid=t.relnamespace "
        "WHERE ns.nspname='public' AND t.relname = ANY(%s)",
        (list(TABLES),),
    )
    indexes = {
        (table, index): (valid, ready)
        for table, index, valid, ready in cursor.fetchall()
    }
    return all(indexes.get(pair) == (True, True) for pair in INDEXES)




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
            contract = not missing and schema_contract_verified(cur)
        print(json.dumps({
            "status": "identity_verified_read_only",
            "expected_tables_present": sorted(found),
            "expected_tables_missing": missing,
            "schema_contract_verified": bool(contract),
            "migration_applied": bool(contract),
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
