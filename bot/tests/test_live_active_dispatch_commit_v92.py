from __future__ import annotations

import inspect
import os
import types

from bot import live_active_dispatch_commit_v92_patch as repair


class _LiveSM:
    def get_current_state(self):
        return "LIVE_ACTIVE"


class _Snapshot:
    def __init__(
        self,
        *,
        commit_version: int,
        execution_permitted: bool,
        runtime_authority_state: str = "AUTHORIZED",
    ):
        self.last_committed_snapshot_version = commit_version
        self.execution_permitted = execution_permitted
        self.runtime_authority_state = runtime_authority_state
        self.runtime_authority_reason = "test"
        self.capital_stale = False
        self.pending_readiness = []


def _enable_live_mode(monkeypatch):
    monkeypatch.setenv("LIVE_CAPITAL_VERIFIED", "1")
    monkeypatch.delenv("DRY_RUN_MODE", raising=False)
    monkeypatch.delenv("PAPER_MODE", raising=False)


def test_already_live_repairs_missing_coordinator_commit(monkeypatch):
    _enable_live_mode(monkeypatch)
    before = _Snapshot(commit_version=0, execution_permitted=False)
    after = _Snapshot(
        commit_version=17,
        execution_permitted=True,
        runtime_authority_state="EXECUTING",
    )

    class Coordinator:
        def __init__(self):
            self.finalize_calls = 0

        def build_snapshot(self, *, trading_state, activation_intent):
            assert trading_state == "LIVE_ACTIVE"
            assert activation_intent is True
            return before if self.finalize_calls == 0 else after

        def finalize_activation_commit(self, snapshot):
            assert snapshot is before
            self.finalize_calls += 1
            return 1

    coordinator = Coordinator()
    fake_module = types.SimpleNamespace(get_startup_coordinator=lambda: coordinator)
    real_import = repair.importlib.import_module

    def fake_import(name: str):
        if name == "bot.startup_coordinator":
            return fake_module
        return real_import(name)

    monkeypatch.setattr(repair.importlib, "import_module", fake_import)
    ok, reason, details = repair._ensure_coordinator_dispatch_commit(
        _LiveSM(),
        source="test",
    )

    assert ok is True
    assert reason == "dispatch_commit_repaired"
    assert coordinator.finalize_calls == 1
    assert details["before"]["commit_version"] == 0
    assert details["after"]["commit_version"] == 17
    assert details["after"]["execution_permitted"] is True


def test_already_live_with_current_dispatch_commit_is_idempotent(monkeypatch):
    _enable_live_mode(monkeypatch)
    snapshot = _Snapshot(
        commit_version=21,
        execution_permitted=True,
        runtime_authority_state="EXECUTING",
    )

    class Coordinator:
        def build_snapshot(self, *, trading_state, activation_intent):
            return snapshot

        def finalize_activation_commit(self, _snapshot):
            raise AssertionError("current dispatch commit must not be finalized again")

    fake_module = types.SimpleNamespace(get_startup_coordinator=lambda: Coordinator())
    real_import = repair.importlib.import_module

    def fake_import(name: str):
        if name == "bot.startup_coordinator":
            return fake_module
        return real_import(name)

    monkeypatch.setattr(repair.importlib, "import_module", fake_import)
    ok, reason, _details = repair._ensure_coordinator_dispatch_commit(
        _LiveSM(),
        source="test",
    )

    assert ok is True
    assert reason == "dispatch_commit_already_current"


def test_failed_readiness_proof_remains_fail_closed(monkeypatch):
    _enable_live_mode(monkeypatch)
    before = _Snapshot(commit_version=0, execution_permitted=False)

    class Coordinator:
        def build_snapshot(self, *, trading_state, activation_intent):
            return before

        def finalize_activation_commit(self, _snapshot):
            raise RuntimeError("LIVE commit blocked: system readiness proof failed at capital.not_stale")

    fake_module = types.SimpleNamespace(get_startup_coordinator=lambda: Coordinator())
    real_import = repair.importlib.import_module

    def fake_import(name: str):
        if name == "bot.startup_coordinator":
            return fake_module
        return real_import(name)

    monkeypatch.setattr(repair.importlib, "import_module", fake_import)
    ok, reason, details = repair._ensure_coordinator_dispatch_commit(
        _LiveSM(),
        source="test",
    )

    assert ok is False
    assert reason == "dispatch_commit_deferred:RuntimeError"
    assert "capital.not_stale" in details["error"]


def test_v92_source_does_not_force_activation_or_mutate_safety_thresholds():
    source = inspect.getsource(repair)
    forbidden = (
        "force_activate_live(",
        "transition_to(TradingState.LIVE_ACTIVE",
        'os.environ["NIJA_RUNTIME_EXECUTION_AUTHORITY"] = "1"',
        "MIN_ENTRY_SCORE =",
        "MIN_TRADE_USD =",
        "MINIMUM_TRADING_BALANCE =",
    )
    for text in forbidden:
        assert text not in source


def test_v92_installs_after_v60_on_canonical_fast_path():
    bot_path = os.path.join(os.path.dirname(__file__), "..", "bot.py")
    source = open(bot_path, encoding="utf-8").read()
    v60 = source.index("bot.final_production_activation_repair_v60_patch")
    v92 = source.index("bot.live_active_dispatch_commit_v92_patch")
    end = source.index("_FAST_PATH_COMPAT_OPTIONAL_GUARDS")
    assert v60 < v92 < end
