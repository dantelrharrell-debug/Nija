from __future__ import annotations

from types import SimpleNamespace

from bot import hard_controls_capital_authority_bridge_patch as patch


class FakeCSM:
    def __init__(self):
        self.original_calls = 0

    def is_live_capital_valid(self):
        self.original_calls += 1
        return False


class FakeCapitalAuthority:
    is_hydrated = True
    first_snap_accepted = True
    total_capital = 580.51
    usable_capital = 568.90
    risk_capital = 568.90
    valid_broker_count = 3
    registered_broker_count = 3

    def get_real_capital(self):
        return 580.51

    def get_usable_capital(self):
        return 568.90

    def is_fresh(self, ttl_s=240.0):
        return True


def test_capital_authority_snapshot_ready_when_live_ca_and_writer(monkeypatch):
    monkeypatch.setenv("LIVE_CAPITAL_VERIFIED", "true")
    monkeypatch.setenv("DRY_RUN_MODE", "false")
    monkeypatch.setenv("PAPER_MODE", "false")
    monkeypatch.setenv("NIJA_RUNTIME_TRADING_STATE", "LIVE_ACTIVE")
    monkeypatch.setenv("NIJA_RUNTIME_EXECUTION_AUTHORITY", "1")
    monkeypatch.setenv("NIJA_WRITER_FENCING_TOKEN", "1")
    monkeypatch.setenv("NIJA_WRITER_LEASE_GENERATION", "2259")

    import bot.capital_authority as ca_mod
    monkeypatch.setattr(ca_mod, "get_capital_authority", lambda: FakeCapitalAuthority())

    ready, reason, detail = patch._capital_authority_snapshot_ready()

    assert ready is True
    assert "ca_bridge_ready" in reason
    assert detail["real"] == 580.51
    assert detail["valid_brokers"] >= 3


def test_csm_patch_returns_true_when_original_false_but_ca_ready(monkeypatch):
    monkeypatch.setenv("LIVE_CAPITAL_VERIFIED", "true")
    monkeypatch.setenv("DRY_RUN_MODE", "false")
    monkeypatch.setenv("PAPER_MODE", "false")
    monkeypatch.setenv("NIJA_RUNTIME_TRADING_STATE", "LIVE_ACTIVE")
    monkeypatch.setenv("NIJA_RUNTIME_EXECUTION_AUTHORITY", "1")
    monkeypatch.setenv("NIJA_WRITER_FENCING_TOKEN", "1")
    monkeypatch.setenv("NIJA_WRITER_LEASE_GENERATION", "2259")

    import bot.capital_authority as ca_mod
    monkeypatch.setattr(ca_mod, "get_capital_authority", lambda: FakeCapitalAuthority())

    module = SimpleNamespace(CapitalCSMv2=FakeCSM, is_live_capital_valid=lambda: False, __name__="bot.capital_csm_v2")
    assert patch._patch_csm_module(module) is True
    csm = module.CapitalCSMv2()

    assert csm.is_live_capital_valid() is True
    assert module.is_live_capital_valid() is True
    assert csm.original_calls == 1


def test_bridge_fails_closed_without_writer_authority(monkeypatch):
    monkeypatch.setenv("LIVE_CAPITAL_VERIFIED", "true")
    monkeypatch.setenv("DRY_RUN_MODE", "false")
    monkeypatch.setenv("PAPER_MODE", "false")
    monkeypatch.setenv("NIJA_RUNTIME_TRADING_STATE", "LIVE_ACTIVE")
    monkeypatch.setenv("NIJA_RUNTIME_EXECUTION_AUTHORITY", "0")
    monkeypatch.delenv("NIJA_WRITER_FENCING_TOKEN", raising=False)
    monkeypatch.delenv("NIJA_WRITER_LEASE_GENERATION", raising=False)

    ready, reason, detail = patch._capital_authority_snapshot_ready()

    assert ready is False
    assert "writer_authority_not_ready" in reason
    assert detail == {}
