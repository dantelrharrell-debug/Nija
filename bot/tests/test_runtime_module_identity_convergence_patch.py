from __future__ import annotations

import sys
from types import ModuleType

import runtime_module_identity_convergence_patch as guard


def _module(name: str, file_path: str, marker: str = "") -> ModuleType:
    module = ModuleType(name)
    module.__file__ = file_path
    module._MARKER = marker
    module.install_import_hook = lambda: None
    return module


def test_alias_is_bound_to_canonical_module_before_second_import(monkeypatch):
    alias_name = "nija_downstream_risk_governor_equity_repair_patch"
    canonical_name = "bot.downstream_risk_governor_equity_repair_patch"
    alias = _module(
        alias_name,
        "/app/bot/downstream_risk_governor_equity_repair_patch.py",
        "20260714-downstream-risk-v2",
    )
    monkeypatch.setitem(sys.modules, alias_name, alias)
    monkeypatch.delitem(sys.modules, canonical_name, raising=False)

    ready, details = guard.canonicalize_loaded_patch_modules()

    assert ready is True
    assert sys.modules[canonical_name] is alias
    assert sys.modules[alias_name] is alias
    assert details[canonical_name] == "same_object"


def test_duplicate_modules_select_v2_but_report_convergence_event(monkeypatch):
    alias_name = "nija_downstream_risk_governor_equity_repair_patch"
    canonical_name = "bot.downstream_risk_governor_equity_repair_patch"
    legacy = _module(
        canonical_name,
        "/app/bot/downstream_risk_governor_equity_repair_patch.py",
        "20260707a",
    )
    v2 = _module(
        alias_name,
        "/app/bot/downstream_risk_governor_equity_repair_patch.py",
        "20260714-downstream-risk-v2",
    )
    monkeypatch.setitem(sys.modules, canonical_name, legacy)
    monkeypatch.setitem(sys.modules, alias_name, v2)

    ready, _details = guard.canonicalize_loaded_patch_modules()

    assert ready is False
    assert sys.modules[canonical_name] is v2
    assert sys.modules[alias_name] is v2


def test_wrapper_chain_detects_v2_and_legacy_layers():
    def leaf(self, request):
        return None

    def v2(self, request):
        return leaf(self, request)

    v2.__wrapped__ = leaf
    setattr(v2, guard._V2_RISK_ATTR, True)

    def legacy(self, request):
        return v2(self, request)

    legacy.__wrapped__ = v2
    setattr(legacy, guard._LEGACY_RISK_ATTR, True)

    current, old, cycle, depth = guard._wrapper_chain_status(legacy)

    assert current is True
    assert old is True
    assert cycle is False
    assert depth == 2


def test_wrapper_chain_detects_cycle():
    def first(self, request):
        return None

    def second(self, request):
        return None

    first.__wrapped__ = second
    second.__wrapped__ = first

    _current, _old, cycle, _depth = guard._wrapper_chain_status(first)

    assert cycle is True


def test_runtime_limits_cap_streak_and_raise_false_stall_threshold(monkeypatch):
    monkeypatch.setenv("NIJA_ZERO_SIGNAL_STREAK_CAP", "999")
    monkeypatch.setenv("NIJA_RUN_CYCLE_PHASE3_TIMEOUT_S", "30")

    guard.normalize_runtime_limits()

    assert guard.os.environ["NIJA_ZERO_SIGNAL_STREAK_CAP"] == "12"
    assert float(guard.os.environ["NIJA_RUN_CYCLE_PHASE3_TIMEOUT_S"]) == 120.0
    assert guard.os.environ["NIJA_CORE_LOOP_PROGRESS_LIMITS_NORMALIZED"] == "1"


def test_audit_rejects_legacy_execution_wrapper(monkeypatch):
    alias_name = "nija_downstream_risk_governor_equity_repair_patch"
    canonical_name = "bot.downstream_risk_governor_equity_repair_patch"
    downstream = _module(
        alias_name,
        "/app/bot/downstream_risk_governor_equity_repair_patch.py",
        "20260714-downstream-risk-v2",
    )
    monkeypatch.setitem(sys.modules, alias_name, downstream)
    monkeypatch.setitem(sys.modules, canonical_name, downstream)

    pipeline = ModuleType("bot.execution_pipeline")

    def execute(self, request):
        return None

    setattr(execute, guard._LEGACY_RISK_ATTR, True)
    pipeline.ExecutionPipeline = type("ExecutionPipeline", (), {"execute": execute})
    monkeypatch.setitem(sys.modules, "bot.execution_pipeline", pipeline)
    monkeypatch.delitem(sys.modules, "execution_pipeline", raising=False)

    ready, details = guard.audit()

    assert ready is False
    assert "legacy=True" in details["execution_pipeline_chain"]
    assert guard.os.environ["NIJA_PRE_DISPATCH_RISK_SIZING_READY"] == "0"
