from __future__ import annotations

import importlib
import sys
import threading
from types import ModuleType

import final_runtime_convergence_patch as final_patch
import runtime_convergence_hardening_patch as hardening
import runtime_convergence_v2_patch as v2


class _Broker:
    account_id = "platform"
    broker_name = "kraken"


class _CoreLoop:
    def run_scan_phase(self, *args, **kwargs):
        return None


def _core_module(name: str = "bot.nija_core_loop") -> ModuleType:
    module = ModuleType(name)
    module.NijaCoreLoop = _CoreLoop
    return module


def test_hardening_install_does_not_replace_global_importlib(monkeypatch):
    original = importlib.import_module
    monkeypatch.setattr(hardening, "_WATCHDOG_STARTED", False)
    monkeypatch.setattr(hardening, "_try_loaded", lambda: False)
    monkeypatch.setattr(threading.Thread, "start", lambda self: None)
    hardening.install()
    assert importlib.import_module is original


def test_hardening_duplicate_scan_returns_result_object(monkeypatch):
    module = _core_module("nija_core_loop_hardening_test")
    assert hardening._patch_core_loop(module) is True
    instance = module.NijaCoreLoop()
    key = hardening._broker_identity(_Broker())
    lock = hardening._SCAN_LOCKS.setdefault(key, threading.RLock())
    assert lock.acquire(timeout=0.1)
    try:
        result = instance.run_scan_phase(broker=_Broker())
    finally:
        lock.release()
    assert result.symbols_scored == 0
    assert result.entries_blocked == 1
    assert result.next_interval >= 5


def test_v2_duplicate_scan_returns_result_object(monkeypatch):
    module = _core_module("nija_core_loop_v2_test")
    assert v2._patch_core_loop(module) is True
    instance = module.NijaCoreLoop()
    key = v2._identity(_Broker())
    lock = v2._SCAN_LOCKS.setdefault(key, threading.Lock())
    assert lock.acquire(timeout=0.1)
    try:
        result = instance.run_scan_phase(broker=_Broker())
    finally:
        lock.release()
    assert result.symbols_scored == 0
    assert result.entries_blocked == 1
    assert result.next_interval >= 5


def test_final_patch_coerces_none_and_tuple():
    none_result = final_patch._coerce_scan_result(None)
    tuple_result = final_patch._coerce_scan_result((4, 2, 1, {"next_interval": 7, "exits_taken": 3}))
    assert none_result.symbols_scored == 0
    assert none_result.entries_blocked == 1
    assert tuple_result.symbols_scored == 4
    assert tuple_result.entries_taken == 1
    assert tuple_result.entries_blocked == 2
    assert tuple_result.exits_taken == 3
    assert tuple_result.next_interval == 7


def test_final_watchdog_patches_late_loaded_core_loop(monkeypatch):
    module = _core_module()
    monkeypatch.setitem(sys.modules, "bot.nija_core_loop", module)
    assert final_patch._patch_loaded() is True
    result = module.NijaCoreLoop().run_scan_phase(broker=_Broker())
    assert result.symbols_scored == 0
    assert result.entries_blocked == 1
