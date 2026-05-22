"""
Tests for the four cycle-integrity tightenings:

1. Immutability — _capture_cycle_capital_state returns a MappingProxyType.
2. Sync failure isolation — CA/MABM read errors set sync_failed=True and log WARNING.
3. Execution-layer snapshot enforcement — cycle_id drift in execute() logs WARNING.
4. Cycle integrity validation — missing cycle_id in run() signal logs WARNING.
"""

from __future__ import annotations

import logging
import os
import sys
import types
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)


# ---------------------------------------------------------------------------
# 1. Immutability: _capture_cycle_capital_state returns MappingProxyType
# ---------------------------------------------------------------------------

class TestCaptureCycleCapitalStateImmutability(unittest.TestCase):
    """_capture_cycle_capital_state must return a MappingProxyType."""

    def _invoke_with_good_ca(self):
        """Run _capture_cycle_capital_state with CA available and healthy."""
        import bot.nija_core_loop as ncl_mod

        # Save originals
        orig_ca_available = ncl_mod._CA_LOOP_AVAILABLE
        orig_get_ca = ncl_mod._get_ca
        orig_event = ncl_mod._CAPITAL_HYDRATED_EVENT

        # Stub CA to succeed
        _ca = SimpleNamespace(is_hydrated=True, total_capital=1000.0)

        # Inject stubs directly into module globals
        ncl_mod._CA_LOOP_AVAILABLE = True
        ncl_mod._get_ca = lambda: _ca
        ncl_mod._CAPITAL_HYDRATED_EVENT = None

        try:
            # Suppress MABM import noise
            with patch.dict(sys.modules, {
                "multi_account_broker_manager": None,
                "bot.multi_account_broker_manager": None,
            }):
                result = ncl_mod._capture_cycle_capital_state()
        finally:
            ncl_mod._CA_LOOP_AVAILABLE = orig_ca_available
            ncl_mod._get_ca = orig_get_ca
            ncl_mod._CAPITAL_HYDRATED_EVENT = orig_event
        return result

    def test_returns_mapping_proxy(self):
        """Return type must be MappingProxyType, not a plain dict."""
        result = self._invoke_with_good_ca()
        self.assertIsInstance(
            result,
            types.MappingProxyType,
            "Expected MappingProxyType; got %s" % type(result).__name__,
        )

    def test_mapping_proxy_is_immutable(self):
        """Writing to the proxy must raise TypeError."""
        result = self._invoke_with_good_ca()
        with self.assertRaises(TypeError):
            result["ca_total_capital"] = 99999.0  # type: ignore[index]

    def test_read_access_works(self):
        """Standard .get() reads must still work on the proxy."""
        result = self._invoke_with_good_ca()
        self.assertIn("ca_is_hydrated", result)
        self.assertIsInstance(result.get("ca_total_capital"), float)
        self.assertEqual(result.get("ca_total_capital"), 1000.0)


# ---------------------------------------------------------------------------
# 2. Sync failure isolation — CA/MABM failures set sync_failed and log WARNING
# ---------------------------------------------------------------------------

class TestSyncFailedFlag(unittest.TestCase):
    """CA/MABM read errors must set sync_failed=True and emit a WARNING."""

    def _run_with_ca_failure(self):
        import bot.nija_core_loop as ncl_mod

        orig_ca_available = ncl_mod._CA_LOOP_AVAILABLE
        orig_get_ca = ncl_mod._get_ca
        orig_event = ncl_mod._CAPITAL_HYDRATED_EVENT

        def bad_ca():
            raise RuntimeError("CA exploded")

        ncl_mod._CA_LOOP_AVAILABLE = True
        ncl_mod._get_ca = bad_ca
        ncl_mod._CAPITAL_HYDRATED_EVENT = None

        log_records: list = []

        class _Capture(logging.Handler):
            def emit(self, record):
                log_records.append(record)

        handler = _Capture()
        log = logging.getLogger("nija.core_loop")
        log.addHandler(handler)
        old_level = log.level
        log.setLevel(logging.DEBUG)
        try:
            with patch.dict(sys.modules, {
                "multi_account_broker_manager": None,
                "bot.multi_account_broker_manager": None,
            }):
                result = ncl_mod._capture_cycle_capital_state()
        finally:
            log.removeHandler(handler)
            log.setLevel(old_level)
            ncl_mod._CA_LOOP_AVAILABLE = orig_ca_available
            ncl_mod._get_ca = orig_get_ca
            ncl_mod._CAPITAL_HYDRATED_EVENT = orig_event
        return result, log_records

    def test_sync_failed_true_on_ca_error(self):
        result, _ = self._run_with_ca_failure()
        self.assertTrue(
            result.get("sync_failed"),
            "sync_failed should be True when CA read raises",
        )

    def test_warning_logged_on_ca_error(self):
        _, records = self._run_with_ca_failure()
        warnings = [r for r in records if r.levelno == logging.WARNING and "CA read failed" in r.getMessage()]
        self.assertTrue(warnings, "Expected a WARNING log about CA read failure")


