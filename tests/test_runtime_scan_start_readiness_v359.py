from __future__ import annotations

from types import SimpleNamespace

from bot import runtime_scan_start_readiness_v359_patch as v359


class _Stop:
    def is_set(self):
        return False


class _CancelAfterOneWait:
    def __init__(self):
        self.waits = 0

    def is_set(self):
        return False

    def wait(self, timeout):
        self.waits += 1
        return True


def _fake_authority():
    return SimpleNamespace(
        acquired=True,
        _scan_started_at=0.0,
        _scan_complete_at=0.0,
        _scan_deadline_armed_at=1.0,
        _scan_deadline_arm_source="bot_main_step3",
        _scan_deadline_exceeded=True,
        _scan_watchdog_cancel=_CancelAfterOneWait(),
        _stop=_Stop(),
        _instance_id="test-instance",
    )


def test_v359_does_not_classify_engine_wait_as_scan_deadline(monkeypatch):
    authority = _fake_authority()
    monkeypatch.setattr(v359, "_engine_start_signal_ready", lambda: False)

    v359._readiness_aware_scan_started_watchdog_loop(authority, 30.0)

    assert authority._scan_deadline_exceeded is False
    assert authority._scan_watchdog_cancel.waits == 1


def test_v359_installs_on_canonical_writer_authority():
    assert v359.install_import_hook() is True
    from bot.entrypoint_writer_authority import EntrypointWriterAuthority

    watchdog = EntrypointWriterAuthority._scan_started_watchdog_loop
    assert getattr(watchdog, "_nija_v359", False) is True
