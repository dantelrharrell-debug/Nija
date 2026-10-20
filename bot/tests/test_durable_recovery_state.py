"""Storage failure tests for the actual recovery modules' shared I/O."""
import json

import pytest

from bot import durable_recovery_state as state


def test_roundtrip_and_corruption_are_not_confused_with_absence(tmp_path):
    path = tmp_path / "state.json"
    assert state.read_recovery_state(path, "orders") == {}
    state.write_recovery_state(path, {"version": 1, "orders": {"oid": {"status": "pending"}}})
    assert state.read_recovery_state(path, "orders") == {"oid": {"status": "pending"}}
    path.write_text("truncated")
    with pytest.raises(ValueError):
        state.read_recovery_state(path, "orders")


@pytest.mark.parametrize("payload", [{}, {"version": 1, "orders": []},
                                    {"version": 1, "orders": {"oid": None}}])
def test_malformed_schema_never_becomes_an_empty_history(tmp_path, payload):
    path = tmp_path / "state.json"
    path.write_text(json.dumps(payload))
    with pytest.raises(ValueError):
        state.read_recovery_state(path, "orders")


def test_failed_file_fsync_preserves_previous_committed_bytes(tmp_path, monkeypatch):
    path = tmp_path / "state.json"
    state.write_recovery_state(path, {"version": 1, "orders": {"old": {}}})
    previous = path.read_bytes()

    def fail(fd):
        raise OSError("fsync failed")

    monkeypatch.setattr(state.os, "fsync", fail)
    with pytest.raises(OSError):
        state.write_recovery_state(path, {"version": 1, "orders": {"new": {}}})
    assert path.read_bytes() == previous
    assert not list(tmp_path.glob("*.tmp"))


def test_failed_directory_fsync_does_not_report_success(tmp_path, monkeypatch):
    path = tmp_path / "state.json"
    real_fsync = state.os.fsync
    calls = []

    def fail_directory(fd):
        calls.append(fd)
        if len(calls) == 2:
            raise OSError("directory fsync failed")
        real_fsync(fd)

    monkeypatch.setattr(state.os, "fsync", fail_directory)
    with pytest.raises(OSError):
        state.write_recovery_state(path, {"version": 1, "orders": {"oid": {}}})
    assert state.read_recovery_state(path, "orders") == {"oid": {}}


def test_symlink_is_rejected_without_touching_target(tmp_path):
    target = tmp_path / "target.json"
    target.write_text("original")
    link = tmp_path / "link.json"
    link.symlink_to(target)
    with pytest.raises(ValueError):
        state.write_recovery_state(link, {"version": 1, "orders": {}})
    assert target.read_text() == "original"
