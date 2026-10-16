"""Regression: circular proof dependency is identified without authorizing trades.

These tests intentionally document the present deadlock. A future replacement
must pass updated tests with verified pre-dispatch controls, not by bypassing
execution guards.
"""
from __future__ import annotations
import importlib.util
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]


def load(filename, name):
    spec = importlib.util.spec_from_file_location(name, ROOT / filename)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def test_execution_authority_guard_rejects_idle_missing_canonical_proof(monkeypatch):
    v361 = load("bot/runtime_execution_authority_proof_gate_v361_patch.py",
                "nija_test_v451_v361")
    class Readiness:
        @staticmethod
        def snapshot():
            return {"broker_connected": True, "capital_ready": True,
                    "risk_ready": True, "strategy_ready": True,
                    "position_sync_ready": True, "execution_ready": False}
    original = v361.importlib.import_module
    monkeypatch.setattr(v361.importlib, "import_module",
                        lambda name: Readiness if name == "bot.readiness_table"
                        else original(name))
    assert v361._canonical_execution_ready()[0] is False


def test_stale_live_guard_also_rejects_same_idle_state(monkeypatch):
    v362 = load("bot/runtime_stale_live_execution_proof_v362_patch.py",
                "nija_test_v451_v362")
    class Readiness:
        @staticmethod
        def snapshot():
            return {"execution_ready": False}
    original = v362.importlib.import_module
    monkeypatch.setattr(v362.importlib, "import_module",
                        lambda name: Readiness if name == "bot.readiness_table"
                        else original(name))
    assert v362._canonical_execution_ready()[0] is False


def test_recovery_classification_never_authorizes_new_orders():
    recovery = load("bot/startup_recovery_readonly.py", "nija_test_v451_recovery")
    status = recovery.classify_recovery(
        {"broker_connected": True, "authority_ready": True,
         "capital_ready": True, "risk_ready": True,
         "strategy_ready": True, "nonce_ready": True,
         "position_sync_ready": True, "execution_ready": False},
        kill_switch_clear=True,
        startup_attempts_reconciled=True,
        protective_exits_verified=True,
        ledger_reconciled=True,
    )
    assert status.allow_new_orders is False
    assert status.reasons == ("execution_ready",)
