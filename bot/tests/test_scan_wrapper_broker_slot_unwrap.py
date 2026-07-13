from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType, SimpleNamespace


ROOT = Path(__file__).resolve().parents[2]


def _load():
    spec = importlib.util.spec_from_file_location(
        "scan_wrapper_convergence_under_test",
        ROOT / "scan_wrapper_convergence_repair_patch.py",
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _result(scored: int = 1):
    return SimpleNamespace(
        symbols_scored=scored,
        entries_taken=0,
        entries_blocked=0,
        exits_taken=0,
        next_interval=15,
        errors=[],
        metadata={},
    )


def test_closure_held_broker_slot_base_is_unwrapped():
    patch = _load()

    def base(self, *args, **kwargs):
        return _result(7)

    original_run_scan_phase = base

    def broker_slot_wrapper(self, *args, **kwargs):
        return original_run_scan_phase(self, *args, **kwargs)

    broker_slot_wrapper._nija_broker_slot_scoped = True
    resolved, depth, cycle = patch._unwrap_known(broker_slot_wrapper)
    assert resolved is base
    assert depth == 1
    assert cycle is False


def test_canonical_wrapper_executes_user_scan_once_without_reentry_block():
    patch = _load()
    calls = []

    def base(self, *args, **kwargs):
        calls.append(kwargs.get("broker"))
        return _result(11)

    original_run_scan_phase = base

    def broker_slot_wrapper(self, *args, **kwargs):
        return original_run_scan_phase(self, *args, **kwargs)

    broker_slot_wrapper._nija_broker_slot_scoped = True

    class NijaCoreLoop:
        run_scan_phase = broker_slot_wrapper

    module = ModuleType("bot.nija_core_loop")
    module.NijaCoreLoop = NijaCoreLoop
    assert patch._patch_core_loop(module) is True

    broker = SimpleNamespace(
        account_identifier="USER:tania_gilbert",
        broker_type=SimpleNamespace(value="kraken"),
    )
    result = NijaCoreLoop().run_scan_phase(broker=broker)
    assert result.symbols_scored == 11
    assert result.entries_blocked == 0
    assert calls == [broker]
