from __future__ import annotations

import importlib
import sys
import threading
import types


def test_nonce_rebuild_coalesces_live_singleton(monkeypatch):
    module = types.ModuleType("bot.global_kraken_nonce")

    class Manager:
        _instance = None

    calls = {"n": 0}

    def rebuild():
        calls["n"] += 1
        obj = object()
        Manager._instance = obj
        module._nonce_manager = obj
        return obj

    module.KrakenNonceManager = Manager
    module._nonce_manager = None
    module.rebuild_nonce_manager = rebuild
    monkeypatch.setitem(sys.modules, "bot.global_kraken_nonce", module)

    patch = importlib.import_module("bot.startup_hook_nonce_v107_patch")
    patch._INSTALLED = False
    assert patch.install() is True

    first = module.rebuild_nonce_manager()
    second = module.rebuild_nonce_manager()
    assert first is second
    assert calls["n"] == 1


def test_nonce_rebuild_serializes_racing_callers(monkeypatch):
    module = types.ModuleType("bot.global_kraken_nonce")

    class Manager:
        _instance = None

    gate = threading.Event()
    calls = {"n": 0}

    def rebuild():
        calls["n"] += 1
        gate.wait(timeout=1)
        obj = object()
        Manager._instance = obj
        module._nonce_manager = obj
        return obj

    module.KrakenNonceManager = Manager
    module._nonce_manager = None
    module.rebuild_nonce_manager = rebuild
    monkeypatch.setitem(sys.modules, "bot.global_kraken_nonce", module)

    patch = importlib.reload(importlib.import_module("bot.startup_hook_nonce_v107_patch"))
    assert patch.install() is True

    results = []
    t1 = threading.Thread(target=lambda: results.append(module.rebuild_nonce_manager()))
    t2 = threading.Thread(target=lambda: results.append(module.rebuild_nonce_manager()))
    t1.start(); t2.start(); gate.set(); t1.join(); t2.join()

    assert len(results) == 2
    assert results[0] is results[1]
    assert calls["n"] == 1


def test_v99_source_contains_import_reentry_guard():
    v99 = importlib.import_module("bot.position_sync_account_isolation_v99_patch")
    assert hasattr(v99, "_IMPORT_LOCAL")
