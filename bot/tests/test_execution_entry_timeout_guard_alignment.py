from __future__ import annotations

from bot import execution_entry_timeout_guard_patch as patch


def test_entry_timeout_defaults_above_ack_timeout(monkeypatch):
    monkeypatch.delenv("NIJA_EXECUTION_ENTRY_TIMEOUT_SECONDS", raising=False)
    monkeypatch.setenv("NIJA_ACK_TIMEOUT_S", "30")

    assert patch._timeout_s() >= 40.0


def test_entry_timeout_explicit_env_is_respected(monkeypatch):
    monkeypatch.setenv("NIJA_EXECUTION_ENTRY_TIMEOUT_SECONDS", "45")
    monkeypatch.setenv("NIJA_ACK_TIMEOUT_S", "30")

    assert patch._timeout_s() == 45.0


def test_entry_timeout_tracks_larger_ack_timeout(monkeypatch):
    monkeypatch.delenv("NIJA_EXECUTION_ENTRY_TIMEOUT_SECONDS", raising=False)
    monkeypatch.setenv("NIJA_ACK_TIMEOUT_S", "55")

    assert patch._timeout_s() >= 65.0
