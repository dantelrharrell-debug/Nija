from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace

from bot import execution_nonce_authority_snapshot_repair_patch as patch


@dataclass
class FakeDecision:
    allowed: bool
    reason: str
    nonce_ready: bool = False
    first_failed_gate: str = "nonce.authority"


class FakeCoordinator:
    def __init__(self):
        self.nonce_ready = False
        self.recorded_nonce = False
        self.activation_requested = False
        self.committed = False

    def build_snapshot(self, trading_state="LIVE_ACTIVE", activation_intent=True):
        return SimpleNamespace(
            nonce_ready=self.nonce_ready,
            snapshot_version=7,
            runtime_authority_state="EXECUTING",
            lifecycle_phase="LIVE",
        )

    def record_nonce_status(self, ready: bool, detail: str = ""):
        self.recorded_nonce = bool(ready)
        self.nonce_ready = bool(ready)
        self.nonce_detail = detail
        return 8

    def record_activation_requested(self, requested: bool = True, source: str = ""):
        self.activation_requested = bool(requested)
        self.activation_source = source
        return 9

    def evaluate_system_readiness_proof(self, snapshot):
        return SimpleNamespace(passed=True, first_blocking_gate="none", failed_gates=[])

    def finalize_activation_commit(self, snapshot):
        self.committed = True
        return 10


def test_startup_nonce_snapshot_block_is_repaired_when_runtime_nonce_is_ready(monkeypatch):
    coordinator = FakeCoordinator()
    module = SimpleNamespace(__name__="bot.execution_authority_context")
    module.assert_distributed_writer_authority = lambda: None
    module._runtime_nonce_authority_status = lambda: (True, "")

    calls = {"count": 0}

    def can_execute():
        calls["count"] += 1
        if not coordinator.nonce_ready:
            return FakeDecision(False, "nonce.authority: startup_snapshot_not_ready")
        return FakeDecision(True, "allowed", nonce_ready=True, first_failed_gate="")

    module.can_execute = can_execute
    monkeypatch.setenv("LIVE_CAPITAL_VERIFIED", "true")
    monkeypatch.setenv("DRY_RUN_MODE", "false")
    monkeypatch.setenv("PAPER_MODE", "false")
    monkeypatch.setenv("NIJA_RUNTIME_TRADING_STATE", "LIVE_ACTIVE")
    monkeypatch.setattr(patch, "_repair_startup_nonce_snapshot", lambda mod, source: setattr(coordinator, "nonce_ready", True) or True)

    assert patch._patch_module(module) is True

    decision = module.can_execute()

    assert decision.allowed is True
    assert coordinator.nonce_ready is True
    assert calls["count"] == 2


def test_repair_refuses_when_runtime_nonce_is_not_ready(monkeypatch):
    module = SimpleNamespace(__name__="bot.execution_authority_context")
    module.assert_distributed_writer_authority = lambda: None
    module._runtime_nonce_authority_status = lambda: (False, "nonce_sync:blocked")
    monkeypatch.setenv("LIVE_CAPITAL_VERIFIED", "true")
    monkeypatch.setenv("DRY_RUN_MODE", "false")
    monkeypatch.setenv("PAPER_MODE", "false")
    monkeypatch.setenv("NIJA_RUNTIME_TRADING_STATE", "LIVE_ACTIVE")

    ok, detail = patch._live_safety_ready(module)

    assert ok is False
    assert "runtime_nonce_not_ready" in detail


def test_repair_records_nonce_status_and_commit(monkeypatch):
    coordinator = FakeCoordinator()
    module = SimpleNamespace(__name__="bot.execution_authority_context")
    module.assert_distributed_writer_authority = lambda: None
    module._runtime_nonce_authority_status = lambda: (True, "")
    monkeypatch.setenv("LIVE_CAPITAL_VERIFIED", "true")
    monkeypatch.setenv("DRY_RUN_MODE", "false")
    monkeypatch.setenv("PAPER_MODE", "false")
    monkeypatch.setenv("NIJA_RUNTIME_TRADING_STATE", "LIVE_ACTIVE")

    monkeypatch.setattr(patch, "_live_safety_ready", lambda mod: (True, "ok"))

    import bot.startup_coordinator as sc

    monkeypatch.setattr(sc, "get_startup_coordinator", lambda: coordinator)

    assert patch._repair_startup_nonce_snapshot(module, "test") is True
    assert coordinator.recorded_nonce is True
    assert coordinator.activation_requested is True
    assert coordinator.committed is True
