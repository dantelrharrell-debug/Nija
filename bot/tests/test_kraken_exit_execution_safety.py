from __future__ import annotations

import importlib.util
import types
from functools import wraps
from pathlib import Path
from types import SimpleNamespace


BOT_DIR = Path(__file__).resolve().parents[1]


def load_module(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, BOT_DIR / filename)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


safety = load_module(
    "kraken_exit_execution_safety_under_test",
    "kraken_exit_execution_safety_patch.py",
)


def test_broad_exit_wrapper_is_replaced_and_downstream_guard_stays_active():
    sentinel = object()

    class ExecutionPipeline:
        def __init__(self):
            self._pre_trade_risk_engine = sentinel
            self._allocation_clamp = sentinel
            self._execution_observer = sentinel
            self._throttler = sentinel
            self._downstream_guard = sentinel

        def execute(self, request):
            return (
                self._pre_trade_risk_engine,
                self._allocation_clamp,
                self._execution_observer,
                self._throttler,
                self._downstream_guard,
            )

    original = ExecutionPipeline.execute

    @wraps(original)
    def broad_wrapper(self, request):
        names = (
            "_pre_trade_risk_engine", "_allocation_clamp", "_execution_observer",
            "_throttler", "_downstream_guard",
        )
        saved = {name: getattr(self, name) for name in names}
        try:
            for name in names:
                setattr(self, name, None)
            return original(self, request)
        finally:
            for name, value in saved.items():
                setattr(self, name, value)

    broad_wrapper._nija_exit_entry_gate_split_v1 = True
    ExecutionPipeline.execute = broad_wrapper

    module = types.ModuleType("bot.execution_pipeline")
    module.ExecutionPipeline = ExecutionPipeline
    assert safety._patch_execution_pipeline(module)

    pipeline = ExecutionPipeline()
    exit_request = SimpleNamespace(
        intent_type="exit",
        position_effect="close",
        metadata={"closing_position": True},
        account_id="tania_gilbert",
        symbol="AIR-EUR",
    )
    entry_request = SimpleNamespace(
        intent_type="entry",
        position_effect=None,
        metadata={},
        account_id="tania_gilbert",
        symbol="AIR-EUR",
    )

    assert pipeline.execute(exit_request) == (
        None,
        None,
        sentinel,
        None,
        sentinel,
    )
    assert pipeline.execute(entry_request) == (
        sentinel,
        sentinel,
        sentinel,
        sentinel,
        sentinel,
    )
    assert pipeline._execution_observer is sentinel
    assert pipeline._downstream_guard is sentinel
