from __future__ import annotations

import logging
import os
from types import ModuleType, SimpleNamespace

import runtime_live_broker_state_convergence_patch as patch


def test_coinbase_live_balance_promotes_missing_activation_flags(monkeypatch):
    monkeypatch.setenv("NIJA_COINBASE_ACTIVATION_STATE", "unknown")
    monkeypatch.setenv("NIJA_COINBASE_CONNECTED", "1")
    monkeypatch.setenv("NIJA_COINBASE_BALANCE_OBSERVED", "1")
    monkeypatch.setenv("NIJA_COINBASE_CREDENTIALS_NORMALIZED", "1")
    monkeypatch.setenv("NIJA_COINBASE_SPENDABLE_QUOTE", "100.10593157")

    status = patch._reconcile_status({
        "venue": "coinbase", "ready": False, "connected": True,
        "trading_ready": False, "activated": False,
        "activation_state": "unknown", "spendable_quote": 100.10593157,
        "reason": "activation_state:unknown",
    })

    assert status["ready"] is True
    assert status["trading_ready"] is True
    assert status["activated"] is True
    assert status["activation_state"] == "ready"
    assert os.environ["NIJA_COINBASE_TRADING_READY"] == "1"
    assert os.environ["NIJA_COINBASE_ACTIVATED"] == "1"


def test_quarantined_okx_stays_disabled(monkeypatch):
    monkeypatch.setenv("NIJA_OKX_CREDENTIALS_QUARANTINED", "1")
    status = patch._reconcile_status({
        "venue": "okx", "ready": True, "connected": True,
        "trading_ready": True, "activated": True,
        "activation_state": "ready", "spendable_quote": 50.0, "reason": "ready",
    })
    assert status["ready"] is False
    assert status["connected"] is False
    assert status["activation_state"] == "quarantined"
    assert status["reason"] == "credentials_quarantined"


def test_auth_patch_module_is_deduplicated():
    calls = []
    state = SimpleNamespace(lock=patch.threading.RLock())
    module = ModuleType("broker_auth_recovery_patch")
    module._state = lambda: state
    def original(target):
        calls.append(target)
        return True
    module._patch_module = original
    assert patch._patch_auth_recovery(module) is True
    target = ModuleType("bot.broker_manager")
    assert module._patch_module(target) is True
    assert module._patch_module(target) is True
    assert len(calls) == 1


def test_safe_scan_depth_is_accepted(monkeypatch):
    module = ModuleType("scan_wrapper_depth_convergence_patch")
    module.audit = lambda: (False, {"scan_chain": "depth=52;max=64;broker_layers=1;canonical_layers=25;cycle=False;head=x;tail=y"})
    monkeypatch.setitem(patch.sys.modules, "scan_wrapper_depth_convergence_patch", module)
    assert patch._accept_safe_scan_depth() is True
    assert os.environ["NIJA_SCAN_WRAPPER_DEPTH_READY"] == "1"


def test_phase3_expected_needle_warning_is_filtered():
    noise_filter = patch._NoiseFilter()
    noisy = logging.LogRecord(
        name="nija.phase3_force_override_terminal_guard", level=logging.WARNING,
        pathname=__file__, lineno=1,
        msg="PHASE3_FORCE_OVERRIDE_TERMINAL_GUARD_DIRECT_NEEDLE_MISSING marker=20260707k",
        args=(), exc_info=None,
    )
    normal = logging.LogRecord(
        name="nija.phase3_force_override_terminal_guard", level=logging.WARNING,
        pathname=__file__, lineno=1, msg="real phase3 failure", args=(), exc_info=None,
    )
    assert noise_filter.filter(noisy) is False
    assert noise_filter.filter(normal) is True
