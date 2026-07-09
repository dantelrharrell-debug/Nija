from __future__ import annotations

from types import SimpleNamespace

from bot import startup_coordinator_live_capital_state_repair_patch as patch


class FakeCoordinator:
    def __init__(self):
        self.capital_state = "BOOT_IDLE"
        self.capital_balance = None
        self.capital_stale = True
        self.activation_requested = False
        self.committed = False

    def record_capital_state(self, *, state, hydrated, balance, stale):
        self.capital_state = state
        self.capital_hydrated = hydrated
        self.capital_balance = balance
        self.capital_stale = stale
        return 1

    def record_activation_requested(self, requested=True, source=""):
        self.activation_requested = requested
        self.activation_source = source
        return 2

    def build_snapshot(self, trading_state="LIVE_ACTIVE", activation_intent=True):
        lifecycle = "LIVE" if self.capital_state == "RUNNING" else "BOOT"
        return SimpleNamespace(
            capital_state=self.capital_state,
            capital_balance=self.capital_balance,
            last_committed_snapshot_version=0,
            snapshot_version=3,
            runtime_authority_state="EXECUTING" if lifecycle == "LIVE" else "STANDBY",
            lifecycle_phase=lifecycle,
        )

    def evaluate_system_readiness_proof(self, snapshot):
        return SimpleNamespace(passed=True, first_blocking_gate="none", failed_gates=[])

    def finalize_activation_commit(self, snapshot):
        self.committed = True
        return 4


def _ready_probe():
    return {
        "hydrated": True,
        "first_snap": True,
        "valid_brokers": 3,
        "real": 581.22,
        "usable": 569.60,
        "fresh": True,
        "source": "capital_authority",
    }


def test_repair_relatches_boot_idle_capital_to_running(monkeypatch):
    coordinator = FakeCoordinator()
    monkeypatch.setenv("LIVE_CAPITAL_VERIFIED", "true")
    monkeypatch.setenv("DRY_RUN_MODE", "false")
    monkeypatch.setenv("PAPER_MODE", "false")
    monkeypatch.setenv("NIJA_RUNTIME_TRADING_STATE", "LIVE_ACTIVE")
    monkeypatch.setenv("NIJA_WRITER_FENCING_TOKEN", "token")
    monkeypatch.setenv("NIJA_WRITER_LEASE_GENERATION", "2278")
    monkeypatch.setattr(patch, "_kill_switch_clear", lambda: (True, "kill_switch_clear"))
    monkeypatch.setattr(patch, "_capital_probe", _ready_probe)

    assert patch._repair_coordinator_capital(coordinator, "test") is True
    assert coordinator.capital_state == "RUNNING"
    assert coordinator.capital_balance == 581.22
    assert coordinator.capital_stale is False
    assert coordinator.activation_requested is True
    assert coordinator.committed is True


def test_repair_refuses_without_live_state(monkeypatch):
    coordinator = FakeCoordinator()
    monkeypatch.setenv("LIVE_CAPITAL_VERIFIED", "true")
    monkeypatch.setenv("DRY_RUN_MODE", "false")
    monkeypatch.setenv("PAPER_MODE", "false")
    monkeypatch.setenv("NIJA_RUNTIME_TRADING_STATE", "OFF")
    monkeypatch.setenv("NIJA_WRITER_FENCING_TOKEN", "token")
    monkeypatch.setenv("NIJA_WRITER_LEASE_GENERATION", "2278")
    monkeypatch.setattr(patch, "_kill_switch_clear", lambda: (True, "kill_switch_clear"))
    monkeypatch.setattr(patch, "_capital_probe", _ready_probe)

    assert patch._repair_coordinator_capital(coordinator, "test") is False
    assert coordinator.capital_state == "BOOT_IDLE"


def test_build_snapshot_wrapper_repairs_boot_lifecycle(monkeypatch):
    monkeypatch.setenv("LIVE_CAPITAL_VERIFIED", "true")
    monkeypatch.setenv("DRY_RUN_MODE", "false")
    monkeypatch.setenv("PAPER_MODE", "false")
    monkeypatch.setenv("NIJA_RUNTIME_TRADING_STATE", "LIVE_ACTIVE")
    monkeypatch.setenv("NIJA_WRITER_FENCING_TOKEN", "token")
    monkeypatch.setenv("NIJA_WRITER_LEASE_GENERATION", "2278")
    monkeypatch.setattr(patch, "_kill_switch_clear", lambda: (True, "kill_switch_clear"))
    monkeypatch.setattr(patch, "_capital_probe", _ready_probe)

    module = SimpleNamespace(StartupCoordinator=FakeCoordinator, __name__="bot.startup_coordinator")
    assert patch._patch_startup_coordinator_module(module) is True
    coordinator = module.StartupCoordinator()

    snap = coordinator.build_snapshot(trading_state="LIVE_ACTIVE", activation_intent=True)

    assert snap.capital_state == "RUNNING"
    assert snap.lifecycle_phase == "LIVE"
