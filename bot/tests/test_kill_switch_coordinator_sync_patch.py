from __future__ import annotations

import os
from types import SimpleNamespace

import bot.startup_coordinator as startup_coordinator
from bot.kill_switch_coordinator_sync_patch import (
    _patch_kill_switch_class,
    _publish_coordinator_truth,
)


def _fresh_coordinator(monkeypatch):
    coordinator = startup_coordinator.StartupCoordinator()
    monkeypatch.setattr(startup_coordinator, "_startup_coordinator", coordinator)
    return coordinator


def test_publish_tracks_kill_switch_truth_without_forcing_lifecycle(monkeypatch):
    coordinator = _fresh_coordinator(monkeypatch)
    coordinator.record_threads_supervised(1, bootstrap_state="RUNNING_SUPERVISED")
    before_state = coordinator.get_state()
    before_epoch = coordinator._runtime.global_epoch

    assert _publish_coordinator_truth(True, "test_activate") is True
    assert coordinator._runtime.kill_switch_active is True
    assert coordinator._runtime.global_epoch == before_epoch + 1
    assert coordinator.get_state() == before_state

    assert _publish_coordinator_truth(False, "test_deactivate") is True
    assert coordinator._runtime.kill_switch_active is False
    assert coordinator._runtime.global_epoch == before_epoch + 2
    assert coordinator.get_state() == before_state


def test_publish_revokes_prior_activation_commit(monkeypatch):
    coordinator = _fresh_coordinator(monkeypatch)
    coordinator._runtime.last_committed_snapshot_version = 123
    coordinator._runtime._activation_committed = True

    assert _publish_coordinator_truth(True, "test") is True
    assert coordinator._runtime.last_committed_snapshot_version == 0
    assert coordinator._runtime._activation_committed is False


def test_patch_syncs_activation_file_check_and_deactivation(monkeypatch, tmp_path):
    events = []
    import bot.kill_switch_coordinator_sync_patch as patch

    monkeypatch.setattr(
        patch,
        "_publish_coordinator_truth",
        lambda active, source: events.append((bool(active), source)) or True,
    )

    class FakeKillSwitch:
        def __init__(self):
            self._is_active = False
            self._kill_file = str(tmp_path / "EMERGENCY_STOP")

        def _activate_internal(self, reason, source):
            self._is_active = True

        def is_active(self):
            if os.path.exists(self._kill_file) and not self._is_active:
                self._activate_internal("Kill switch file detected", "FILE_SYSTEM")
            return self._is_active

        def deactivate(self, reason="Manual deactivation"):
            self._is_active = False
            if os.path.exists(self._kill_file):
                os.remove(self._kill_file)

    assert _patch_kill_switch_class(FakeKillSwitch) is True
    switch = FakeKillSwitch()

    switch._activate_internal("operator", "MANUAL")
    assert events[-1] == (True, "activate:MANUAL")

    switch.deactivate()
    assert events[-1] == (False, "deactivate")

    with open(switch._kill_file, "w", encoding="utf-8") as handle:
        handle.write("stop")
    assert switch.is_active() is True
    assert (True, "activate:FILE_SYSTEM") in events
    assert events[-1] == (True, "is_active")


def test_patch_is_idempotent(tmp_path):
    class FakeKillSwitch:
        def __init__(self):
            self._is_active = False
            self._kill_file = str(tmp_path / "EMERGENCY_STOP")

        def _activate_internal(self, reason, source):
            self._is_active = True

        def is_active(self):
            return self._is_active

        def deactivate(self, reason="Manual deactivation"):
            self._is_active = False

    assert _patch_kill_switch_class(FakeKillSwitch) is True
    first = FakeKillSwitch.is_active
    assert _patch_kill_switch_class(FakeKillSwitch) is True
    assert FakeKillSwitch.is_active is first
