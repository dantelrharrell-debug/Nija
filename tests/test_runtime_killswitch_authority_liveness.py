from __future__ import annotations

import inspect
from types import SimpleNamespace

import bot.runtime_killswitch_authority_liveness_patch as mod


_HEARTBEAT_REASON = (
    "AUTHORITY_HEARTBEAT_EXPIRED: core_thread_dead - "
    "NIJA_CORE_THREAD_ALIVE is not set"
)


def _status(source: str, reason: str):
    return {
        "is_active": True,
        "recent_history": [
            {"source": source, "reason": reason},
            {"source": "FILE_SYSTEM", "reason": "Kill switch file detected"},
        ],
    }


def test_heartbeat_signature_is_narrow():
    assert mod._heartbeat_failure_reason(_HEARTBEAT_REASON)
    assert not mod._heartbeat_failure_reason("AUTHORITY_HEARTBEAT_EXPIRED: redis timeout")
    assert not mod._heartbeat_failure_reason("daily loss limit exceeded")


def test_legacy_manual_heartbeat_persistence_is_eligible():
    ok, detail = mod._eligible_persisted_heartbeat_stop(_status("MANUAL", _HEARTBEAT_REASON))
    assert ok is True
    assert detail == "legacy_manual_heartbeat_provenance"


def test_explicit_operator_manual_stop_is_preserved():
    reason = "operator manual stop after AUTHORITY_HEARTBEAT_EXPIRED: core_thread_dead"
    ok, detail = mod._eligible_persisted_heartbeat_stop(_status("MANUAL", reason))
    assert ok is False
    assert detail == "causal_source_forbidden"


def test_unrelated_automatic_risk_stop_is_preserved():
    ok, detail = mod._eligible_persisted_heartbeat_stop(
        _status("AUTOMATIC", "daily loss limit exceeded")
    )
    assert ok is False
    assert detail == "causal_reason_not_retired_heartbeat"


def test_unknown_source_is_preserved_even_with_heartbeat_words():
    ok, detail = mod._eligible_persisted_heartbeat_stop(
        _status("FAILURE_MODE_MANAGER", _HEARTBEAT_REASON)
    )
    assert ok is False
    assert detail == "causal_source_forbidden"


def test_direct_new_heartbeat_stop_is_not_restart_eligible():
    status = {
        "is_active": True,
        "recent_history": [{"source": "AUTOMATIC", "reason": _HEARTBEAT_REASON}],
    }
    ok, detail = mod._eligible_persisted_heartbeat_stop(status)
    assert ok is False
    assert detail == "latest_not_restart_persistence"


def test_source_normalization_requires_owned_heartbeat(monkeypatch):
    monkeypatch.delenv(mod._OWNED_STOP_ENV, raising=False)
    monkeypatch.delenv(mod._OWNED_REASON_ENV, raising=False)
    assert mod._normalized_activation_source("generic system stop", "MANUAL") == "MANUAL"

    monkeypatch.setenv(mod._OWNED_STOP_ENV, "1")
    monkeypatch.setenv(
        mod._OWNED_REASON_ENV,
        "AUTHORITY HEARTBEAT EXPIRED: 3 failures; core_thread_dead",
    )
    assert mod._normalized_activation_source("state machine emergency stop", "MANUAL") == "AUTOMATIC"
    assert mod._normalized_activation_source("operator manual stop", "MANUAL") == "MANUAL"
    assert mod._normalized_activation_source("state machine emergency stop", "UI") == "UI"


