from __future__ import annotations

import sys
from types import ModuleType

from bot import runtime_kraken_local_contention_alias_v241_patch as v241
from bot import runtime_kraken_local_contention_health_v237_patch as v237
from bot import runtime_kraken_local_contention_instance_v242_patch as v242
from bot import runtime_kraken_read_lock_recovery_v234_patch as v234


class _CanonicalKrakenBroker:
    def _kraken_private_call(self, *_args, **_kwargs):
        return {"result": {}}

    def get_account_balance(self):
        return 0.0

    def connect(self):
        return True


def _install_test_topology(monkeypatch) -> None:
    canonical = ModuleType("bot.broker_manager")
    canonical.KrakenBroker = _CanonicalKrakenBroker
    integration = ModuleType("bot.broker_integration")
    integration.KrakenBrokerAdapter = type("KrakenBrokerAdapter", (), {})

    monkeypatch.setitem(sys.modules, "bot.broker_manager", canonical)
    monkeypatch.setitem(sys.modules, "broker_manager", canonical)
    monkeypatch.setitem(sys.modules, "bot.broker_integration", integration)
    monkeypatch.setitem(sys.modules, "broker_integration", integration)


def test_v234_accepts_canonical_broker_manager_topology(monkeypatch):
    _install_test_topology(monkeypatch)

    ready, patched, modules = v234._patch_all_kraken_classes()

    assert ready is True
    assert patched == 1
    assert "bot.broker_manager" in modules


def test_v237_accepts_canonical_broker_manager_topology(monkeypatch):
    _install_test_topology(monkeypatch)

    assert v237._patch_kraken_balance_health() is True


def test_v241_accepts_canonical_broker_manager_topology(monkeypatch):
    _install_test_topology(monkeypatch)

    ready, patched, modules = v241._patch_aliases()

    assert ready is True
    assert patched == 1
    assert "bot.broker_manager" in modules


def test_v242_accepts_canonical_broker_manager_topology(monkeypatch):
    _install_test_topology(monkeypatch)

    ready, patched, modules = v242._patch_aliases()

    assert ready is True
    assert patched == 1
    assert "bot.broker_manager" in modules
