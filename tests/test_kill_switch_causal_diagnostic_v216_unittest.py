from __future__ import annotations

import importlib
import os


def test_v216_dependencies_require_guarded_recovery_chain(monkeypatch):
    module = importlib.import_module("bot.kill_switch_causal_diagnostic_v216_periodic_patch")
    for name in (
        "NIJA_KILL_SWITCH_COORDINATOR_SYNC_READY",
        "NIJA_KILL_SWITCH_PERSISTENCE_PROVENANCE_V143_READY",
        "NIJA_KILL_SWITCH_TRANSACTIONAL_RECOVERY_V193_READY",
    ):
        monkeypatch.delenv(name, raising=False)
    assert module._dependencies_ready() is False

    monkeypatch.setenv("NIJA_KILL_SWITCH_COORDINATOR_SYNC_READY", "1")
    monkeypatch.setenv("NIJA_KILL_SWITCH_PERSISTENCE_PROVENANCE_V143_READY", "1")
    assert module._dependencies_ready() is False

    monkeypatch.setenv("NIJA_KILL_SWITCH_TRANSACTIONAL_RECOVERY_V193_READY", "1")
    assert module._dependencies_ready() is True


def test_v216_interval_is_bounded(monkeypatch):
    module = importlib.import_module("bot.kill_switch_causal_diagnostic_v216_periodic_patch")

    monkeypatch.setenv("NIJA_KILL_SWITCH_CAUSAL_DIAGNOSTIC_INTERVAL_S", "1")
    assert module._interval_s() == 15.0

    monkeypatch.setenv("NIJA_KILL_SWITCH_CAUSAL_DIAGNOSTIC_INTERVAL_S", "9999")
    assert module._interval_s() == 300.0

    monkeypatch.setenv("NIJA_KILL_SWITCH_CAUSAL_DIAGNOSTIC_INTERVAL_S", "bad")
    assert module._interval_s() == 30.0
