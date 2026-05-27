from __future__ import annotations

import os
import tempfile
import unittest
from contextlib import ExitStack
from types import SimpleNamespace
from unittest.mock import patch

from bot.execution_broker_capabilities import BrokerCapabilityRegistry
from bot.execution_pipeline import ExecutionPipeline, PipelineRequest, PipelineResult
from bot.margin_position_ledger import MarginPositionLedger


class ExecutionPipelineMarginLedgerHookTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.ledger = MarginPositionLedger(db_path=f"{self._tmp.name}/margin_position_ledger.db")

    def tearDown(self) -> None:
        self.ledger.stop_periodic_reconcile()
        self._tmp.cleanup()

    def _make_pipeline(self, dispatch_result: PipelineResult) -> ExecutionPipeline:
        pipeline = ExecutionPipeline.__new__(ExecutionPipeline)
        pipeline._execution_observer = None
        pipeline._allocation_clamp = None
        pipeline._exchange_normalizer = None
        pipeline._pre_trade_risk_engine = None
        pipeline._ecel = None
        pipeline._ecel_required = False
        pipeline._ecel_fail_closed = False
        pipeline._throttler = None
        pipeline._router = None
        pipeline._multi_router = None
        pipeline._downstream_guard = None
        pipeline._margin_position_ledger = self.ledger
        pipeline._broker_capability_registry = BrokerCapabilityRegistry()
        pipeline._enforce_execution_gate = lambda request, t_start: None
        pipeline._emit_execution_rejection_telemetry = lambda **kwargs: None
        pipeline._dispatch = lambda request, t_start: dispatch_result
        return pipeline

    @staticmethod
    def _request(**overrides) -> PipelineRequest:
        payload = {
            "request_id": "req-1",
            "intent_id": "intent-1",
            "strategy": "test_strategy",
            "symbol": "BTC-USD",
            "side": "buy",
            "size_usd": 100.0,
            "notional_usd": 100.0,
            "sizing_mode": "notional_usd",
            "asset_class": "crypto",
            "preferred_broker": "kraken",
            "account_id": "acc-1",
            "subaccount_id": "sub-1",
            "intent_type": "entry",
            "reduce_only": False,
            "margin_mode": "cross",
            "leverage": 1,
            "buying_power_usd": 250.0,
            "available_balance_usd": 250.0,
        }
        payload.update(overrides)
        return PipelineRequest(**payload)

    def _execute(self, pipeline: ExecutionPipeline, request: PipelineRequest):
        with ExitStack() as stack:
            stack.enter_context(patch.dict(os.environ, {"LIVE_CAPITAL_VERIFIED": "false", "NIJA_WRITER_FENCING_TOKEN": ""}, clear=False))
            stack.enter_context(patch("bot.execution_pipeline.assert_distributed_writer_authority", return_value=None))
            stack.enter_context(patch("bot.execution_pipeline.assert_execution_dispatch_permitted", return_value=None))
            stack.enter_context(patch("bot.execution_pipeline.runtime_authority_snapshot", return_value=SimpleNamespace(ready=True)))
            stack.enter_context(patch("bot.execution_pipeline.get_seak", return_value=SimpleNamespace(is_halted=False)))
            stack.enter_context(patch("bot.execution_pipeline.get_runtime_correlation", return_value={"intent_id": request.intent_id or "", "cycle_id": "cycle-1"}))
            stack.enter_context(patch("bot.execution_pipeline.append_execution_journal_event", return_value=None))
            stack.enter_context(patch("bot.execution_pipeline._get_pipeline_cycle_snapshot", return_value=SimpleNamespace(cycle_id="cycle-1")))
            return pipeline.execute(request)

    def test_submit_to_ack_fill_path_updates_open_state(self):
        dispatch = PipelineResult(success=True, symbol="BTC-USD", side="buy", size_usd=100.0, filled_size_usd=100.0, broker="kraken")
        pipeline = self._make_pipeline(dispatch)
        request = self._request()

        result = self._execute(pipeline, request)
        self.assertTrue(result.success)

        row = self.ledger.get_record(
            broker="kraken",
            account_id="acc-1",
            subaccount_id="sub-1",
            symbol="BTC-USD",
            asset_class="crypto",
        )
        self.assertEqual(row["lifecycle_status"], "open")
        self.assertEqual(float(row["position_notional_usd"]), 100.0)

    def test_partial_reduce_behavior_updates_reducing_state(self):
        pipeline = self._make_pipeline(PipelineResult(success=True, symbol="BTC-USD", side="buy", size_usd=100.0, filled_size_usd=100.0, broker="kraken"))
        self._execute(pipeline, self._request())

        pipeline._dispatch = lambda request, t_start: PipelineResult(
            success=True,
            symbol="BTC-USD",
            side="sell",
            size_usd=40.0,
            filled_size_usd=40.0,
            broker="kraken",
        )
        reduce_request = self._request(
            request_id="req-2",
            intent_id="intent-2",
            side="sell",
            intent_type="reduce",
            reduce_only=True,
            size_usd=40.0,
            notional_usd=40.0,
        )
        reduce_result = self._execute(pipeline, reduce_request)
        self.assertTrue(reduce_result.success)

        row = self.ledger.get_record(
            broker="kraken",
            account_id="acc-1",
            subaccount_id="sub-1",
            symbol="BTC-USD",
            asset_class="crypto",
        )
        self.assertEqual(row["lifecycle_status"], "reducing")
        self.assertEqual(float(row["position_notional_usd"]), 60.0)

    def test_rejection_does_not_mutate_open_exposure(self):
        pipeline = self._make_pipeline(PipelineResult(success=True, symbol="BTC-USD", side="buy", size_usd=100.0, filled_size_usd=100.0, broker="kraken"))
        self._execute(pipeline, self._request())

        pipeline._dispatch = lambda request, t_start: PipelineResult(
            success=False,
            symbol="BTC-USD",
            side="buy",
            size_usd=30.0,
            error="Invalid API Key",
        )
        reject_request = self._request(request_id="req-3", intent_id="intent-3", size_usd=30.0, notional_usd=30.0)
        reject_result = self._execute(pipeline, reject_request)
        self.assertFalse(reject_result.success)

        row = self.ledger.get_record(
            broker="kraken",
            account_id="acc-1",
            subaccount_id="sub-1",
            symbol="BTC-USD",
            asset_class="crypto",
        )
        self.assertEqual(row["lifecycle_status"], "rejected")
        self.assertEqual(float(row["position_notional_usd"]), 100.0)

    def test_reconcile_drift_correction_path(self):
        pipeline = self._make_pipeline(PipelineResult(success=True, symbol="BTC-USD", side="buy", size_usd=100.0, filled_size_usd=100.0, broker="kraken"))
        self._execute(pipeline, self._request())

        reconciliation = self.ledger.reconcile_snapshot(
            broker="kraken",
            account_id="acc-1",
            subaccount_id="sub-1",
            symbol="BTC-USD",
            asset_class="crypto",
            broker_units=0.005,
            broker_notional_usd=20.0,
            buying_power_usd=300.0,
            available_margin_usd=180.0,
            drift_threshold_usd=0.5,
        )
        self.assertTrue(reconciliation["corrected"])
        self.assertEqual(float(reconciliation["record"]["position_notional_usd"]), 20.0)

    def test_capability_registry_blocks_unsupported_combo(self):
        pipeline = self._make_pipeline(PipelineResult(success=True, symbol="BTC-USD", side="buy", size_usd=50.0, filled_size_usd=50.0, broker="coinbase"))
        request = self._request(
            request_id="req-coinbase",
            intent_id="intent-coinbase",
            preferred_broker="coinbase",
            leverage=2,
            margin_mode="cross",
            reduce_only=False,
        )
        result = self._execute(pipeline, request)
        self.assertFalse(result.success)
        self.assertIn("BrokerCapability deny", result.error)


if __name__ == "__main__":
    unittest.main()
