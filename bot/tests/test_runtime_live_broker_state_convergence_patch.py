from __future__ import annotations

import logging
import os
from types import ModuleType, SimpleNamespace

import runtime_live_broker_state_convergence_patch as patch


def test_stale_coinbase_failure_recovers_from_live_success(monkeypatch):
    monkeypatch.setenv("NIJA_COINBASE_ACTIVATION_STATE", "connect_failed")
    monkeypatch.setenv("NIJA_COINBASE_CONNECTED", "1")
    monkeypatch.setenv("NIJA_COINBASE_TRADING_READY", "1")
    monkeypatch.setenv("NIJA_COINBASE_ACTIVATED", "1")
    monkeypatch.setenv("NIJA_COINBASE_SPENDABLE_QUOTE", "100.10593157")

    status = patch._reconcile_status(
        {
            "venue": "coinbase",
            "ready": False,
            "connected": True,
            "trading_ready": True,
            "activated": True,
            "activation_state": "connect_failed",
            "spendable_quote": 100.10593157,
            "reason": "activation_state:connect_failed",
        }
    )

    assert status["ready"] is True
    assert status["activation_state"] == "ready"
    assert status["reason"] == "ready"
    assert os.environ["NIJA_COINBASE_ACTIVATION_STATE"] == "ready"


def test_quarantined_okx_stays_disabled(monkeypatch):
    monkeypatch.setenv("NIJA_OKX_CREDENTIALS_QUARANTINED", "1")
    status = patch._reconcile_status(
        {
            "venue": "okx",
            "ready": True,
            "connected": True,
            "trading_ready": True,
            "activated": True,
            "activation_state": "ready",
            "spendable_quote": 50.0,
            "reason": "ready",
        }
    )

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


def test_phase3_expected_needle_warning_is_filtered():
    noise_filter = patch._ExpectedNeedleNoiseFilter()
    noisy = logging.LogRecord(
        name="nija.phase3_force_override_terminal_guard",
        level=logging.WARNING,
        pathname=__file__,
        lineno=1,
        msg="PHASE3_FORCE_OVERRIDE_TERMINAL_GUARD_DIRECT_NEEDLE_MISSING marker=20260707k",
        args=(),
        exc_info=None,
    )
    normal = logging.LogRecord(
        name="nija.phase3_force_override_terminal_guard",
        level=logging.WARNING,
        pathname=__file__,
        lineno=1,
        msg="real phase3 failure",
        args=(),
        exc_info=None,
    )
    assert noise_filter.filter(noisy) is False
    assert noise_filter.filter(normal) is True
