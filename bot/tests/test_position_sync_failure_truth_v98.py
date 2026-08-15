from __future__ import annotations

import importlib
import os
from types import ModuleType, SimpleNamespace


def test_v98_revokes_previous_success_when_fetch_fails() -> None:
    patch = importlib.import_module("bot.position_sync_failure_truth_v98_patch")
    module = ModuleType("startup_position_sync_test_v98")
    module.__file__ = "/tmp/startup_position_sync.py"

    def adopt(broker, broker_name, eps):
        try:
            broker.get_positions()
        except Exception:
            return 0
        broker._startup_position_sync_adopted = True
        return 0

    module._adopt_broker_positions = adopt
    assert patch._patch_startup_sync(module)

    def timeout():
        raise TimeoutError("position snapshot timed out")

    broker = SimpleNamespace(
        _startup_position_sync_adopted=True,
        _startup_position_sync_symbols=("ETH-USD",),
        get_positions=timeout,
    )
    os.environ["NIJA_POSITION_SYNC_ACTIVATION_READY"] = "1"
    os.environ["NIJA_POSITION_SYNC_DISPATCH_READY"] = "1"

    assert module._adopt_broker_positions(broker, "platform:kraken", None) == 0
    assert broker._startup_position_sync_adopted is False
    assert broker._startup_position_sync_symbols == tuple()
    assert os.environ["NIJA_POSITION_SYNC_ACTIVATION_READY"] == "0"
    assert os.environ["NIJA_POSITION_SYNC_DISPATCH_READY"] == "0"


def test_v98_allows_fresh_success_to_reestablish_sync() -> None:
    patch = importlib.import_module("bot.position_sync_failure_truth_v98_patch")
    module = ModuleType("startup_position_sync_test_v98_success")
    module.__file__ = "/tmp/startup_position_sync.py"

    def adopt(broker, broker_name, eps):
        broker.get_positions()
        broker._startup_position_sync_adopted = True
        broker._startup_position_sync_symbols = tuple()
        return 0

    module._adopt_broker_positions = adopt
    assert patch._patch_startup_sync(module)

    broker = SimpleNamespace(
        _startup_position_sync_adopted=True,
        _startup_position_sync_symbols=("ETH-USD",),
        get_positions=lambda: [],
    )

    assert module._adopt_broker_positions(broker, "user:test:kraken", None) == 0
    assert broker._startup_position_sync_adopted is True
    assert broker._startup_position_sync_symbols == tuple()


def test_v98_installer_is_mandatory_after_v97() -> None:
    source = open("bot/bot.py", "r", encoding="utf-8").read()
    v97 = source.index('(\"bot.runtime_truth_convergence_v97_patch\", \"RUNTIME_TRUTH_CONVERGENCE_V97\")')
    v98 = source.index('(\"bot.position_sync_failure_truth_v98_patch\", \"POSITION_SYNC_FAILURE_TRUTH_V98\")')
    integrity = source.index('(\"bot.strategy_runtime_integrity_patch\", \"STRATEGY_RUNTIME_INTEGRITY\")')
    assert v97 < v98 < integrity
