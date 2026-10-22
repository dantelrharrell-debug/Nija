"""Offline NIJA legacy global preservation tests; never touch a live ledger."""
from __future__ import annotations

import io
import json
import os
from pathlib import Path
import stat
import zipfile

import pytest

from scripts import nija_legacy_global_state_evidence_v462 as recovery


def _sources(tmp_path):
    root = tmp_path / "persistent"
    root.mkdir()
    legacy = tmp_path / "legacy"
    legacy.mkdir()
    position = legacy / "positions.json"
    entry = legacy / "entry_prices.json"
    position.write_bytes(b'{"positions":{"BABY-USD":{"quantity":0.00142}}}')
    entry.write_bytes(b'{"BABY-USD":{"source":"reconciliation_required"}}')
    return root, position, entry


def _save(tmp_path, sources=None):
    root, position, entry = _sources(tmp_path)
    selected = sources or {"global-positions": position, "global-entry": entry}
    result = recovery.create_archive(
        selected, tmp_path / "private-output", persistent_root=root,
    )
    return root, position, entry, result


def test_capture_preserves_legacy_bytes_without_certifying_anything(tmp_path):
    root, position, entry, result = _save(tmp_path)
    a, b = position.read_bytes(), entry.read_bytes()
    archive = Path(result["archive"])
    assert archive.is_file()
    assert stat.S_IMODE(archive.stat().st_mode) == 0o600
    assert stat.S_IMODE(archive.parent.stat().st_mode) == 0o700
    with zipfile.ZipFile(archive) as source:
        assert set(source.namelist()) == {
            "manifest.json", "legacy/global-positions", "legacy/global-entry",
        }
        assert source.read("legacy/global-positions") == a
        assert source.read("legacy/global-entry") == b
        manifest = json.loads(source.read("manifest.json"))
        for key in (
            "account_scope_provenance_verified", "legacy_path_inventory_complete",
            "off_host_custody_verified", "isolated_restore_verified",
            "cross_store_atomicity_verified", "broker_reconciliation_verified",
            "trading_authorized",
        ):
            assert manifest[key] is False
    checked = recovery.verify_archive(
        archive, expected_sha256=result["archive_sha256"],
    )
    assert checked["files_verified"] == 2
    assert checked["off_host_custody_verified"] is False
    assert checked["trading_authorized"] is False
    assert (position.read_bytes(), entry.read_bytes()) == (a, b)
    assert not list(root.glob("**/*.zip"))


def test_missing_default_candidate_never_proves_complete_inventory(tmp_path):
    root, position, entry = _sources(tmp_path)
    absent = tmp_path / "not-present.json"
    result = recovery.create_archive(
        {"present": position, "missing": absent},
        tmp_path / "private-output", persistent_root=root,
    )
    assert result["missing_source_labels"] == ["missing"]
    with zipfile.ZipFile(result["archive"]) as archive:
        manifest = json.loads(archive.read("manifest.json"))
        assert manifest["legacy_path_inventory_complete"] is False
    with pytest.raises(ValueError, match="no legacy bytes found"):
        recovery.create_archive(
            {"missing": absent},
            tmp_path / "another-private-output", persistent_root=root,
        )


def test_source_symlink_and_hardlink_are_denied(tmp_path):
    root, position, entry = _sources(tmp_path)
    link = tmp_path / "aliased.json"
    link.symlink_to(position)
    with pytest.raises(ValueError, match="unsafe"):
        recovery.create_archive(
            {"link": link}, tmp_path / "out-one", persistent_root=root,
        )
    hardlink = tmp_path / "hardlinked.json"
    os.link(position, hardlink)
    with pytest.raises(ValueError, match="unsafe"):
        recovery.create_archive(
            {"hardlink": hardlink}, tmp_path / "out-two", persistent_root=root,
        )


def test_source_changes_mid_read_are_denied(tmp_path, monkeypatch):
    root, position, entry = _sources(tmp_path)
    original = recovery._read_stable_file

    def changed(source):
        raw = original(source)
        position.write_bytes(b'{"changed":true}')
        return raw

    monkeypatch.setattr(recovery, "_read_stable_file", changed)
    with pytest.raises(ValueError, match="changed across capture passes"):
        recovery.create_archive(
            {"legacy": position}, tmp_path / "first", persistent_root=root,
        )
    assert not list((tmp_path / "first").glob("*.zip"))


def test_same_bytes_replaced_inode_between_capture_passes_denied(tmp_path, monkeypatch):
    root, position, _ = _sources(tmp_path)
    original = recovery._read_stable_file
    calls = 0

    def replace_with_identical_bytes(source):
        nonlocal calls
        calls += 1
        if calls == 2:
            replacement = position.with_suffix(".replacement")
            replacement.write_bytes(position.read_bytes())
            os.replace(replacement, position)
        return original(source)

    monkeypatch.setattr(recovery, "_read_stable_file", replace_with_identical_bytes)
    with pytest.raises(ValueError, match="changed across capture passes"):
        recovery.create_archive(
            {"legacy": position}, tmp_path / "private-out", persistent_root=root,
        )
    assert not list((tmp_path / "private-out").glob("*.zip"))


