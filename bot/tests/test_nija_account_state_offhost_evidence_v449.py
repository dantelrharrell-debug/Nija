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
    cases = (
        '{"x": NaN}', '{"x": Infinity}',
        '{"positions":{"BABY":{"price":1e999}}}',
        '{"positions":{},"positions":{"BABY":{}}}',
        '{"positions":{"BABY":{"quantity":1,"quantity":2}}}',
        "[]", "not-json",
    )
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


def test_cross_account_change_between_passes_aborts(monkeypatch, tmp_path):
    root, positions, entries, position, _ = _fixture(tmp_path)
    original = audit._inventory
    calls = []

    def mutate_between_passes(persistent, directories):
        captured = original(persistent, directories)
        calls.append(1)
        if len(calls) == 1:
            position.write_text('{"positions":{"BABY-USD":{"quantity":2}}}')
        return captured

    monkeypatch.setattr(audit, "_inventory", mutate_between_passes)
    with pytest.raises(ValueError, match="changed across collection passes"):
        _backup(tmp_path, root=root, positions=positions, entries=entries)
    assert len(calls) == 2
    assert not (tmp_path / "out").exists()


def test_account_archive_total_memory_budget_fails_closed(monkeypatch, tmp_path):
    root, positions, entries, _, _ = _fixture(tmp_path)
    monkeypatch.setattr(audit, "MAX_TOTAL_JSON_BYTES", 8)
    with pytest.raises(ValueError, match="total byte budget"):
        _backup(tmp_path, root=root, positions=positions, entries=entries)
    assert not (tmp_path / "out").exists()


def test_duplicate_manifest_keys_fail_closed(tmp_path):
    record = _backup(tmp_path)
    original = Path(record["archive"])
    with zipfile.ZipFile(original, "r") as source:
        manifest = source.read("manifest.json")
    assert b'"format_version":1' in manifest
    tampered = manifest.replace(
        b'"format_version":1', b'"format_version":1,"format_version":1', 1,
    )
    archive = tmp_path / "duplicate-manifest.zip"
    digest = _rewrite(original, archive, {"manifest.json": tampered})
    with pytest.raises(ValueError, match="duplicate account JSON"):
        audit.verify_archive(archive, expected_sha256=digest)


def test_boolean_manifest_version_is_not_format_v1(tmp_path):
    record = _backup(tmp_path)
    original = Path(record["archive"])
    with zipfile.ZipFile(original, "r") as source:
        manifest = source.read("manifest.json")
    assert b'"format_version":1' in manifest
    archive = tmp_path / "boolean-version.zip"
    digest = _rewrite(
        original, archive, {
            "manifest.json": manifest.replace(
                b'"format_version":1', b'"format_version":true', 1,
            ),
        },
    )
    with pytest.raises(ValueError, match="invalid archive manifest"):
        audit.verify_archive(archive, expected_sha256=digest)


def test_fifo_account_file_fails_immediately(tmp_path):
    """O_NONBLOCK must reject a valid-looking FIFO without a writer/hang."""
    import os
    root, positions, entries, _, _ = _fixture(tmp_path)
    fifo = positions / "platform__fifo.json"
    os.mkfifo(fifo)
    with pytest.raises(ValueError, match="unsafe or oversized"):
        _backup(tmp_path, root=root, positions=positions, entries=entries)
    assert not (tmp_path / "out").exists()


def test_same_directory_cannot_be_positions_and_entry_prices(tmp_path):
    root, positions, entries, _, _ = _fixture(tmp_path)
    with pytest.raises(ValueError, match="share filesystem identity"):
        _backup(tmp_path, root=root, positions=positions, entries=positions)
    assert not (tmp_path / "out").exists()


def test_leaf_directory_symlink_refused_inside_mount(tmp_path):
    root, positions, entries, _, price = _fixture(tmp_path)
    price.unlink()
    entries.rmdir()
    entries.symlink_to(positions, target_is_directory=True)
    with pytest.raises(ValueError, match="source directory symlink"):
        _backup(tmp_path, root=root, positions=positions, entries=entries)
    assert not (tmp_path / "out").exists()


def test_parent_data_symlink_to_persistent_mount_still_works(tmp_path):
    root, positions, entries, _, _ = _fixture(tmp_path)
    app = tmp_path / "app"
    app.mkdir()
    (app / "data").symlink_to(root, target_is_directory=True)
    report = _backup(tmp_path, root=root, positions=app / "data" / "positions",
                     entries=app / "data" / "entry_prices")
    assert report["account_files"] == 2
    assert audit.verify_archive(Path(report["archive"]), expected_sha256=report["sha256"])[
        "trading_authorized"
    ] is False


def test_parent_alias_swap_does_not_escape_pinned_root(monkeypatch, tmp_path):
    root, positions, entries, _, _ = _fixture(tmp_path)
    app = tmp_path / "app"
    app.mkdir()
    alias = app / "data"
    alias.symlink_to(root, target_is_directory=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "positions").mkdir()
    (outside / "entry_prices").mkdir()
    (outside / "positions" / "platform__kraken.json").write_text(
        '{"positions":{"UNAUTHORIZED":{"quantity":999}}}'
    )
    original = audit._open_root_anchored_directory
    calls = []

    def swap_after_resolution(root_fd, parts):
        if not calls:
            alias.unlink()
            alias.symlink_to(outside, target_is_directory=True)
        calls.append(1)
        return original(root_fd, parts)

    monkeypatch.setattr(audit, "_open_root_anchored_directory", swap_after_resolution)
    # First pass uses root-anchored descriptors even after the alias is
    # retargeted; the second pass must reject the now out-of-root alias.
    # No unsafe archive is created and no outside data is captured.
    with pytest.raises(ValueError, match="outside persistent root"):
        _backup(tmp_path, root=root, positions=alias / "positions",
                entries=alias / "entry_prices")
    assert len(calls) == 1
    assert not (tmp_path / "out").exists()