# ---------------------------------------------------------------------------
# 3. Execution-layer snapshot enforcement — cycle_id drift logs WARNING
# ---------------------------------------------------------------------------

class TestPipelineCycleIdDriftWarning(unittest.TestCase):
    """execute() should log a WARNING when correlation cycle_id ≠ snapshot cycle_id."""

    def _make_pipeline(self, dispatch_fn=None):
        from bot.execution_pipeline import ExecutionPipeline
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
        pipeline._enforce_execution_gate = lambda request, t_start: None
        pipeline._emit_execution_rejection_telemetry = lambda **kwargs: None
        if dispatch_fn is None:
            pipeline._dispatch = lambda request, t_start: SimpleNamespace(
                success=True, symbol=request.symbol, side=request.side,
                size_usd=request.size_usd, fill_price=0.0, filled_size_usd=0.0,
                broker="test", error=None, throttled=False, latency_ms=0.0,
            )
        else:
            pipeline._dispatch = dispatch_fn
        return pipeline

    def test_warning_on_cycle_id_mismatch(self):
        """A WARNING should fire when correlation cycle_id ≠ snapshot cycle_id."""
        from bot.execution_pipeline import ExecutionPipeline, PipelineRequest
        import bot.execution_pipeline as ep_mod

        pipeline = self._make_pipeline()

        log_records: list = []

        class _Cap(logging.Handler):
            def emit(self, record):
                log_records.append(record)

        handler = _Cap()
        log = logging.getLogger("nija.execution_pipeline")
        log.addHandler(handler)
        old_level = log.level
        log.setLevel(logging.DEBUG)

        stale_snap = SimpleNamespace(cycle_id="cycle-OLD-000001")
        fake_corr = {
            "cycle_id": "cycle-NEW-999999",
            "intent_id": "",
        }

        try:
            with patch("bot.execution_pipeline.assert_distributed_writer_authority", return_value=None), \
                 patch("bot.execution_pipeline.assert_execution_dispatch_permitted", return_value=None), \
                 patch("bot.execution_pipeline.runtime_authority_snapshot", return_value=SimpleNamespace(ready=True)), \
                 patch("bot.execution_pipeline.get_seak", return_value=SimpleNamespace(is_halted=False)), \
                 patch("bot.execution_pipeline.get_runtime_correlation", return_value=fake_corr), \
                 patch("bot.execution_pipeline._get_pipeline_cycle_snapshot", return_value=stale_snap), \
                 patch("bot.execution_pipeline.append_execution_journal_event", return_value=None):
                request = PipelineRequest(symbol="BTC-USD", side="buy", size_usd=25.0)
                pipeline.execute(request)
        finally:
            log.removeHandler(handler)
            log.setLevel(old_level)

        drift_warnings = [
            r for r in log_records
            if r.levelno == logging.WARNING and "cycle_id lineage drift" in r.getMessage()
        ]
        self.assertTrue(drift_warnings, "Expected a cycle_id lineage drift WARNING")

    def test_no_warning_when_cycle_ids_match(self):
        """No drift warning should fire when correlation and snapshot cycle_ids are equal."""
        from bot.execution_pipeline import ExecutionPipeline, PipelineRequest

        pipeline = self._make_pipeline()

        log_records: list = []

        class _Cap(logging.Handler):
            def emit(self, record):
                log_records.append(record)

        handler = _Cap()
        log = logging.getLogger("nija.execution_pipeline")
        log.addHandler(handler)
        old_level = log.level
        log.setLevel(logging.DEBUG)

        same_cid = "cycle-2026T120000-000001"
        snap = SimpleNamespace(cycle_id=same_cid)
        fake_corr = {"cycle_id": same_cid, "intent_id": ""}

        try:
            with patch("bot.execution_pipeline.assert_distributed_writer_authority", return_value=None), \
                 patch("bot.execution_pipeline.assert_execution_dispatch_permitted", return_value=None), \
                 patch("bot.execution_pipeline.runtime_authority_snapshot", return_value=SimpleNamespace(ready=True)), \
                 patch("bot.execution_pipeline.get_seak", return_value=SimpleNamespace(is_halted=False)), \
                 patch("bot.execution_pipeline.get_runtime_correlation", return_value=fake_corr), \
                 patch("bot.execution_pipeline._get_pipeline_cycle_snapshot", return_value=snap), \
                 patch("bot.execution_pipeline.append_execution_journal_event", return_value=None):
                request = PipelineRequest(symbol="ETH-USD", side="sell", size_usd=30.0)
                pipeline.execute(request)
        finally:
            log.removeHandler(handler)
            log.setLevel(old_level)

        drift_warnings = [
            r for r in log_records
            if r.levelno == logging.WARNING and "cycle_id lineage drift" in r.getMessage()
        ]
        self.assertFalse(drift_warnings, "Should NOT log cycle_id drift when IDs match")


