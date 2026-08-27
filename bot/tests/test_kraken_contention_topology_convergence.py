from __future__ import annotations

import sys
from types import ModuleType

import bot.runtime_kraken_local_contention_health_v237_patch as v237
import bot.runtime_kraken_local_contention_instance_v242_patch as v242
import bot.runtime_kraken_read_lock_recovery_v234_patch as v234


def _manager_module_with_kraken() -> ModuleType:
    module = ModuleType("bot.broker_manager")

    class KrakenBroker:
        def _kraken_private_call(self, method, *_args, **_kwargs):
            return {"result": {}, "method": method}

        def get_account_balance(self, *_args, **_kwargs):
            return 1.0

        def connect(self, *_args, **_kwargs):
            return True

    module.KrakenBroker = KrakenBroker
    return module


def test_v234_accepts_canonical_broker_manager_without_integration_kraken_class(monkeypatch):
    module = _manager_module_with_kraken()
    monkeypatch.setitem(sys.modules, "bot.broker_manager", module)
    monkeypatch.setattr(v234, "_MODULES", ("bot.broker_manager",))

    ready, patched, modules = v234._patch_all_kraken_classes()

    assert ready is True
    assert patched == 1
    assert modules == ("bot.broker_manager",)


def test_v237_accepts_canonical_broker_manager_balance_owner(monkeypatch):
    module = _manager_module_with_kraken()
    monkeypatch.setitem(sys.modules, "bot.broker_manager", module)
    monkeypatch.setattr(v237, "_MODULES", ("bot.broker_manager",))

    assert v237._patch_kraken_balance_health() is True


def test_v242_accepts_canonical_broker_manager_instance_owner(monkeypatch):
    module = _manager_module_with_kraken()
    monkeypatch.setitem(sys.modules, "bot.broker_manager", module)
    monkeypatch.setattr(v242, "_MODULES", ("bot.broker_manager",))

    ready, patched, modules = v242._patch_aliases()

    assert ready is True
    assert patched == 1
    assert modules == ("bot.broker_manager",)
