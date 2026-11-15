#!/usr/bin/env python3
"""Test-only TIQ72 ledger migration. Never connect to NIJA billing or Kraken."""
from __future__ import annotations
import argparse
import os
from pathlib import Path
from urllib.parse import urlsplit, unquote

DB = "nija_tiq72_test_ledger_20261115"
HOST = "dpg-dbsuhuc9v7es73bmteeg-a"
USER = "nija_tiq72_test_ledger_20261115_user"
SCHEMA = Path(__file__).resolve().parents[1] / "web/trading-challenge/v515/server/sql/tiq72-v515-report-ledger.sql"
TABLES = frozenset(("tiq72_v515_runs", "tiq72_v515_reservations", "tiq72_v515_reports", "tiq72_v515_verified_events"))

class MigrationDenied(Exception):
    pass

def verify_private_url(value):
    if not isinstance(value,str) or not value or len(value)>2048:
        raise MigrationDenied("private_url_required")
    try:
        u=urlsplit(value)
        port=u.port or 5432
        username=unquote(u.username or "")
        database=unquote(u.path.lstrip("/"))
    except (ValueError,TypeError):
        raise MigrationDenied("invalid_private_url") from None
    if (u.scheme not in ("postgres","postgresql") or u.hostname!=HOST or
        username!=USER or database!=DB or not u.password or port!=5432 or
        u.query not in ("","sslmode=require") or u.fragment):
        raise MigrationDenied("database_identity_mismatch")

def migrate(url, apply=False, connect=None):
    verify_private_url(url)
    sql=SCHEMA.read_text(encoding="utf-8")
    if (not sql.startswith("-- TIQ v515 test-only durable ledger.") or
        "BEGIN;" not in sql or "COMMIT;" not in sql or
        any("CREATE TABLE IF NOT EXISTS "+t not in sql for t in TABLES)):
        raise MigrationDenied("reviewed_migration_required")
    if connect is None:
        from psycopg2 import connect
    try:
        db=connect(url, connect_timeout=8, sslmode="require")
        try:
            with db.cursor() as cursor:
                cursor.execute("SELECT current_database(), current_user")
                if tuple(cursor.fetchone())!=(DB,USER):
                    raise MigrationDenied("connected_identity_mismatch")
                if not apply:
                    db.rollback()
                    return "identity_verified_no_changes"
                if os.getenv("NIJA_TIQ72_TEST_SCHEMA_APPLY")!="APPROVED_TEST_ONLY":
                    raise MigrationDenied("apply_gate_required")
                cursor.execute(sql)
                cursor.execute("SELECT tablename FROM pg_tables WHERE schemaname=current_schema() AND tablename LIKE %s", ("tiq72_v515_%",))
                if not TABLES.issubset({row[0] for row in cursor.fetchall()}):
                    raise MigrationDenied("schema_postcondition_failed")
            db.commit()
            return "isolated_test_schema_installed"
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()
    except MigrationDenied:
        raise
    except Exception:
        raise MigrationDenied("private_database_operation_failed") from None

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--apply", action="store_true")
    args=p.parse_args()
    try:
        result=migrate(os.getenv("TIQ72_TEST_DATABASE_URL",""),apply=args.apply)
    except (MigrationDenied,OSError):
        print("TIQ72: test migration denied; no credentials disclosed")
        return 2
    print("TIQ72: "+result)
    return 0

if __name__=="__main__":
    raise SystemExit(main())
