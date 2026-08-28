from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType


MODULE_PATH = Path(__file__).resolve().parents[1] / "bot" / "exchange_kill_switch_internal_reject_guard_patch.py"


def _load_guard():
    spec = importlib.util.spec_from_file_location("test_early_recorder_guard_v260", MODULE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _build_surfaces(guard):
    kill_module = ModuleType("test_exchange_kill_switch_v260")

    class ExchangeKillSwitchProtector:
        def __init__(self):
            self.samples = []

        def record_order_result(self, order_id: str, accepted: bool, *args, **kwargs):
            self.samples.append(bool(accepted))
            return None

    kill_module.ExchangeKillSwitchProtector = ExchangeKillSwitchProtector
    protector = ExchangeKillSwitchProtector()

    pipeline_module = ModuleType("test_execution_pipeline_v260")

    class ExecutionPipeline:
        def _emit_execution_rejection_telemetry(self, *, symbol: str, side: str, reason: str):
            protector.record_order_result(
                order_id=f"exec-reject:pipeline:{symbol}:{side}",
                accepted=False,
            )
            return None

    pipeline_module.ExecutionPipeline = ExecutionPipeline

    assert guard._patch_module(kill_module) is True
    assert guard._patch_execution_pipeline_module(pipeline_module) is True
    return protector, ExecutionPipeline()


def test_v260_known_local_reject_never_enters_exchange_window():
    guard = _load_guard()
    protector, pipeline = _build_surfaces(guard)

    pipeline._emit_execution_rejection_telemetry(
        symbol="BTC-USD",
        side="buy",
        reason="dispatch_disabled: dispatch.enabled=false",
    )

    assert protector.samples == []


def test_v260_genuine_exchange_reject_remains_fail_closed():
    guard = _load_guard()
    protector, pipeline = _build_surfaces(guard)

    pipeline._emit_execution_rejection_telemetry(
        symbol="BTC-USD",
        side="buy",
        reason="Coinbase order rejected: insufficient liquidity",
    )

    assert protector.samples == [False]


def test_v260_unknown_reject_remains_fail_closed():
    guard = _load_guard()
    protector, pipeline = _build_surfaces(guard)

    pipeline._emit_execution_rejection_telemetry(
        symbol="BTC-USD",
        side="buy",
        reason="unknown exchange rejection",
    )

    assert protector.samples == [False]
