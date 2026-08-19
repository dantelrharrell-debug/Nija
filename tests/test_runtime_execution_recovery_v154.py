from __future__ import annotations

import sys
import types

from bot import runtime_execution_recovery_v154_patch as v154


def _install_readiness_table(monkeypatch, snapshot):
    fake = types.ModuleType("bot.readiness_table")
    fake.snapshot = lambda: dict(snapshot)
    monkeypatch.setitem(sys.modules, "bot.readiness_table", fake)


def test_execution_ready_is_not_a_pre_authority_blocker(monkeypatch):
    _install_readiness_table(
        monkeypatch,
        {
            "broker_connected": True,
            "balance_hydrated": True,
            "capital_ready": True,
            "risk_ready": True,
            "strategy_ready": True,
            "execution_ready": False,
            "bootstrap_ready": True,
            "position_sync_ready": True,
        },
    )

    assert v154._safe_structural_blockers() == []


def test_structural_readiness_remains_fail_closed(monkeypatch):
    _install_readiness_table(
        monkeypatch,
        {
            "broker_connected": True,
            "balance_hydrated": True,
            "capital_ready": False,
            "risk_ready": True,
            "strategy_ready": False,
            "execution_ready": False,
            "bootstrap_ready": True,
            "position_sync_ready": False,
        },
    )

    assert v154._safe_structural_blockers() == [
        "capital_ready",
        "strategy_ready",
        "position_sync_ready",
    ]


def test_missing_readiness_table_fails_closed(monkeypatch):
    monkeypatch.delitem(sys.modules, "bot.readiness_table", raising=False)
    monkeypatch.delitem(sys.modules, "readiness_table", raising=False)

    # Force imports to fail regardless of what the repository environment has.
    original_import = __import__

    def guarded_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name in {"bot.readiness_table", "readiness_table"} or (
            name == "bot" and fromlist and "readiness_table" in fromlist
        ):
            raise ImportError("readiness table unavailable")
        return original_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr("builtins.__import__", guarded_import)
    assert v154._safe_structural_blockers() == ["readiness_table_unavailable"]
