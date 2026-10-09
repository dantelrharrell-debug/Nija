"""Offline tests for non-mutating NIJA ledger snapshot and archive validation."""
from __future__ import annotations

import importlib.util
import sqlite3
from pathlib import Path

import pytest


SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "nija_trade_ledger_snapshot_v436.py"
spec = importlib.util.spec_from_file_location("nija_trade_ledger_snapshot_v436", SCRIPT)
assert spec and spec.loader
snapshot = importlib.util.module_from_spec(spec)
spec.loader.exec_module(snapshot)


def _ledger(path: Path) -> None:
    with sqlite3.connect(path) as conn:
        for name in snapshot.MANDATORY_TABLES:
            conn.execute(f"CREATE TABLE {name} (id INTEGER PRIMARY KEY, value TEXT)")
        conn.execute("INSERT INTO trade_ledger(value) VALUES ('immutable proof')")
        conn.commit()


def test_backup_roundtrip_integrity_and_original_unchanged(tmp_path, monkeypatch):
    original = tmp_path / "live.db"
    _ledger(original)
    original_sha = snapshot._sha256(original)
    monkeypatch.chdir(tmp_path)
    result = snapshot.create_snapshot(original, tmp_path / "exports")
    assert snapshot._sha256(original) == original_sha
    manifest = snapshot.verify_snapshot(Path(result["archive"]))
    assert manifest["sqlite_tables"]["trade_ledger"] == 1
    assert manifest["off_host_backup_verified"] is False
    assert manifest["restore_test_verified"] is False
    assert result["sha256"] == snapshot._sha256(Path(result["archive"]))


def test_missing_ledger_does_not_create_blank_database(tmp_path):
    absent = tmp_path / "absent.db"
    with pytest.raises(FileNotFoundError):
        snapshot.create_snapshot(absent, tmp_path / "exports")
    assert not absent.exists()


def test_missing_required_table_fails_closed(tmp_path):
    original = tmp_path / "incomplete.db"
    with sqlite3.connect(original) as conn:
        conn.execute("CREATE TABLE trade_ledger (id INTEGER PRIMARY KEY)")
    with pytest.raises(RuntimeError, match="tables missing"):
        snapshot.create_snapshot(original, tmp_path / "exports")


def test_snapshot_archive_rejects_member_tampering(tmp_path):
    original = tmp_path / "live.db"
    _ledger(original)
    result = snapshot.create_snapshot(original, tmp_path / "exports")
    import tarfile
    import io
    import json
    archive = Path(result["archive"])
    manifest = snapshot.verify_snapshot(archive)
    payload = io.BytesIO()
    with tarfile.open(fileobj=payload, mode="w:gz") as output:
        raw = b"malicious substitution"
        entry = tarfile.TarInfo("trade_ledger.db")
        entry.size = len(raw)
        output.addfile(entry, io.BytesIO(raw))
        data = json.dumps(manifest).encode()
        entry = tarfile.TarInfo("manifest.json")
        entry.size = len(data)
        output.addfile(entry, io.BytesIO(data))
    archive.write_bytes(payload.getvalue())
    with pytest.raises(ValueError, match="digest mismatch|size mismatch"):
        snapshot.verify_snapshot(archive)
