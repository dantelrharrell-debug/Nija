from __future__ import annotations

from types import ModuleType

import bot.trading_state_dispatch_latch_repair_patch as patch


def test_unknown_state_uses_canonical_env(monkeypatch):
    monkeypatch.setenv("NIJA_RUNTIME_TRADING_STATE", "LIVE_ACTIVE")
    assert patch._canonical_trading_state("UNKNOWN") == "LIVE_ACTIVE"


def test_explicit_safety_state_is_never_upgraded(monkeypatch):
    monkeypatch.setenv("NIJA_RUNTIME_TRADING_STATE", "LIVE_ACTIVE")
    assert patch._canonical_trading_state("OFF") == "OFF"
    assert patch._canonical_trading_state("EMERGENCY_STOP") == "EMERGENCY_STOP"


def test_capital_ready_requires_complete_authority(monkeypatch):
    monkeypatch.setattr(
        patch,
        "_capital_probe",
        lambda: {
            "hydrated": True,
            "first_snap": True,
            "valid_brokers": 2,
            "registered_brokers": 2,
            "expected_brokers": 3,
            "brokers_complete": False,
            "real": 95.12,
            "usable": 93.22,
            "fresh": True,
            "source": "capital_authority",
        },
    )
    ready, detail = patch._capital_ready()
    assert ready is False
    assert "complete=False" in detail
    assert "registered_brokers=2 expected_brokers=3" in detail


def test_core_normalizer_does_not_inflate_broker_completeness(monkeypatch):
    module = ModuleType("fake_core")

    def original():
        return {
            "ca_total_capital": 95.12,
            "ca_valid_brokers": 3,
            "aggregation_normalized": True,
        }

    module._capture_cycle_capital_state = original
    monkeypatch.setattr(
        patch,
        "_capital_probe",
        lambda: {
            "hydrated": True,
            "valid_brokers": 2,
            "registered_brokers": 2,
            "expected_brokers": 3,
            "brokers_complete": False,
            "real": 95.12,
            "usable": 93.22,
            "fresh": True,
            "source": "capital_authority",
        },
    )

    assert patch._install_core_loop_patch_on_module(module) is True
    result = dict(module._capture_cycle_capital_state())
    assert result["ca_valid_brokers"] == 2
    assert result["aggregation_normalized"] is False


def test_partial_snapshot_cannot_downgrade_fresh_complete_state():
    module = ModuleType("fake_capital_authority")

    class CapitalAuthority:
        def __init__(self):
            self.expected_brokers = 3
            self._broker_balances = {"kraken": 235.0, "coinbase": 95.0, "okx": 0.1}
            self.original_calls = 0

        def is_fresh(self):
            return True

        def publish_snapshot(self, snapshot, writer_id):
            self.original_calls += 1
            self._broker_balances = dict(snapshot.broker_balances)
            return True

    module.CapitalAuthority = CapitalAuthority
    assert patch._install_capital_authority_patch_on_module(module) is True
    authority = CapitalAuthority()

    class Snapshot:
        broker_balances = {"coinbase": 95.0, "okx": 0.1}

    assert authority.publish_snapshot(Snapshot(), "mabm_capital_refresh_coordinator") is False
    assert authority.original_calls == 0
    assert set(authority._broker_balances) == {"kraken", "coinbase", "okx"}


def test_complete_snapshot_still_flows_to_original():
    module = ModuleType("fake_capital_authority_complete")

    class CapitalAuthority:
        def __init__(self):
            self.expected_brokers = 3
            self._broker_balances = {"kraken": 235.0, "coinbase": 95.0, "okx": 0.1}
            self.original_calls = 0

        def is_fresh(self):
            return True

        def publish_snapshot(self, snapshot, writer_id):
            self.original_calls += 1
            self._broker_balances = dict(snapshot.broker_balances)
            return True

    module.CapitalAuthority = CapitalAuthority
    assert patch._install_capital_authority_patch_on_module(module) is True
    authority = CapitalAuthority()

    class Snapshot:
        broker_balances = {"kraken": 236.0, "coinbase": 95.0, "okx": 0.1}

    assert authority.publish_snapshot(Snapshot(), "mabm_capital_refresh_coordinator") is True
    assert authority.original_calls == 1
    assert authority._broker_balances["kraken"] == 236.0


def test_startup_coordinator_wrapper_canonicalizes_only_unknown(monkeypatch):
    module = ModuleType("fake_startup_coordinator")

    class StartupCoordinator:
        def build_snapshot(self, *, trading_state, activation_intent):
            return trading_state, activation_intent

    module.StartupCoordinator = StartupCoordinator
    monkeypatch.setenv("NIJA_RUNTIME_TRADING_STATE", "LIVE_ACTIVE")
    assert patch._install_startup_coordinator_patch_on_module(module) is True
    coordinator = StartupCoordinator()
    assert coordinator.build_snapshot(trading_state="UNKNOWN", activation_intent=True) == (
        "LIVE_ACTIVE",
        True,
    )
    assert coordinator.build_snapshot(trading_state="OFF", activation_intent=True) == (
        "OFF",
        True,
    )
