from __future__ import annotations

import os
import sys
import types

import pytest

import bot.canonical_broker_bootstrap_handoff_patch as patch


class FakeAuthority:
    def __init__(self, hydrated=True, capital=125.0, stale=False):
        self.is_hydrated = hydrated
        self._capital = capital
        self._stale = stale

    def get_real_capital(self):
        return self._capital

    def is_stale(self):
        return self._stale


class FakeManager:
    def __init__(self, authority: FakeAuthority, initialize_ok=True):
        self._fsm_initialized = False
        self._capital_last_valid_brokers = 0
        self.authority = authority
        self.initialize_ok = initialize_ok
        self.initialize_calls = 0
        self.refresh_calls = 0

    def initialize(self):
        self.initialize_calls += 1
        if self.initialize_ok:
            self._fsm_initialized = True
            self._capital_last_valid_brokers = 1

    def has_registered_sources(self):
        return self._fsm_initialized

    def has_attempted_connections(self):
        return self._fsm_initialized

    def refresh_capital_authority(self, trigger=None):
        self.refresh_calls += 1


def _install_fake_modules(monkeypatch, manager, authority):
    mabm_mod = types.ModuleType("bot.multi_account_broker_manager")
    mabm_mod.multi_account_broker_manager = manager
    ca_mod = types.ModuleType("bot.capital_authority")
    ca_mod.get_capital_authority = lambda: authority
    monkeypatch.setitem(sys.modules, "bot.multi_account_broker_manager", mabm_mod)
    monkeypatch.setitem(sys.modules, "bot.capital_authority", ca_mod)


def test_initializes_existing_manager_and_requires_positive_live_capital(monkeypatch):
    authority = FakeAuthority()
    manager = FakeManager(authority)
    _install_fake_modules(monkeypatch, manager, authority)
    monkeypatch.setenv("LIVE_CAPITAL_VERIFIED", "true")
    monkeypatch.setenv("DRY_RUN_MODE", "false")
    monkeypatch.setenv("PAPER_MODE", "false")

    broker = object()
    result = patch._initialize_canonical_broker_runtime(broker, "kraken")

    assert result == (True, broker, "kraken")
    assert manager.initialize_calls == 1
    assert os.environ["NIJA_CANONICAL_BROKER_BOOTSTRAP_READY"] == "1"


def test_fails_closed_when_manager_initialization_does_not_wire_fsm(monkeypatch):
    authority = FakeAuthority()
    manager = FakeManager(authority, initialize_ok=False)
    _install_fake_modules(monkeypatch, manager, authority)

    with pytest.raises(RuntimeError, match="fsm_not_initialized"):
        patch._initialize_canonical_broker_runtime(object(), "kraken")


def test_wrapper_stops_bot_main_when_canonical_handoff_fails(monkeypatch):
    fake_bot_main = types.ModuleType("bot.bot_main")
    broker = object()
    fake_bot_main._run_self_healing_startup = lambda: (True, broker, "kraken")
    assert patch._patch_bot_main(fake_bot_main)

    def fail_handoff(_broker, _name):
        raise RuntimeError("capital unavailable")

    monkeypatch.setattr(patch, "_initialize_canonical_broker_runtime", fail_handoff)
    assert fake_bot_main._run_self_healing_startup() == (False, None, "")
    assert os.environ["NIJA_CANONICAL_BROKER_BOOTSTRAP_READY"] == "0"
