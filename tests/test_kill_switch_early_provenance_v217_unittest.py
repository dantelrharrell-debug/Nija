from __future__ import annotations

import importlib


def test_existing_marker_is_not_rewritten_on_constructor(tmp_path):
    base = importlib.import_module("bot.kill_switch")
    v217 = importlib.import_module("bot.kill_switch_early_provenance_v217_patch")
    assert v217.install_import_hook() is True

    marker = tmp_path / "EMERGENCY_STOP"
    original = (
        "EMERGENCY STOP\n"
        "Reason: AUTHORITY_HEARTBEAT_EXPIRED core_thread_dead\n"
        "Activated: 2026-08-24T03:52:00+00:00\n"
    )
    marker.write_text(original, encoding="utf-8")

    ks = base.KillSwitch(base_path=str(tmp_path))

    assert ks.is_active() is True
    assert marker.read_text(encoding="utf-8") == original
    status = ks.get_status()
    latest = status["recent_history"][-1]
    assert latest["source"] == "FILE_SYSTEM"
    assert latest["restart_persistence"] is True
    assert latest["persisted_marker_reason"] == "AUTHORITY_HEARTBEAT_EXPIRED core_thread_dead"
    assert latest["marker_rewritten"] is False


def test_existing_marker_cannot_be_overwritten(tmp_path):
    base = importlib.import_module("bot.kill_switch")
    v217 = importlib.import_module("bot.kill_switch_early_provenance_v217_patch")
    assert v217.install_import_hook() is True

    marker = tmp_path / "EMERGENCY_STOP"
    original = "Reason: operator stop\nActivated: 2026-08-24T03:52:00+00:00\n"
    marker.write_text(original, encoding="utf-8")

    ks = base.KillSwitch(base_path=str(tmp_path))
    ks._create_kill_file("replacement reason")

    assert marker.read_text(encoding="utf-8") == original
