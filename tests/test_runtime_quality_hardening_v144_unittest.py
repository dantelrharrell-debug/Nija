from __future__ import annotations

import importlib.util
import os
import sys
import types
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
PATCH_PATH = ROOT / "bot" / "runtime_quality_hardening_v144_patch.py"
SPEC = importlib.util.spec_from_file_location("runtime_quality_hardening_v144_under_test", PATCH_PATH)
assert SPEC is not None and SPEC.loader is not None
v144 = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(v144)


class RuntimeQualityHardeningV144Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.env = patch.dict(os.environ, {}, clear=False)
        self.env.start()
        for key in (
            "DRY_RUN_MODE",
            "PAPER_MODE",
            "NIJA_RECONCILIATION_STATUS",
            "NIJA_RECONCILIATION_COMPLETE",
            "NIJA_REQUIRE_STARTUP_RECONCILIATION",
            "NIJA_LIVE_AI_GATE_REQUIRED",
            "NIJA_LIVE_MIN_GATE_QUALITY_PCT",
        ):
            os.environ.pop(key, None)

    def tearDown(self) -> None:
        self.env.stop()

    def test_live_reconciliation_missing_fails_closed(self) -> None:
        ok, detail = v144._reconciliation_status()
        self.assertFalse(ok)
        self.assertIn("status=missing", detail)
        self.assertIn("complete=false", detail)

    def test_clean_complete_reconciliation_passes(self) -> None:
        os.environ["NIJA_RECONCILIATION_STATUS"] = "CLEAN"
        os.environ["NIJA_RECONCILIATION_COMPLETE"] = "true"
        ok, detail = v144._reconciliation_status()
        self.assertTrue(ok)
        self.assertEqual(detail, "")

    def test_trading_state_gate_never_fail_opens_live_missing_status(self) -> None:
        module = types.ModuleType("fake_tsm")

        def legacy_gate():
            return True, "legacy_fail_open"

        module._startup_reconciliation_gate = legacy_gate
        self.assertTrue(v144._patch_trading_state_machine(module))
        ok, detail = module._startup_reconciliation_gate()
        self.assertFalse(ok)
        self.assertIn("missing", detail)

    def test_simulation_can_explicitly_disable_reconciliation(self) -> None:
        os.environ["DRY_RUN_MODE"] = "true"
        os.environ["NIJA_REQUIRE_STARTUP_RECONCILIATION"] = "false"
        module = types.ModuleType("fake_tsm_sim")
        module._startup_reconciliation_gate = lambda: (False, "legacy")
        self.assertTrue(v144._patch_trading_state_machine(module))
        self.assertEqual(module._startup_reconciliation_gate(), (True, ""))

    def test_entry_pipeline_blocks_new_exposure_until_reconciled(self) -> None:
        module = types.ModuleType("fake_pipeline")

        class PipelineResult:
            def __init__(self, **kwargs):
                self.__dict__.update(kwargs)

        class ExecutionPipeline:
            def execute(self, request, *args, **kwargs):
                return PipelineResult(success=True, symbol=request.symbol, side=request.side, size_usd=request.size_usd)

        module.PipelineResult = PipelineResult
        module.ExecutionPipeline = ExecutionPipeline
        self.assertTrue(v144._patch_execution_pipeline(module))
        request = SimpleNamespace(symbol="ADA-USD", side="buy", size_usd=25.0, intent_type="entry", reduce_only=False)
        result = ExecutionPipeline().execute(request)
        self.assertFalse(result.success)
        self.assertIn("STARTUP_RECONCILIATION_INCOMPLETE", result.error)

    def test_exit_pipeline_remains_available_when_reconciliation_missing(self) -> None:
        module = types.ModuleType("fake_pipeline_exit")

        class PipelineResult:
            def __init__(self, **kwargs):
                self.__dict__.update(kwargs)

        class ExecutionPipeline:
            def execute(self, request, *args, **kwargs):
                return PipelineResult(success=True, symbol=request.symbol, side=request.side, size_usd=request.size_usd)

        module.PipelineResult = PipelineResult
        module.ExecutionPipeline = ExecutionPipeline
        self.assertTrue(v144._patch_execution_pipeline(module))
        request = SimpleNamespace(
            symbol="ETH-USD",
            side="sell",
            size_usd=72.0,
            intent_type="exit",
            position_effect="reduce",
            reduce_only=True,
        )
        result = ExecutionPipeline().execute(request)
        self.assertTrue(result.success)

    def test_entry_pipeline_passes_after_clean_reconciliation(self) -> None:
        os.environ["NIJA_RECONCILIATION_STATUS"] = "CLEAN_START"
        os.environ["NIJA_RECONCILIATION_COMPLETE"] = "1"
        module = types.ModuleType("fake_pipeline_clean")

        class PipelineResult:
            def __init__(self, **kwargs):
                self.__dict__.update(kwargs)

        class ExecutionPipeline:
            def execute(self, request, *args, **kwargs):
                return PipelineResult(success=True, order_id="order-123")

        module.PipelineResult = PipelineResult
        module.ExecutionPipeline = ExecutionPipeline
        self.assertTrue(v144._patch_execution_pipeline(module))
        request = SimpleNamespace(symbol="ADA-USD", side="buy", size_usd=25.0, intent_type="entry", reduce_only=False)
        result = ExecutionPipeline().execute(request)
        self.assertTrue(result.success)
        self.assertEqual(result.order_id, "order-123")

    def test_live_ai_signal_requires_canonical_gate_pass(self) -> None:
        module = types.ModuleType("fake_ai")

        class NijaAIEngine:
            def evaluate_symbol(self, *args, **kwargs):
                return SimpleNamespace(
                    symbol="ADA-USD",
                    side="long",
                    composite_score=38.35,
                    metadata={"gate_passed": False, "gate_quality": 0.0},
                )

        module.NijaAIEngine = NijaAIEngine
        self.assertTrue(v144._patch_ai_engine(module))
        self.assertIsNone(NijaAIEngine().evaluate_symbol())

    def test_live_ai_signal_allows_passed_gate(self) -> None:
        module = types.ModuleType("fake_ai_pass")

        class NijaAIEngine:
            def evaluate_symbol(self, *args, **kwargs):
                return SimpleNamespace(
                    symbol="BTC-USD",
                    side="long",
                    composite_score=55.0,
                    metadata={"gate_passed": True, "gate_quality": 62.0},
                )

        module.NijaAIEngine = NijaAIEngine
        self.assertTrue(v144._patch_ai_engine(module))
        signal = NijaAIEngine().evaluate_symbol()
        self.assertIsNotNone(signal)
        self.assertEqual(signal.symbol, "BTC-USD")

    def test_optional_live_gate_quality_floor_is_enforced(self) -> None:
        os.environ["NIJA_LIVE_MIN_GATE_QUALITY_PCT"] = "40"
        module = types.ModuleType("fake_ai_quality")

        class NijaAIEngine:
            def evaluate_symbol(self, *args, **kwargs):
                return SimpleNamespace(
                    symbol="SOL-USD",
                    side="long",
                    composite_score=50.0,
                    metadata={"gate_passed": True, "gate_quality": 25.0},
                )

        module.NijaAIEngine = NijaAIEngine
        self.assertTrue(v144._patch_ai_engine(module))
        self.assertIsNone(NijaAIEngine().evaluate_symbol())

    def test_readiness_success_logging_is_idempotent(self) -> None:
        module = types.ModuleType("fake_readiness")
        module._TABLE = {"broker_connected": False}
        import threading
        module._LOCK = threading.Lock()
        module.logger = types.SimpleNamespace(info=lambda *a, **k: None, debug=lambda *a, **k: None)

        def set_ready(component, value):
            with module._LOCK:
                module._TABLE[component] = bool(value)

        module.set_ready = set_ready
        module.mark_ready = lambda component: None
        self.assertTrue(v144._patch_readiness_table(module))
        module.mark_ready("broker_connected")
        module.mark_ready("broker_connected")
        self.assertTrue(module._TABLE["broker_connected"])

    def test_entry_classification_never_blocks_reduce_only(self) -> None:
        self.assertFalse(v144._entry_increases_exposure(SimpleNamespace(reduce_only=True, side="buy", intent_type="entry")))
        self.assertFalse(v144._entry_increases_exposure(SimpleNamespace(reduce_only=False, side="sell", intent_type="exit")))
        self.assertTrue(v144._entry_increases_exposure(SimpleNamespace(reduce_only=False, side="buy", intent_type="entry")))


if __name__ == "__main__":
    unittest.main()
