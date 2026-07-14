from __future__ import annotations

import sys
from types import ModuleType, SimpleNamespace

import runtime_module_identity_convergence_patch as guard


def _module(name: str, file_path: str, marker: str = "") -> ModuleType:
    module = ModuleType(name)
    module.__file__ = file_path
    module._MARKER = marker
    module.install_import_hook = lambda: None
    return module


def _no_threads(monkeypatch):
    monkeypatch.setattr(guard.threading, "enumerate", lambda: [])
    monkeypatch.delenv("NIJA_DUPLICATE_PATCH_MODULE_DETECTED", raising=False)


def _install_clean_risk_identity(monkeypatch):
    downstream = _module(
        guard._RISK_ALIAS,
        "/app/bot/downstream_risk_governor_equity_repair_patch.py",
        guard._REQUIRED_RISK_MARKER,
    )
    monkeypatch.setitem(sys.modules, guard._RISK_ALIAS, downstream)
    monkeypatch.setitem(sys.modules, guard._RISK_CANONICAL, downstream)
    return downstream


def test_unregistered_sitecustomize_module_is_recovered_from_monitor_thread(monkeypatch):
    monkeypatch.delenv("NIJA_DUPLICATE_PATCH_MODULE_DETECTED", raising=False)
    globals_dict = {
        "__name__": guard._RISK_ALIAS,
        "__file__": "/app/bot/downstream_risk_governor_equity_repair_patch.py",
        "_MARKER": guard._REQUIRED_RISK_MARKER,
        "install_import_hook": lambda: None,
    }

    class Target:
        __globals__ = globals_dict

        def __call__(self):
            return None

    fake_thread = SimpleNamespace(name="downstream-risk-v2-monitor", _target=Target())
    monkeypatch.setattr(guard.threading, "enumerate", lambda: [fake_thread])
    monkeypatch.delitem(sys.modules, guard._RISK_ALIAS, raising=False)
    monkeypatch.delitem(sys.modules, guard._RISK_CANONICAL, raising=False)

    recovered = guard.recover_unregistered_patch_modules_from_threads()

    assert guard._RISK_CANONICAL in recovered
    assert isinstance(sys.modules[guard._RISK_CANONICAL], ModuleType)
    assert sys.modules[guard._RISK_ALIAS] is sys.modules[guard._RISK_CANONICAL]
    assert sys.modules[guard._RISK_CANONICAL]._MARKER == guard._REQUIRED_RISK_MARKER
    assert "duplicate=false" in recovered[guard._RISK_CANONICAL]


def test_alias_is_bound_to_canonical_module_before_second_import(monkeypatch):
    _no_threads(monkeypatch)
    alias = _module(
        guard._RISK_ALIAS,
        "/app/bot/downstream_risk_governor_equity_repair_patch.py",
        guard._REQUIRED_RISK_MARKER,
    )
    monkeypatch.setitem(sys.modules, guard._RISK_ALIAS, alias)
    monkeypatch.delitem(sys.modules, guard._RISK_CANONICAL, raising=False)

    ready, details = guard.canonicalize_loaded_patch_modules()

    assert ready is True
    assert sys.modules[guard._RISK_CANONICAL] is alias
    assert sys.modules[guard._RISK_ALIAS] is alias
    assert "same_object=true" in details[guard._RISK_CANONICAL]
    assert guard._REQUIRED_RISK_MARKER in details[guard._RISK_CANONICAL]


def test_duplicate_modules_select_v2_and_latch_fail_closed(monkeypatch):
    _no_threads(monkeypatch)
    legacy = _module(
        guard._RISK_CANONICAL,
        "/app/bot/downstream_risk_governor_equity_repair_patch.py",
        "20260707a",
    )
    v2 = _module(
        guard._RISK_ALIAS,
        "/app/bot/downstream_risk_governor_equity_repair_patch.py",
        guard._REQUIRED_RISK_MARKER,
    )
    monkeypatch.setitem(sys.modules, guard._RISK_CANONICAL, legacy)
    monkeypatch.setitem(sys.modules, guard._RISK_ALIAS, v2)

    ready, _details = guard.canonicalize_loaded_patch_modules()

    assert ready is False
    assert sys.modules[guard._RISK_CANONICAL] is v2
    assert sys.modules[guard._RISK_ALIAS] is v2
    assert guard.os.environ["NIJA_DUPLICATE_PATCH_MODULE_DETECTED"] == "1"


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


def test_runtime_limits_cap_streak_normalize_stale_threshold_and_raise_timeout(monkeypatch):
    monkeypatch.setenv("NIJA_ZERO_SIGNAL_STREAK_CAP", "999")
    monkeypatch.setenv("NIJA_ZERO_SIGNAL_STREAK_STALE_THRESHOLD", "10")
    monkeypatch.setenv("NIJA_RUN_CYCLE_PHASE3_TIMEOUT_S", "30")

    guard.normalize_runtime_limits()

    assert guard.os.environ["NIJA_ZERO_SIGNAL_STREAK_CAP"] == "12"
    assert guard.os.environ["NIJA_ZERO_SIGNAL_STREAK_STALE_THRESHOLD"] == "13"
    assert float(guard.os.environ["NIJA_RUN_CYCLE_PHASE3_TIMEOUT_S"]) == 120.0
    assert guard.os.environ["NIJA_CORE_LOOP_PROGRESS_LIMITS_NORMALIZED"] == "1"


def test_audit_accepts_both_phase3_guards_in_any_wrapper_order(monkeypatch):
    _no_threads(monkeypatch)
    _install_clean_risk_identity(monkeypatch)
    monkeypatch.delitem(sys.modules, "bot.execution_pipeline", raising=False)
    monkeypatch.delitem(sys.modules, "execution_pipeline", raising=False)

    core = ModuleType("bot.nija_core_loop")

    def leaf(self, broker, snapshot, symbols, slots, streak=0):
        return None

    setattr(leaf, guard._ZERO_CAP_ATTR, True)

    def outer(self, broker, snapshot, symbols, slots, streak=0):
        return leaf(self, broker, snapshot, symbols, slots, streak)

    outer.__wrapped__ = leaf
    setattr(outer, guard._ZERO_STATE_ATTR, True)
    core.NijaCoreLoop = type("NijaCoreLoop", (), {"_phase3_scan_and_enter": outer})
    monkeypatch.setitem(sys.modules, "bot.nija_core_loop", core)
    monkeypatch.delitem(sys.modules, "nija_core_loop", raising=False)

    ready, details = guard.audit()

    assert ready is True
    assert "cap_guard=True" in details["zero_signal_streak_chain"]
    assert "state_repair=True" in details["zero_signal_streak_chain"]
    assert "cycle=False" in details["zero_signal_streak_chain"]


def test_audit_rejects_legacy_execution_wrapper(monkeypatch):
    _no_threads(monkeypatch)
    _install_clean_risk_identity(monkeypatch)
    monkeypatch.delitem(sys.modules, "bot.nija_core_loop", raising=False)
    monkeypatch.delitem(sys.modules, "nija_core_loop", raising=False)

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
