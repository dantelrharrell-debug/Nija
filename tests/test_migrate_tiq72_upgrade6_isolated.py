"""Offline gates for NIJA same-workspace isolated test PostgreSQL migration."""
from __future__ import annotations
import importlib.util
import secrets
from pathlib import Path
from unittest.mock import patch
import pytest

PATH = Path(__file__).resolve().parents[1] / "scripts/migrate_tiq72_upgrade6_isolated.py"
spec = importlib.util.spec_from_file_location("tiq72_safe_migration", PATH)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

def url(host=module.HOST, db=module.DB, user=module.USER, port="5432"):
    # Disposable values only; these tests inject fake connections and never connect.
    credential = secrets.token_urlsafe(24)
    return f"postgresql://{user}:{credential}@{host}:{port}/{db}"

class Cursor:
    def __init__(self, identity=None, tables=None):
        self.identity = identity or (module.DB,module.USER)
        self.tables = tables or [(x,) for x in module.TABLES]
        self.queries = []
    def __enter__(self): return self
    def __exit__(self,*args): return False
    def execute(self, sql, params=None): self.queries.append((sql,params))
    def fetchone(self): return self.identity
    def fetchall(self): return self.tables

class Connection:
    def __init__(self, cursor=None):
        self.c = cursor or Cursor()
        self.commits=0;self.rollbacks=0;self.closed=0
    def cursor(self): return self.c
    def commit(self): self.commits+=1
    def rollback(self): self.rollbacks+=1
    def close(self): self.closed+=1

@pytest.mark.parametrize("uri",[
    url(host="external.example"), url(db="nija_billing_db"),
    url(user="nija_course_sandbox_user"),
    url(host="127.0.0.1", user="user"),
    "https://example.com", "", url(host="broken", user="test", db="db", port="bad"),
    url()+"?sslmode=disable",
])
def test_only_explicit_private_test_database(uri):
    with pytest.raises(module.MigrationDenied):
        module.verify_private_url(uri)

def test_readonly_preflight_checks_identity_without_running_schema():
    db=Connection()
    assert module.migrate(url(),connect=lambda *a,**k:db)=="identity_verified_no_changes"
    assert db.commits==0 and db.rollbacks==1 and db.closed==1
    assert len(db.c.queries)==1
    assert db.c.queries[0][0]=="SELECT current_database(), current_user"

def test_wrong_connected_database_rejected_even_if_url_claims_right_database():
    db=Connection(Cursor(identity=("nija_billing_db","nija_billing_db_user")))
    with pytest.raises(module.MigrationDenied,match="connected_identity_mismatch"):
        module.migrate(url(),connect=lambda *a,**k:db)
    assert db.commits==0 and db.rollbacks==1

def test_apply_requires_explicit_env_gate():
    db=Connection()
    with patch.dict("os.environ",{"NIJA_TIQ72_ISOLATED_SCHEMA_APPLY":"false"}):
        with pytest.raises(module.MigrationDenied,match="apply_gate_required"):
            module.migrate(url(),apply=True,connect=lambda *a,**k:db)
    assert db.commits==0 and db.rollbacks==1

def test_apply_requires_separate_backup_restore_gate():
    db=Connection()
    with patch.dict("os.environ",{"NIJA_TIQ72_ISOLATED_SCHEMA_APPLY":"APPROVED_TEST_ONLY",
                                  "NIJA_TIQ72_ISOLATED_BACKUP_RESTORE_VERIFIED":"NO"}):
        with pytest.raises(module.MigrationDenied,match="backup_restore_gate_required"):
            module.migrate(url(),apply=True,connect=lambda *a,**k:db)
    assert db.commits==0 and db.rollbacks==1

def test_apply_checks_all_tables_and_commits_only_on_success():
    db=Connection()
    with patch.dict("os.environ",{"NIJA_TIQ72_TEST_SCHEMA_APPLY":"APPROVED_TEST_ONLY"}):
        assert module.migrate(url(),apply=True,connect=lambda *a,**k:db)=="isolated_test_schema_installed"
    assert db.commits==1 and db.rollbacks==0 and db.closed==1
    ddl = [q[0] for q in db.c.queries if "CREATE TABLE IF NOT EXISTS tiq72_v515_runs" in q[0]]
    assert len(ddl) == 1
    assert "BEGIN;" not in ddl[0] and "COMMIT;" not in ddl[0]
    assert db.c.queries[-1][0].startswith("SELECT tablename FROM pg_tables")

def test_missing_table_rolls_back():
    db=Connection(Cursor(tables=[("tiq72_v515_runs",)]))
    with patch.dict("os.environ",{"NIJA_TIQ72_TEST_SCHEMA_APPLY":"APPROVED_TEST_ONLY"}):
        with pytest.raises(module.MigrationDenied,match="schema_postcondition_failed"):
            module.migrate(url(),apply=True,connect=lambda *a,**k:db)
    assert db.commits==0 and db.rollbacks==1

def test_provider_exception_is_redacted():
    def connect(*a,**k): raise RuntimeError("secret-in-provider-exception")
    with pytest.raises(module.MigrationDenied,match="private_database_operation_failed") as e:
        module.migrate(url(),connect=connect)
    assert "secret-in-provider-exception" not in str(e.value)

@pytest.mark.parametrize("line_ending", ["\n", "\r\n"])
def test_schema_line_endings_preserve_one_transaction(tmp_path, monkeypatch, line_ending):
    schema = tmp_path / "schema.sql"
    original = module.SCHEMA.read_text()
    schema.write_bytes(original.replace("\n", line_ending).encode())
    monkeypatch.setattr(module, "SCHEMA", schema)
    monkeypatch.setenv("NIJA_TIQ72_TEST_SCHEMA_APPLY", "APPROVED_TEST_ONLY")
    db = Connection()
    assert module.migrate(url(), apply=True, connect=lambda *a, **k: db) == "isolated_test_schema_installed"
    assert db.commits == 1 and db.rollbacks == 0
    assert "BEGIN;" not in db.c.queries[1][0] and "COMMIT;" not in db.c.queries[1][0]

@pytest.mark.parametrize("change,reason", [
    (lambda sql: sql.replace("\nBEGIN;\n", "\nBEGIN;\n\nBEGIN;\n"), "schema_transaction_boundary_invalid"),
    (lambda sql: sql + "\nSELECT 1;", "schema_trailing_statement_forbidden"),
    (lambda sql: sql.replace("\nCOMMIT;", "\nBEGIN; SELECT 1;\nCOMMIT;"), "nested_transaction_disallowed"),
])
def test_unsafe_transaction_boundaries_never_execute_schema(tmp_path, monkeypatch, change, reason):
    schema = tmp_path / "schema.sql"
    schema.write_text(change(module.SCHEMA.read_text()))
    monkeypatch.setattr(module, "SCHEMA", schema)
    monkeypatch.setenv("NIJA_TIQ72_TEST_SCHEMA_APPLY", "APPROVED_TEST_ONLY")
    db = Connection()
    with pytest.raises(module.MigrationDenied, match=reason):
        module.migrate(url(), apply=True, connect=lambda *a, **k: db)
    assert db.commits == 0 and db.rollbacks == 1 and db.closed == 1
    assert len(db.c.queries) == 1
