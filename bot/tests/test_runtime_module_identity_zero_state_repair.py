from __future__ import annotations

import sys
from types import ModuleType

import runtime_module_identity_convergence_patch as identity


def test_audit_reinstalls_missing_zero_signal_state_wrapper(monkeypatch):
    core = ModuleType("bot.nija_core_loop")

    class NijaCoreLoop:
        def _phase3_scan_and_enter(
            self,
            broker,
            snapshot,
            symbols,
            available_slots,
            zero_signal_streak=0,
        ):
            return 0, 0, 0, {}

    setattr(
        NijaCoreLoop._phase3_scan_and_enter,
        identity._ZERO_CAP_ATTR,
        True,
    )
    core.NijaCoreLoop = NijaCoreLoop
    monkeypatch.setitem(sys.modules, "bot.nija_core_loop", core)
    monkeypatch.delitem(sys.modules, "nija_core_loop", raising=False)

    risk = ModuleType(identity._RISK_CANONICAL)
    risk._MARKER = identity._REQUIRED_RISK_MARKER
    monkeypatch.setitem(sys.modules, identity._RISK_CANONICAL, risk)
    monkeypatch.setitem(sys.modules, identity._RISK_ALIAS, risk)

    pipeline = ModuleType("bot.execution_pipeline")

    class ExecutionPipeline:
        def execute(self):
            return None

    setattr(ExecutionPipeline.execute, identity._V2_RISK_ATTR, True)
    pipeline.ExecutionPipeline = ExecutionPipeline
    monkeypatch.setitem(sys.modules, "bot.execution_pipeline", pipeline)
    monkeypatch.delitem(sys.modules, "execution_pipeline", raising=False)

    monkeypatch.setattr(
        identity,
        "canonicalize_loaded_patch_modules",
        lambda: (True, {}),
    )

    ready, details = identity.audit()

    assert ready is True
    assert "state_repair=True" in details["zero_signal_streak_chain"]
    assert identity.os.environ["NIJA_ZERO_SIGNAL_STREAK_STATE_READY"] == "1"
