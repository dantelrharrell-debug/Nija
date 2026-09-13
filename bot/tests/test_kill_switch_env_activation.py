from __future__ import annotations

import json

from bot.kill_switch import KillSwitch


def test_environment_stop_activates_and_materializes_files(monkeypatch, tmp_path):
    monkeypatch.setenv("NIJA_KILL_SWITCH", "true")
    monkeypatch.setenv("NIJA_KILL_SWITCH_REASON", "verification hold")

    switch = KillSwitch(base_path=str(tmp_path))

    assert switch.is_active() is True
    assert (tmp_path / "EMERGENCY_STOP").exists()
    state = json.loads((tmp_path / ".nija_kill_switch_state.json").read_text())
    assert state["is_active"] is True
    assert state["history"][-1]["source"] == "ENV"
    assert state["history"][-1]["reason"] == "verification hold"


def test_false_environment_stop_does_not_activate(monkeypatch, tmp_path):
    monkeypatch.setenv("NIJA_KILL_SWITCH", "false")

    switch = KillSwitch(base_path=str(tmp_path))

    assert switch.is_active() is False
    assert not (tmp_path / "EMERGENCY_STOP").exists()


def test_existing_file_remains_authoritative_with_environment_stop(monkeypatch, tmp_path):
    (tmp_path / "EMERGENCY_STOP").write_text("manual hold")
    monkeypatch.setenv("NIJA_KILL_SWITCH", "1")

    switch = KillSwitch(base_path=str(tmp_path))

    assert switch.is_active() is True
    status = switch.get_status()
    assert len(status["recent_history"]) == 1
    assert status["recent_history"][0]["source"] == "FILE_SYSTEM"
