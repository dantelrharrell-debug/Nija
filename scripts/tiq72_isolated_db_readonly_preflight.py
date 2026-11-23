#!/usr/bin/env python3
"""Value-free read-only PostgreSQL identity, connectivity and table preflight.

This is exclusively for the isolated Nija TIQ72 sandbox Render workspace.
Never prints raw exceptions, credentials, URLs, query results or customer data.
Never executes DDL/DML and never certifies payment or database backup safety.
"""
import json
import os
import re
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
        "created_at": ("timestamp with time zone", "NO"),
    },
    "tiq72_v515_reservations": {
        "reservation_id": ("text", "NO"), "run_id": ("text", "NO"),
        "owner_id": ("text", "NO"), "stripe_session": ("text", "YES"),
        "state": ("text", "NO"),
        "created_at": ("timestamp with time zone", "NO"),
        "updated_at": ("timestamp with time zone", "NO"),
    },
    "tiq72_v515_reports": {
        "run_id": ("text", "NO"), "reservation_id": ("text", "NO"),
        "owner_id": ("text", "NO"), "stripe_session": ("text", "NO"),
        "report": ("jsonb", "NO"),
        "created_at": ("timestamp with time zone", "NO"),
    },
    "tiq72_v515_verified_events": {
        "event_id": ("text", "NO"), "event_type": ("text", "NO"),
        "reservation_id": ("text", "NO"),
        "stripe_session": ("text", "NO"),
        "received_at": ("timestamp with time zone", "NO"),
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

# Constraint existence alone is insufficient: a same-named CHECK (true)
# does not enforce the intended test-only ledger restrictions. These are
# canonical PostgreSQL 18 forms of security-critical public schema checks.
REQUIRED_CHECK_DEFINITIONS = {
    ("tiq72_v515_runs", "tiq72_v515_run_version"):
        "checkversion='v515-72-decisions'",
    ("tiq72_v515_reservations", "tiq72_v515_session_test_only"):
        "checkstripe_sessionisnullorstripe_sessionlike'cs_test_%'",
    ("tiq72_v515_verified_events", "tiq72_v515_event_test_session"):
        "checkstripe_sessionlike'cs_test_%'",
}
# Require exact column order and referenced keys, not just trusted names/types.
# These strings are normalized PostgreSQL pg_get_constraintdef forms.
REQUIRED_KEY_DEFINITIONS = {
    ("tiq72_v515_runs", "tiq72_v515_runs_pkey"): "primarykeyrun_id",
    ("tiq72_v515_runs", "tiq72_v515_unique_attempt"):
        "uniqueowner_id,attempt_key",
    ("tiq72_v515_reservations", "tiq72_v515_reservations_pkey"):
        "primarykeyreservation_id",
    ("tiq72_v515_reservations", "tiq72_v515_reservations_run_id_key"):
        "uniquerun_id",
    ("tiq72_v515_reservations", "tiq72_v515_reservations_stripe_session_key"):
        "uniquestripe_session",
    ("tiq72_v515_reservations", "tiq72_v515_reservations_run_id_fkey"):
        "foreignkeyrun_idreferencestiq72_v515_runsrun_id",
    ("tiq72_v515_reports", "tiq72_v515_reports_pkey"): "primarykeyrun_id",
    ("tiq72_v515_reports", "tiq72_v515_reports_reservation_id_key"):
        "uniquereservation_id",
    ("tiq72_v515_reports", "tiq72_v515_reports_stripe_session_key"):
        "uniquestripe_session",
    ("tiq72_v515_reports", "tiq72_v515_reports_run_id_fkey"):
        "foreignkeyrun_idreferencestiq72_v515_runsrun_id",
    ("tiq72_v515_reports", "tiq72_v515_reports_reservation_id_fkey"):
        "foreignkeyreservation_idreferencestiq72_v515_reservationsreservation_id",
    ("tiq72_v515_verified_events", "tiq72_v515_verified_events_pkey"):
        "primarykeyevent_id",
    ("tiq72_v515_verified_events", "tiq72_v515_verified_events_reservation_id_fkey"):
        "foreignkeyreservation_idreferencestiq72_v515_reservationsreservation_id",
}

REQUIRED_INDEX_DEFINITIONS = {
    ("tiq72_v515_reservations", "tiq72_v515_res_owner_run"):
        "usingbtreeowner_id,run_id",
    ("tiq72_v515_verified_events", "tiq72_v515_events_reservation"):
        "usingbtreereservation_id,received_at",
}


def normalized_catalog_definition(value):
    """Normalize only harmless PostgreSQL formatting, never remove predicates."""
    if not isinstance(value, str):
        return ""
    return re.sub(r"[\s()]", "", value.lower()).replace("~~", "like").replace("::text", "")



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
    expected_columns = {
        (table, column): spec
        for table, specs in COLUMNS.items()
        for column, spec in specs.items()
    }
    # Even an additional unreviewed column changes the isolated contract.
    if columns != expected_columns:
        return False

    cursor.execute(
        "SELECT t.relname, con.conname, con.contype, ref.relname, "
        "pg_catalog.pg_get_constraintdef(con.oid), con.convalidated "
        "FROM pg_catalog.pg_constraint con "
        "JOIN pg_catalog.pg_class t ON t.oid=con.conrelid "
        "JOIN pg_catalog.pg_namespace ns ON ns.oid=t.relnamespace "
        "LEFT JOIN pg_catalog.pg_class ref ON ref.oid=con.confrelid "
        "WHERE ns.nspname='public' AND t.relname = ANY(%s)",
        (list(TABLES),),
    )
    constraints = {
        (table, name): (kind, foreign, definition, validated)
        for table, name, kind, foreign, definition, validated in cursor.fetchall()
    }
    if any(
        (table, name) not in constraints or
        constraints[(table, name)][:2] != (kind, reference) or
        constraints[(table, name)][3] is not True
        for table, name, kind, reference in CONSTRAINTS
    ):
        return False
    if any(
        normalized_catalog_definition(constraints[pair][2]) != expected
        for pair, expected in REQUIRED_CHECK_DEFINITIONS.items()
    ):
        return False

    if any(
        normalized_catalog_definition(constraints[pair][2]) != expected
        for pair, expected in REQUIRED_KEY_DEFINITIONS.items()
    ):
        return False

    cursor.execute(
        "SELECT t.relname, i.relname, ix.indisvalid, ix.indisready, "
        "pg_catalog.pg_get_indexdef(ix.indexrelid) "
        "FROM pg_catalog.pg_index ix "
        "JOIN pg_catalog.pg_class t ON t.oid=ix.indrelid "
        "JOIN pg_catalog.pg_class i ON i.oid=ix.indexrelid "
        "JOIN pg_catalog.pg_namespace ns ON ns.oid=t.relnamespace "
        "WHERE ns.nspname='public' AND t.relname = ANY(%s)",
        (list(TABLES),),
    )
    indexes = {
        (table, index): (valid, ready, definition)
        for table, index, valid, ready, definition in cursor.fetchall()
    }
    return all(
        indexes.get(pair, (False, False, ""))[:2] == (True, True)
        and normalized_catalog_definition(indexes[pair][2]).endswith(
            REQUIRED_INDEX_DEFINITIONS[pair])
        for pair in INDEXES
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
            # Catalog-only inventory: do not read customer rows or emit names.
            cur.execute(
                "SELECT count(*) FROM information_schema.tables "
                "WHERE table_schema='public' AND table_type='BASE TABLE'"
            )
            public_table_count = int(cur.fetchone()[0])
            # Inventory non-system schemas without exposing names or row contents.
            cur.execute(
                "SELECT count(*) FROM pg_catalog.pg_class c "
                "JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace "
                "WHERE c.relkind IN ('r','p') "
                "AND n.nspname NOT IN ('public','information_schema') "
                "AND n.nspname NOT LIKE 'pg_%'"
            )
            other_schema_table_count = int(cur.fetchone()[0])
            missing = sorted(set(TABLES) - found)
            contract = not missing and schema_contract_verified(cur)
        print(json.dumps({
            "status": "identity_verified_read_only",
            "expected_tables_present": sorted(found),
            "public_base_table_count": public_table_count,
            "other_schema_table_count": other_schema_table_count,
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
