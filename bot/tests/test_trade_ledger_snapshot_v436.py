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


def test_isolated_restore_test_preserves_table_counts_without_touching_source(tmp_path, monkeypatch):
    original = tmp_path / "live.db"
    _ledger(original)
    original_sha = snapshot._sha256(original)
    monkeypatch.chdir(tmp_path)
    report = snapshot.create_snapshot(original, tmp_path / "exports")
    archive = Path(report["archive"])
    checked = snapshot.verify_snapshot(
        archive, expected_sha256=report["sha256"], exercise_restore=True,
    )
    assert checked["sqlite_tables"]["trade_ledger"] == 1
    assert checked["isolated_restore_test_verified"] is True
    assert checked["expected_archive_sha256_matched"] is True
    assert checked["off_host_backup_verified"] is False
    assert checked["historical_fill_completeness_verified"] is False
    assert checked["live_trading_eligible"] is False
    assert snapshot._sha256(original) == original_sha
    assert not list(tmp_path.glob("_isolated_restore.db"))


def test_restore_requires_matching_source_hash(tmp_path, monkeypatch):
    original = tmp_path / "live.db"
    _ledger(original)
    monkeypatch.chdir(tmp_path)
    report = snapshot.create_snapshot(original, tmp_path / "exports")
    with pytest.raises(ValueError, match="SHA-256"):
        snapshot.verify_snapshot(
            Path(report["archive"]), expected_sha256="0" * 64,
            exercise_restore=True,
        )


def test_restore_rejects_oversized_member_before_extraction(tmp_path, monkeypatch):
    original = tmp_path / "live.db"
    _ledger(original)
    monkeypatch.chdir(tmp_path)
    report = snapshot.create_snapshot(original, tmp_path / "exports")
    src = Path(report["archive"])
    malicious = tmp_path / "oversized.tar.gz"
    import io
    import tarfile
    with tarfile.open(src, "r:gz") as archive_in, tarfile.open(malicious, "w:gz") as archive_out:
        for member in archive_in.getmembers():
            data = archive_in.extractfile(member).read()
            info = tarfile.TarInfo(name=member.name)
            info.size = len(data)
            archive_out.addfile(info, io.BytesIO(data))
        data = b"x" * 100
        extra = tarfile.TarInfo(name="execution_journal.jsonl")
        extra.size = len(data)
        archive_out.addfile(extra, io.BytesIO(data))
    monkeypatch.setattr(snapshot, "MAX_COMPANION_BYTES", 64)
    with pytest.raises(ValueError, match="oversized"):
        snapshot.verify_snapshot(malicious)


def test_restore_rejects_archive_path_traversal(tmp_path, monkeypatch):
    original = tmp_path / "live.db"
    _ledger(original)
    monkeypatch.chdir(tmp_path)
    report = snapshot.create_snapshot(original, tmp_path / "exports")
    import io
    import tarfile
    malicious = tmp_path / "path-traversal.tar.gz"
    with tarfile.open(report["archive"], "r:gz") as archive_in, tarfile.open(malicious, "w:gz") as archive_out:
        for member in archive_in.getmembers():
            data = archive_in.extractfile(member).read()
            info = tarfile.TarInfo(name="../" + member.name if member.name == "trade_ledger.db" else member.name)
            info.size = len(data)
            archive_out.addfile(info, io.BytesIO(data))
    with pytest.raises(ValueError, match="unsafe"):
        snapshot.verify_snapshot(malicious)


def test_restore_rejects_oversized_pax_header_without_parsing_it(tmp_path, monkeypatch):
    """A PAX extension cannot allocate its attacker-declared metadata payload."""
    import io
    import tarfile

    original = tmp_path / "live.db"
    _ledger(original)
    monkeypatch.chdir(tmp_path)
    report = snapshot.create_snapshot(original, tmp_path / "exports")
    malicious = tmp_path / "oversized-pax.tar.gz"
    with tarfile.open(report["archive"], "r:gz") as source, tarfile.open(
        malicious, "w:gz", format=tarfile.PAX_FORMAT,
    ) as target:
        for member in source.getmembers():
            raw = source.extractfile(member).read()
            info = tarfile.TarInfo(member.name)
            info.size = len(raw)
            if member.name == "trade_ledger.db":
                info.pax_headers = {"comment": "X" * 20000}
            target.addfile(info, io.BytesIO(raw))
    with pytest.raises(ValueError, match="pax|metadata|unsafe|oversized"):
        snapshot.verify_snapshot(malicious)


def test_restore_rejects_pax_path_override(tmp_path, monkeypatch):
    """A PAX path override cannot redirect a recovered SQLite write."""
    import io
    import tarfile

    original = tmp_path / "live.db"
    _ledger(original)
    monkeypatch.chdir(tmp_path)
    report = snapshot.create_snapshot(original, tmp_path / "exports")
    malicious = tmp_path / "path-pax.tar.gz"
    with tarfile.open(report["archive"], "r:gz") as source, tarfile.open(
        malicious, "w:gz", format=tarfile.PAX_FORMAT,
    ) as target:
        for member in source.getmembers():
            raw = source.extractfile(member).read()
            info = tarfile.TarInfo(member.name)
            info.size = len(raw)
            if member.name == "trade_ledger.db":
                info.pax_headers = {"path": "../outside.db"}
            target.addfile(info, io.BytesIO(raw))
    with pytest.raises(ValueError, match="pax|metadata|unsafe"):
        snapshot.verify_snapshot(malicious)
    assert not (tmp_path / "outside.db").exists()


def test_archive_symlink_rejected(tmp_path, monkeypatch):
    original = tmp_path / "live.db"
    _ledger(original)
    monkeypatch.chdir(tmp_path)
    report = snapshot.create_snapshot(original, tmp_path / "exports")
    link = tmp_path / "archive-link.tar.gz"
    link.symlink_to(Path(report["archive"]))
    with pytest.raises(ValueError, match="symlink"):
        snapshot.verify_snapshot(link)


def test_verified_restore_uses_pinned_bytes_if_original_archive_is_replaced(tmp_path, monkeypatch):
    """A file swap between source hash and gzip parsing cannot change restore."""
    original = tmp_path / "live.db"
    _ledger(original)
    monkeypatch.chdir(tmp_path)
    report = snapshot.create_snapshot(original, tmp_path / "exports")
    archive = Path(report["archive"])
    original_gzip_open = snapshot.gzip.open
    swapped = []

    def replace_original_before_decompression(path, mode):
        if not swapped:
            # This replaces only the untrusted *input path*, never the pinned
            # copy the verifier already wrote to its private temp directory.
            archive.unlink()
            archive.write_bytes(b"tampered archive after verification")
            swapped.append(True)
        return original_gzip_open(path, mode)

    monkeypatch.setattr(snapshot.gzip, "open", replace_original_before_decompression)
    checked = snapshot.verify_snapshot(
        archive, expected_sha256=report["sha256"], exercise_restore=True,
    )
    assert swapped
    assert checked["expected_archive_sha256_matched"] is True
    assert checked["isolated_restore_test_verified"] is True
    assert checked["off_host_backup_verified"] is False