# ---------------------------------------------------------------------------
# 4. Cycle integrity validation — missing cycle_id in run() signal warns
# ---------------------------------------------------------------------------

class TestRunFallbackCycleIdWarning(unittest.TestCase):
    """run() should log a WARNING when signal has no cycle_id (synthetic fallback used)."""

    def _make_minimal_pipeline(self):
        from bot.execution_pipeline import ExecutionPipeline
        pipeline = ExecutionPipeline.__new__(ExecutionPipeline)
        pipeline._lock = __import__("threading").Lock()
        pipeline._run_count = 0
        pipeline._blocked_count = 0
        pipeline._last_run = None
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
        pipeline._enforce_execution_gate = lambda request, t_start: None
        pipeline._emit_execution_rejection_telemetry = lambda **kwargs: None
        return pipeline

    def test_warning_logged_when_signal_missing_cycle_id(self):
        """A WARNING should fire when signal dict lacks cycle_id."""
        import bot.execution_pipeline as ep_mod
        pipeline = self._make_minimal_pipeline()

        # Use "enter_long" to pass the early-action gate in run().
        # No cycle_id — expects the synthetic-fallback WARNING.
        signal = {
            "action": "enter_long",
            "symbol": "BTC-USD",
            "size_usd": 50.0,
            # deliberately no "cycle_id"
        }

        log_records: list = []

        class _Cap(logging.Handler):
            def emit(self, record):
                log_records.append(record)

        handler = _Cap()
        log = logging.getLogger("nija.execution_pipeline")
        log.addHandler(handler)
        old_level = log.level
        log.setLevel(logging.DEBUG)
        try:
            with patch.object(ep_mod, "get_execution_integrity_layer", None), \
                 patch.object(ep_mod, "get_global_capital_manager", None), \
                 patch.object(ep_mod, "get_master_strategy_router", None), \
                 patch.object(ep_mod, "get_signal_broadcaster", None), \
                 patch.object(ep_mod, "get_account_performance_dashboard", None), \
                 patch.object(ep_mod, "get_profit_splitter", None), \
                 patch.object(ep_mod, "get_regime_specific_strategy_evolution", None), \
                 patch.object(ep_mod, "get_ai_capital_allocator", None):
                pipeline.run(signal=signal, account_id="test", account_balance=5000.0)
        finally:
            log.removeHandler(handler)
            log.setLevel(old_level)

        missing_id_warnings = [
            r for r in log_records
            if r.levelno == logging.WARNING and "cycle_id missing" in r.getMessage()
        ]
        self.assertTrue(
            missing_id_warnings,
            "Expected a WARNING about missing cycle_id; got warnings: %s"
            % [r.getMessage() for r in log_records if r.levelno == logging.WARNING],
        )

    def test_no_warning_when_signal_has_cycle_id(self):
        """No fallback WARNING should fire when signal provides a real cycle_id."""
        import bot.execution_pipeline as ep_mod
        pipeline = self._make_minimal_pipeline()

        signal = {
            "action": "enter_long",
            "symbol": "BTC-USD",
            "size_usd": 50.0,
            "cycle_id": "cycle-2026T120000-000099",
        }

        log_records: list = []

        class _Cap(logging.Handler):
            def emit(self, record):
                log_records.append(record)

        handler = _Cap()
        log = logging.getLogger("nija.execution_pipeline")
        log.addHandler(handler)
        old_level = log.level
        log.setLevel(logging.DEBUG)
        try:
            with patch.object(ep_mod, "get_execution_integrity_layer", None), \
                 patch.object(ep_mod, "get_global_capital_manager", None), \
                 patch.object(ep_mod, "get_master_strategy_router", None), \
                 patch.object(ep_mod, "get_signal_broadcaster", None), \
                 patch.object(ep_mod, "get_account_performance_dashboard", None), \
                 patch.object(ep_mod, "get_profit_splitter", None), \
                 patch.object(ep_mod, "get_regime_specific_strategy_evolution", None), \
                 patch.object(ep_mod, "get_ai_capital_allocator", None):
                pipeline.run(signal=signal, account_id="test", account_balance=5000.0)
        finally:
            log.removeHandler(handler)
            log.setLevel(old_level)

        missing_id_warnings = [
            r for r in log_records
            if r.levelno == logging.WARNING and "cycle_id missing" in r.getMessage()
        ]
        self.assertFalse(
            missing_id_warnings,
            "Should NOT warn about missing cycle_id when signal provides one",
        )


if __name__ == "__main__":
    unittest.main()
