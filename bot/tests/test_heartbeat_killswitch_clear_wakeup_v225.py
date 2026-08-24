from __future__ import annotations

import types

from bot import runtime_heartbeat_killswitch_clear_wakeup_v225_patch as v225


def _fake_v202(wait_result=False):
    module = types.ModuleType("bot.runtime_heartbeat_position_sync_wakeup_v202_patch")
    module.position_state = (True, True)
    module.wait_calls = []

    def _position_sync_ready():
        return module.position_state

    def _wait_for_retry_or_position_sync(sleep_s):
        module.wait_calls.append(sleep_s)
        return wait_result

    module._position_sync_ready = _position_sync_ready
    module._wait_for_retry_or_position_sync = _wait_for_retry_or_position_sync
    return module


def test_preserves_v202_when_kill_switch_not_active(monkeypatch):
    module = _fake_v202(wait_result=True)
    monkeypatch.setattr(v225, "_canonical_kill_switch_active", lambda: (True, False))
    assert v225._patch_v202(module)

    assert module._wait_for_retry_or_position_sync(0.01) is True
    assert module.wait_calls == [0.01]


def test_wakes_immediately_after_true_to_false_kill_switch_transition(monkeypatch):
    module = _fake_v202(wait_result=False)
    states = iter([(True, True), (True, False)])
    monkeypatch.setattr(v225, "_canonical_kill_switch_active", lambda: next(states))
    monkeypatch.setattr(v225.time, "sleep", lambda _seconds: None)
    ticks = iter([0.0, 0.0])
    monkeypatch.setattr(v225.time, "monotonic", lambda: next(ticks))
    assert v225._patch_v202(module)

    # False is intentional: v202 must not mislabel the wake as position-sync.
    assert module._wait_for_retry_or_position_sync(15.0) is False
    assert module.wait_calls == []


def test_position_sync_wakeup_is_preserved_while_kill_switch_active(monkeypatch):
    module = _fake_v202(wait_result=False)
    position_states = iter([(True, False), (True, True)])
    module._position_sync_ready = lambda: next(position_states)
    monkeypatch.setattr(v225, "_canonical_kill_switch_active", lambda: (True, True))
    monkeypatch.setattr(v225.time, "sleep", lambda _seconds: None)
    ticks = iter([0.0, 0.0])
    monkeypatch.setattr(v225.time, "monotonic", lambda: next(ticks))
    assert v225._patch_v202(module)

    assert module._wait_for_retry_or_position_sync(15.0) is True


def test_unknown_kill_switch_state_preserves_original_wait(monkeypatch):
    module = _fake_v202(wait_result=False)
    monkeypatch.setattr(v225, "_canonical_kill_switch_active", lambda: (False, False))
    assert v225._patch_v202(module)

    assert module._wait_for_retry_or_position_sync(0.01) is False
    assert module.wait_calls == [0.01]
