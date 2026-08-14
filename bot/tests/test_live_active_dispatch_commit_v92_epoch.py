from __future__ import annotations

import types

from bot import live_active_dispatch_commit_v92_patch as repair


class _LiveSM:
    def get_current_state(self):
        return "LIVE_ACTIVE"


class _Snapshot:
    def __init__(
        self,
        *,
        runtime_authority_reason: str,
        activation_epoch: int,
        global_epoch: int,
        capital_stale: bool = False,
    ):
        self.last_committed_snapshot_version = 0
        self.execution_permitted = False
        self.runtime_authority_state = "DEGRADED"
        self.runtime_authority_reason = runtime_authority_reason
        self.activation_epoch = activation_epoch
        self.global_epoch = global_epoch
        self.capital_stale = capital_stale
        self.kill_switch_active = False
        self.authority_ready = True
        self.nonce_ready = True
        self.dispatch_health_ready = True
        self.pending_readiness = []


class _Proof:
    def __init__(self, passed: bool, failed_gates=()):
        self.passed = bool(passed)
        self.failed_gates = list(failed_gates)
        self.first_blocking_gate = self.failed_gates[0] if self.failed_gates else "none"
        self.gate_results = {name: False for name in self.failed_gates}


def _enable_live_mode(monkeypatch):
    monkeypatch.setenv("LIVE_CAPITAL_VERIFIED", "1")
    monkeypatch.delenv("DRY_RUN_MODE", raising=False)
    monkeypatch.delenv("PAPER_MODE", raising=False)


def _patch_coordinator_module(monkeypatch, coordinator):
    fake_module = types.SimpleNamespace(get_startup_coordinator=lambda: coordinator)
    real_import = repair.importlib.import_module

    def fake_import(name: str):
        if name == "bot.startup_coordinator":
            return fake_module
        return real_import(name)

    monkeypatch.setattr(repair.importlib, "import_module", fake_import)


def test_epoch_only_stale_live_state_reanchors_then_commits(monkeypatch):
    _enable_live_mode(monkeypatch)
    before = _Snapshot(
        runtime_authority_reason="global_epoch_stale",
        activation_epoch=4,
        global_epoch=5,
    )
    refreshed = types.SimpleNamespace(
        last_committed_snapshot_version=0,
        execution_permitted=False,
        runtime_authority_state="AUTHORIZED",
        runtime_authority_reason="authority_converged",
        activation_epoch=5,
        global_epoch=5,
        capital_stale=False,
        kill_switch_active=False,
        authority_ready=True,
        nonce_ready=True,
        dispatch_health_ready=True,
        pending_readiness=[],
    )
    after = types.SimpleNamespace(
        last_committed_snapshot_version=29,
        execution_permitted=True,
        runtime_authority_state="EXECUTING",
        runtime_authority_reason="dispatch_committed",
        activation_epoch=5,
        global_epoch=5,
        capital_stale=False,
        kill_switch_active=False,
        authority_ready=True,
        nonce_ready=True,
        dispatch_health_ready=True,
        pending_readiness=[],
    )

    class Coordinator:
        def __init__(self):
            self.phase = 0
            self.reanchor_calls = 0
            self.finalize_calls = 0

        def build_snapshot(self, *, trading_state, activation_intent):
            assert trading_state == "LIVE_ACTIVE"
            assert activation_intent is True
            return (before, refreshed, after)[self.phase]

        def evaluate_system_readiness_proof(self, snapshot):
            if snapshot is before:
                return _Proof(False, ("epoch.current", "runtime_authority.authorized"))
            return _Proof(True)

        def record_activation_requested(self, *, requested, source):
            assert requested is True
            assert "epoch_reanchor" in source
            self.reanchor_calls += 1
            self.phase = 1
            return 1

        def finalize_activation_commit(self, snapshot):
            assert snapshot is refreshed
            self.finalize_calls += 1
            self.phase = 2
            return 2

    coordinator = Coordinator()
    _patch_coordinator_module(monkeypatch, coordinator)
    ok, reason, details = repair._ensure_coordinator_dispatch_commit(
        _LiveSM(), source="test_epoch"
    )

    assert ok is True
    assert reason == "dispatch_commit_repaired"
    assert coordinator.reanchor_calls == 1
    assert coordinator.finalize_calls == 1
    assert details["epoch_reanchor"]["reanchored"] is True
    assert details["after"]["commit_version"] == 29


def test_epoch_reanchor_refuses_non_epoch_blocker(monkeypatch):
    _enable_live_mode(monkeypatch)
    before = _Snapshot(
        runtime_authority_reason="global_epoch_stale",
        activation_epoch=8,
        global_epoch=9,
        capital_stale=True,
    )

    class Coordinator:
        def __init__(self):
            self.reanchor_calls = 0

        def build_snapshot(self, *, trading_state, activation_intent):
            return before

        def evaluate_system_readiness_proof(self, _snapshot):
            return _Proof(
                False,
                ("capital.not_stale", "epoch.current", "runtime_authority.authorized"),
            )

        def record_activation_requested(self, **_kwargs):
            self.reanchor_calls += 1
            raise AssertionError("must not reanchor through a capital blocker")

        def finalize_activation_commit(self, _snapshot):
            raise RuntimeError(
                "LIVE commit blocked: system readiness proof failed at capital.not_stale"
            )

    coordinator = Coordinator()
    _patch_coordinator_module(monkeypatch, coordinator)
    ok, reason, details = repair._ensure_coordinator_dispatch_commit(
        _LiveSM(), source="test_non_epoch_blocker"
    )

    assert ok is False
    assert reason == "dispatch_commit_deferred:RuntimeError"
    assert coordinator.reanchor_calls == 0
    assert details["epoch_reanchor"]["reason"] == "non_epoch_blockers_present"
    assert details["epoch_reanchor"]["non_epoch_blockers"] == ["capital.not_stale"]


def test_epoch_reanchor_requires_global_epoch_stale_reason(monkeypatch):
    _enable_live_mode(monkeypatch)
    before = _Snapshot(
        runtime_authority_reason="authority_regressed",
        activation_epoch=3,
        global_epoch=4,
    )

    class Coordinator:
        def __init__(self):
            self.reanchor_calls = 0

        def build_snapshot(self, *, trading_state, activation_intent):
            return before

        def evaluate_system_readiness_proof(self, _snapshot):
            return _Proof(False, ("epoch.current", "runtime_authority.authorized"))

        def record_activation_requested(self, **_kwargs):
            self.reanchor_calls += 1
            raise AssertionError("must not reanchor unrelated authority regression")

        def finalize_activation_commit(self, _snapshot):
            raise RuntimeError(
                "LIVE commit blocked: system readiness proof failed at epoch.current"
            )

    coordinator = Coordinator()
    _patch_coordinator_module(monkeypatch, coordinator)
    ok, _reason, details = repair._ensure_coordinator_dispatch_commit(
        _LiveSM(), source="test_wrong_reason"
    )

    assert ok is False
    assert coordinator.reanchor_calls == 0
    assert details["epoch_reanchor"]["reason"] == "epoch_failure_not_global_epoch_stale"
