"""Offline fail-closed tests for scoped NIJA account-state evidence archives."""
from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path

import pytest

from scripts import nija_account_state_offhost_evidence_v449 as audit


def _fixture(tmp_path):
    root = tmp_path / "data"
    positions = root / "positions"
    entries = root / "entry_prices"
    positions.mkdir(parents=True)
    entries.mkdir()
    position = positions / "platform__kraken.json"
    price = entries / "platform__kraken.json"
    position.write_text('{"positions":{"BABY-USD":{"quantity":0.00142}}}')
    price.write_text('{"entry_prices":{"BABY-USD":{"verified":false}}}')
    return root, positions, entries, position, price


def _backup(tmp_path, *, root=None, positions=None, entries=None):
    root, positions, entries, _, _ = (root, positions, entries, None, None) if root else _fixture(tmp_path)
    return audit.create_archive(
        persistent_root=root, positions_dir=positions, entry_prices_dir=entries,
        output_dir=tmp_path / "out",
    )


def test_archive_roundtrip_is_read_only_and_does_not_certify_trading(tmp_path):
    root, positions, entries, position, price = _fixture(tmp_path)
    original = (position.read_bytes(), price.read_bytes())
    result = _backup(tmp_path, root=root, positions=positions, entries=entries)
    assert result["account_files"] == 2
    assert result["off_host_copy_verified"] is False
    assert result["trading_authorized"] is False
    archive = Path(result["archive"])
    assert archive.stat().st_mode & 0o777 == 0o600
    verified = audit.verify_archive(archive, expected_sha256=result["sha256"])
    assert verified["account_files_verified"] == 2
    assert verified["archive_sha256_matched"] is True
    assert verified["off_host_custody_independently_verified"] is False
    assert verified["live_ledger_to_json_atomicity_verified"] is False
    assert verified["historical_cost_basis_verified"] is False
    assert verified["trading_authorized"] is False
    assert (position.read_bytes(), price.read_bytes()) == original
    assert not list(root.glob("*.zip"))


def test_all_account_scopes_are_distinct_in_archive(tmp_path):
    root, positions, entries, _, _ = _fixture(tmp_path)
    (positions / "user__test_account__kraken.json").write_text('{"positions":{}}')
    result = _backup(tmp_path, root=root, positions=positions, entries=entries)
    with zipfile.ZipFile(result["archive"]) as source:
        assert set(source.namelist()) == {
            "positions/platform__kraken.json",
            "positions/user__test_account__kraken.json",
            "entry_prices/platform__kraken.json",
            "manifest.json",
        }
    assert audit.verify_archive(Path(result["archive"]), expected_sha256=result["sha256"])[
        "account_files_verified"
    ] == 3


def test_invalid_source_raises_without_creating_archive(tmp_path):
    root, positions, entries, position, _ = _fixture(tmp_path)
    cases = ('{"x": NaN}', '{"x": Infinity}', "[]", "not-json")
    for contents in cases:
        position.write_text(contents)
        with pytest.raises(ValueError, match="account JSON"):
            _backup(tmp_path, root=root, positions=positions, entries=entries)
    assert not (tmp_path / "out").exists()


def test_symlink_and_unexpected_account_file_fail_closed(tmp_path):
    root, positions, entries, position, _ = _fixture(tmp_path)
    link = positions / "user__outside__kraken.json"
    link.symlink_to(position)
    with pytest.raises(OSError):
        _backup(tmp_path, root=root, positions=positions, entries=entries)
    link.unlink()
    (positions / "credential.txt").write_text("not part of state")
    with pytest.raises(ValueError, match="filename"):
        _backup(tmp_path, root=root, positions=positions, entries=entries)


def test_account_directory_escape_and_live_mount_output_rejected(tmp_path):
    root, positions, entries, _, _ = _fixture(tmp_path)
    other = tmp_path / "outside"
    other.mkdir()
    with pytest.raises(ValueError, match="outside persistent"):
        _backup(tmp_path, root=root, positions=positions, entries=other)
    with pytest.raises(ValueError, match="output must not"):
        audit.create_archive(persistent_root=root, positions_dir=positions,
                             entry_prices_dir=entries, output_dir=root / "exports")


def test_position_inventory_cannot_be_empty(tmp_path):
    root, positions, entries, position, _ = _fixture(tmp_path)
    position.unlink()
    with pytest.raises(ValueError, match="empty"):
        _backup(tmp_path, root=root, positions=positions, entries=entries)


def test_archive_hash_mismatch_and_symlink_input_rejected(tmp_path):
    record = _backup(tmp_path)
    archive = Path(record["archive"])
    with pytest.raises(ValueError, match="checksum"):
        audit.verify_archive(archive, expected_sha256="0" * 64)
    link = tmp_path / "alias.zip"
    link.symlink_to(archive)
    with pytest.raises(ValueError, match="unsafe"):
        audit.verify_archive(link, expected_sha256=record["sha256"])


def _rewrite(src: Path, dst: Path, overrides: dict[str, bytes]):
    with zipfile.ZipFile(src) as source, zipfile.ZipFile(dst, "w") as target:
        for name in source.namelist():
            target.writestr(name, overrides.get(name, source.read(name)))
        for name, raw in overrides.items():
            if name not in source.namelist():
                target.writestr(name, raw)
    return audit._sha(dst.read_bytes())


def test_member_tampering_and_path_traversal_rejected(tmp_path):
    result = _backup(tmp_path)
    original = Path(result["archive"])
    tampered = tmp_path / "tampered.zip"
    digest = _rewrite(original, tampered, {"positions/platform__kraken.json": b'{"positions":{"x":5}}'})
    with pytest.raises(ValueError, match="checksum"):
        audit.verify_archive(tampered, expected_sha256=digest)
    traversal = tmp_path / "traversal.zip"
    digest = _rewrite(original, traversal, {"../secrets.txt": b"do not unpack"})
    with pytest.raises(ValueError, match="unsafe archive"):
        audit.verify_archive(traversal, expected_sha256=digest)
    assert not (tmp_path / "secrets.txt").exists()


def test_duplicate_entry_and_undeclared_member_rejected(tmp_path):
    record = _backup(tmp_path)
    original = Path(record["archive"])
    duplicate = tmp_path / "duplicate.zip"
    with zipfile.ZipFile(original) as source, zipfile.ZipFile(duplicate, "w") as target:
        for name in source.namelist():
            target.writestr(name, source.read(name))
        with pytest.warns(UserWarning):
            target.writestr("positions/platform__kraken.json", b"{}")
    with pytest.raises(ValueError, match="duplicate"):
        audit.verify_archive(duplicate, expected_sha256=audit._sha(duplicate.read_bytes()))


def test_symlinked_output_directory_rejected(tmp_path):
    root, positions, entries, _, _ = _fixture(tmp_path)
    out = tmp_path / "output_real"
    out.mkdir()
    alias = tmp_path / "output_alias"
    alias.symlink_to(out, target_is_directory=True)
    with pytest.raises(ValueError, match="output"):
        audit.create_archive(persistent_root=root, positions_dir=positions,
                             entry_prices_dir=entries, output_dir=alias)
