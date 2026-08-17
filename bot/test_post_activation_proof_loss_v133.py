from __future__ import annotations

import types

from bot import post_activation_proof_loss_v133_patch as v133


class _FakeTable:
    def __init__(self):
        self.state = {key: True for key in v133._CRITICAL_KEYS}

    def mark_ready(self, key):
        self.state[key] = True

    def revoke_ready(self, key, reason=""):
        self.state[key] = False

    def snapshot(self):
        return dict(self.state)


class _FakeState:
    def __init__(self, value):
        self.value = value


class _FakeSM:
    def __init__(self, value="LIVE_ACTIVE"):
        self.value = value
        self.transitions = []

    def get_current_state(self):
        return _FakeState(self.value)

    def transition_to(self, new_state, reason=""):
        self.transitions.append((getattr(new_state, "value", str(new_state)), reason))
        self.value = getattr(new_state, "value", str(new_state))
        return True


def test_revoke_false_readiness_revokes_current_false_proofs(monkeypatch):
    table = _FakeTable()
    real_import = v133.importlib.import_module

    def fake_import(name):
        if name == "bot.readiness_table":
            return table
        return real_import(name)

    monkeypatch.setattr(v133.importlib, "import_module", fake_import)
    proofs = {key: True for key in v133._CRITICAL_KEYS}
    proofs["broker_connected"] = False
    proofs["balance_hydrated"] = False
    proofs["capital_ready"] = False

    after, pending = v133._revoke_false_readiness(proofs)

    assert pending == ["broker_connected", "balance_hydrated", "capital_ready"]
    assert after["broker_connected"] is False
    assert after["balance_hydrated"] is False
    assert after["capital_ready"] is False
    assert after["authority_ready"] is True


def test_live_proof_loss_routes_through_canonical_off_transition(monkeypatch):
    sm = _FakeSM("LIVE_ACTIVE")
    trading_state = types.SimpleNamespace(OFF=_FakeState("OFF"))
    real_import = v133.importlib.import_module

    def fake_import(name):
        if name == "bot.trading_state_machine":
            return types.SimpleNamespace(TradingState=trading_state)
        return real_import(name)

    monkeypatch.setattr(v133.importlib, "import_module", fake_import)

    changed = v133._fail_closed_live_state(sm, ["capital_ready"])

    assert changed is True
    assert sm.value == "OFF"
    assert sm.transitions == [("OFF", "v133 current proof loss: capital_ready")]


def test_healthy_live_state_is_not_forced_off(monkeypatch):
    sm = _FakeSM("LIVE_ACTIVE")
    changed = v133._fail_closed_live_state(sm, [])
    assert changed is False
    assert sm.transitions == []


def test_non_live_state_is_not_retransitioned(monkeypatch):
    sm = _FakeSM("OFF")
    changed = v133._fail_closed_live_state(sm, ["broker_connected"])
    assert changed is False
    assert sm.transitions == []


def test_owner_markers_keep_v132_watchdog_from_downgrading_successor():
    assert getattr(v133._truth_sync_v133, "_nija_v61_truth_sync", False) is True
    assert getattr(v133._truth_sync_v133, "_nija_v132_truth_sync", False) is True
    assert getattr(v133._truth_sync_v133, "_nija_v133_truth_sync", False) is True


def test_source_contains_no_forced_live_or_safety_clear_bypass():
    import inspect

    source = inspect.getsource(v133)
    forbidden = [
        "force_activate_live(",
        "force_live_active",
        "clear_kill_switch",
        "deactivate_kill_switch",
        "resume_seak",
        "clear_seak",
    ]
    for token in forbidden:
        assert token not in source
