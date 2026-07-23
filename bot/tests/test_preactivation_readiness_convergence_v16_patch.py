from __future__ import annotations

import importlib
import sys
import threading
import time
from types import ModuleType, SimpleNamespace


def _module():
    return importlib.import_module("preactivation_readiness_convergence_v16_patch")


def test_marks_every_key_only_when_every_proof_passes(monkeypatch):
    patch = _module()
    marked: list[str] = []
    table = ModuleType("bot.readiness_table")
    table.pending = lambda: [key for key in patch._KEYS if key not in marked]
    table.mark_ready = lambda key: marked.append(key) if key not in marked else None
    monkeypatch.setitem(sys.modules, "bot.readiness_table", table)

    proofs = {key: True for key in patch._KEYS}
    ready, pending = patch._mark_proven_readiness(proofs)
    assert ready is True
    assert pending == []
    assert set(marked) == set(patch._KEYS)

    marked.clear()
    proofs["nonce_ready"] = False
    ready, pending = patch._mark_proven_readiness(proofs)
    assert ready is False
    assert pending == ["nonce_ready"]
    assert marked == []


def test_rearms_pending_timeout_without_force_transition(monkeypatch):
    patch = _module()
    monkeypatch.delenv("NIJA_ALLOW_PENDING_CONFIRMATION_FORCE_TIMEOUT", raising=False)

    class StateMachine:
        def __init__(self):
            self._lock = threading.RLock()
            self._pending_confirmation_since = 1.0

        def get_current_state(self):
            return SimpleNamespace(value="LIVE_PENDING_CONFIRMATION")

    sm = StateMachine()
    before = time.monotonic()
    patch._rearm_unsafe_timeout(sm)
    assert sm._pending_confirmation_since >= before


def test_activation_uses_normal_commit_path(monkeypatch):
    patch = _module()
    proofs = {key: True for key in patch._KEYS}
    monkeypatch.setattr(patch, "_collect_proofs", lambda: (proofs, {"proof": "ok"}))
    monkeypatch.setattr(patch, "_mark_proven_readiness", lambda value: (True, []))

    class StateMachine:
        def __init__(self):
            self._lock = threading.RLock()
            self._pending_confirmation_since = time.monotonic()
            self.state = "LIVE_PENDING_CONFIRMATION"

        def get_current_state(self):
            return SimpleNamespace(value=self.state)

    sm = StateMachine()
    calls: list[str] = []
    monitor = ModuleType("bot.activation_pending_commit_monitor_patch")
    monitor._state_machine = lambda: sm
    monitor._current_state_value = lambda value: value.state
    monitor._capital_ready_snapshot = lambda: (True, {"real_capital": 100.0})

    def commit_once(value, meta):
        calls.append("commit")
        value.state = "LIVE_ACTIVE"
        return True

    monitor._commit_once = commit_once
    monkeypatch.setitem(sys.modules, "bot.activation_pending_commit_monitor_patch", monitor)

    active, details = patch._attempt_activation()
    assert active is True
    assert calls == ["commit"]
    assert details["state_after"] == "LIVE_ACTIVE"