def test_recovery_clears_only_verified_latch_and_returns_to_off(monkeypatch):
    class FakeKillSwitch:
        def __init__(self):
            self.active = True
            self.deactivations = []

        def get_status(self):
            return _status("MANUAL", _HEARTBEAT_REASON)

        def deactivate(self, reason):
            self.deactivations.append(reason)
            self.active = False

        def is_active(self):
            return self.active

    class FakeSeak:
        def __init__(self):
            self.resumed = []

        def resume(self, caller="operator"):
            self.resumed.append(caller)

    kill = FakeKillSwitch()
    seak = FakeSeak()
    kill_module = SimpleNamespace(get_kill_switch=lambda: kill)
    original_import = mod.importlib.import_module

    def fake_import(name):
        if name == "bot.kill_switch":
            return kill_module
        return original_import(name)

    monkeypatch.setattr(mod.importlib, "import_module", fake_import)
    monkeypatch.setattr(mod, "_runtime_recovery_proof", lambda: (True, "ok", seak, True))
    monkeypatch.setattr(mod, "_fsm_state_value", lambda: "OFF")

    assert mod._attempt_persisted_heartbeat_stop_recovery() is True
    assert len(kill.deactivations) == 1
    assert seak.resumed == ["runtime_killswitch_authority_liveness_v140"]


def test_recovery_does_not_resume_seak_until_fsm_is_off(monkeypatch):
    class FakeKillSwitch:
        def __init__(self):
            self.active = True

        def get_status(self):
            return _status("AUTOMATIC", _HEARTBEAT_REASON)

        def deactivate(self, _reason):
            self.active = False

        def is_active(self):
            return self.active

    class FakeSeak:
        def __init__(self):
            self.resumed = False

        def resume(self, caller="operator"):
            self.resumed = True

    kill = FakeKillSwitch()
    seak = FakeSeak()
    original_import = mod.importlib.import_module

    def fake_import(name):
        if name == "bot.kill_switch":
            return SimpleNamespace(get_kill_switch=lambda: kill)
        return original_import(name)

    monkeypatch.setattr(mod.importlib, "import_module", fake_import)
    monkeypatch.setattr(mod, "_runtime_recovery_proof", lambda: (True, "ok", seak, True))
    monkeypatch.setattr(mod, "_fsm_state_value", lambda: "EMERGENCY_STOP")

    assert mod._attempt_persisted_heartbeat_stop_recovery() is False
    assert seak.resumed is False


def test_recovery_keeps_stop_when_runtime_proof_is_not_healthy(monkeypatch):
    class FakeKillSwitch:
        def __init__(self):
            self.deactivated = False

        def get_status(self):
            return _status("AUTOMATIC", _HEARTBEAT_REASON)

        def deactivate(self, _reason):
            self.deactivated = True

        def is_active(self):
            return True

    kill = FakeKillSwitch()
    original_import = mod.importlib.import_module

    def fake_import(name):
        if name == "bot.kill_switch":
            return SimpleNamespace(get_kill_switch=lambda: kill)
        return original_import(name)

    monkeypatch.setattr(mod.importlib, "import_module", fake_import)
    monkeypatch.setattr(
        mod,
        "_runtime_recovery_proof",
        lambda: (False, "writer_epoch_not_current", None, False),
    )

    assert mod._attempt_persisted_heartbeat_stop_recovery() is False
    assert kill.deactivated is False


def test_canonical_writer_guard_remains_diagnostic_only(monkeypatch):
    calls = []

    def original_should_release(snapshot, elapsed_s, timeout_s):
        calls.append((snapshot, elapsed_s, timeout_s))
        return True

    guard = SimpleNamespace(_should_release=original_should_release)
    v58 = SimpleNamespace(
        _canonical_fast_path=lambda: True,
        _canonical_core_registered=lambda: True,
    )
    original_import = mod.importlib.import_module

    def fake_import(name):
        if name == "bot.stalled_writer_release_guard_v22":
            return guard
        if name == "bot.final_production_activation_repair_v58_patch":
            return v58
        return original_import(name)

    monkeypatch.setattr(mod.importlib, "import_module", fake_import)
    assert mod._patch_stalled_writer_release_guard() is True
    snap = SimpleNamespace(generation="4225", state="OFF")
    assert guard._should_release(snap, 2530.5, 360.0) is False
    assert calls == []


def test_patch_has_no_live_or_execution_authority_grant():
    source = inspect.getsource(mod)
    assert 'NIJA_RUNTIME_EXECUTION_AUTHORITY"] = "1"' not in source
    assert "TradingState.LIVE_ACTIVE" not in source
    assert "force_live=false" in source
    assert "writer_release=false" in source