def test_output_inside_live_mount_and_world_readable_output_denied(tmp_path):
    root, position, entry = _sources(tmp_path)
    with pytest.raises(ValueError, match="inside live persistent root"):
        recovery.create_archive(
            {"legacy": position}, root / "out", persistent_root=root,
        )
    output = tmp_path / "shared"
    output.mkdir(mode=0o755)
    output.chmod(0o755)
    with pytest.raises(ValueError, match="not private"):
        recovery.create_archive(
            {"legacy": position}, output, persistent_root=root,
        )


def test_archive_hash_and_duplicate_members_are_denied(tmp_path):
    _, _, _, result = _save(tmp_path)
    original = Path(result["archive"])
    with pytest.raises(ValueError, match="SHA-256"):
        recovery.verify_archive(original, expected_sha256="0" * 64)
    symlink = tmp_path / "alias.zip"
    symlink.symlink_to(original)
    with pytest.raises(ValueError, match="symlink"):
        recovery.verify_archive(symlink, expected_sha256=result["archive_sha256"])

    corrupted = tmp_path / "duplicate.zip"
    with zipfile.ZipFile(original) as source, zipfile.ZipFile(corrupted, "w") as target:
        for name in source.namelist():
            target.writestr(name, source.read(name))
        target.writestr("legacy/global-entry", b"malicious addition")
    with pytest.raises(ValueError, match="duplicate"):
        recovery.verify_archive(
            corrupted, expected_sha256=recovery._sha(corrupted.read_bytes()),
        )


def test_archive_claim_forgery_fails_closed(tmp_path):
    _, _, _, result = _save(tmp_path)
    source = Path(result["archive"])
    forged = tmp_path / "forged.zip"
    with zipfile.ZipFile(source) as original, zipfile.ZipFile(forged, "w") as target:
        for name in original.namelist():
            raw = original.read(name)
            if name == "manifest.json":
                manifest = json.loads(raw)
                manifest["trading_authorized"] = True
                raw = json.dumps(manifest).encode()
            target.writestr(name, raw)
    with pytest.raises(ValueError, match="forbidden"):
        recovery.verify_archive(
            forged, expected_sha256=recovery._sha(forged.read_bytes()),
        )


def test_corrupt_member_and_path_injection_denied(tmp_path):
    _, _, _, result = _save(tmp_path)
    source = Path(result["archive"])
    forged = tmp_path / "corrupt.zip"
    with zipfile.ZipFile(source) as original, zipfile.ZipFile(forged, "w") as target:
        for name in original.namelist():
            raw = original.read(name)
            if name == "legacy/global-entry":
                raw = b'{"faked":true}'
            target.writestr(name, raw)
    with pytest.raises(ValueError, match="member hash mismatch"):
        recovery.verify_archive(
            forged, expected_sha256=recovery._sha(forged.read_bytes()),
        )
    traversal = tmp_path / "traversal.zip"
    with zipfile.ZipFile(source) as original, zipfile.ZipFile(traversal, "w") as target:
        for name in original.namelist():
            target.writestr(name, original.read(name))
        target.writestr("../secret.json", b"leak")
    with pytest.raises(ValueError, match="membership mismatch"):
        recovery.verify_archive(
            traversal, expected_sha256=recovery._sha(traversal.read_bytes()),
        )
    assert not (tmp_path / "secret.json").exists()


def test_invalid_labels_and_duplicate_source_inodes_rejected(tmp_path):
    root, position, entry = _sources(tmp_path)
    with pytest.raises(ValueError, match="label"):
        recovery.create_archive(
            {"../../bad": position}, tmp_path / "label-out", persistent_root=root,
        )
    with pytest.raises(ValueError, match="duplicate legacy source inode"):
        recovery.create_archive(
            {"first": position, "second": position},
            tmp_path / "duplicate-out", persistent_root=root,
        )


def test_main_failure_is_non_authorizing(tmp_path, capsys, monkeypatch):
    root = tmp_path / "persistent"
    root.mkdir()
    monkeypatch.setattr(
        "sys.argv",
        ["nija_legacy_global_state_evidence_v462.py", "snapshot",
         "--persistent-root", str(root),
         "--output-dir", str(tmp_path / "output"),
         "--source", "invalid=no-absolute-path"],
    )
    assert recovery.main() == 1
    report = json.loads(capsys.readouterr().err)
    assert report["status"] == "FAILED_CLOSED"
    assert report["trading_authorized"] is False
