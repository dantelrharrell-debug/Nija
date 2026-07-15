from __future__ import annotations

import os
import sys
from types import ModuleType

import runtime_convergence_quiescence_patch as patch


def test_chain_has_attr_detects_marker_and_cycle():
    def leaf():
        return None

    def outer():
        return None

    outer.__wrapped__ = leaf
    leaf._marker = True
    found, cycle, depth = patch._chain_has_attr(outer, "_marker")
    assert found is True
    assert cycle is False
    assert depth == 1

    leaf.__wrapped__ = outer
    found, cycle, _depth = patch._chain_has_attr(outer, "_missing")
    assert found is False
    assert cycle is True


def test_identity_wrapper_ignores_stale_latch_when_current_graph_is_clean(monkeypatch):
    module = ModuleType("runtime_module_identity_convergence_patch")
    calls = []

    def canonicalize():
        calls.append(os.environ.get("NIJA_DUPLICATE_PATCH_MODULE_DETECTED"))
        return True, {"risk": "clean"}

    module.canonicalize_loaded_patch_modules = canonicalize
    monkeypatch.setenv("NIJA_DUPLICATE_PATCH_MODULE_DETECTED", "1")
    monkeypatch.setattr(patch, "_current_module_duplicates", lambda: [])

    assert patch._patch_identity_module(module) is True
    ready, details = module.canonicalize_loaded_patch_modules()

    assert ready is True
    assert calls == ["0"]
    assert os.environ["NIJA_DUPLICATE_PATCH_MODULE_DETECTED"] == "0"
    assert "current_clean=true" in details["duplicate_latch"]


def test_identity_wrapper_preserves_fail_closed_for_current_duplicate(monkeypatch):
    module = ModuleType("runtime_module_identity_convergence_patch")
    module.canonicalize_loaded_patch_modules = lambda: (True, {})
    monkeypatch.setattr(patch, "_current_module_duplicates", lambda: ["nija_x->bot.x"])

    patch._patch_identity_module(module)
    ready, details = module.canonicalize_loaded_patch_modules()

    assert ready is False
    assert details["current_duplicate_modules"] == "nija_x->bot.x"
    assert os.environ["NIJA_DUPLICATE_PATCH_MODULE_DETECTED"] == "1"


def test_final_auth_repair_runs_once_after_quiescence():
    module = ModuleType("final_runtime_convergence_patch")
    calls = []
    module._replace_recursive_auth_hooks = lambda: calls.append("auth") or True
    module._patch_okx_classes = lambda: False

    assert patch._patch_final_convergence(module) is True
    assert module._replace_recursive_auth_hooks() is True
    assert module._replace_recursive_auth_hooks() is False
    assert calls == ["auth"]


def test_scan_owner_broker_patch_is_not_reapplied_when_markers_exist():
    module = ModuleType("scan_owner_okx_auth_convergence_patch")
    calls = []

    class CoinbaseBroker:
        def connect(self):
            return True

    class OKXBroker:
        def connect(self):
            return True

    CoinbaseBroker.connect._nija_coinbase_failfast_20260713b = True
    OKXBroker.connect._nija_okx_connect_canonical_20260713b = True
    target = ModuleType("bot.broker_manager")
    target.CoinbaseBroker = CoinbaseBroker
    target.OKXBroker = OKXBroker
    module._patch_brokers = lambda _target: calls.append("patched") or True

    assert patch._patch_scan_owner(module) is True
    assert module._patch_brokers(target) is False
    assert calls == []


def test_one_shot_guard_logs_only_first_success():
    module = ModuleType("scan_wrapper_convergence_repair_patch")
    calls = []
    module._guard_secondary_scan_owner = lambda: calls.append("guard") or True

    assert patch._patch_one_shot(module, "_guard_secondary_scan_owner") is True
    assert module._guard_secondary_scan_owner() is True
    assert module._guard_secondary_scan_owner() is True
    assert calls == ["guard"]
