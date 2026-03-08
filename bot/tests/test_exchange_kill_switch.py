"""
Tests for bot/exchange_kill_switch.py
"""

from __future__ import annotations

import sys
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Allow imports from bot/
sys.path.insert(0, str(Path(__file__).parent.parent))

from exchange_kill_switch import (
    ExchangeKillSwitchConfig,
    ExchangeKillSwitchProtector,
    GateStatus,
    GateResult,
    ThreatLevel,
    get_exchange_kill_switch_protector,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def cfg_no_autotrigger():
    """Config with auto-trigger disabled so we can test gates independently."""
    return ExchangeKillSwitchConfig(
        api_error_window_seconds=60,
        api_error_rate_threshold=0.5,
        api_burst_threshold=5,
        api_burst_caution=3,
        price_stale_seconds=120.0,
        price_stale_caution_seconds=60.0,
        price_spike_pct=15.0,
        order_window_size=10,
        order_reject_rate_threshold=0.5,
        order_reject_rate_caution=0.25,
        latency_window_size=10,
        latency_p95_threshold_ms=5_000.0,
        latency_p95_caution_ms=2_000.0,
        phantom_fill_threshold=2,
        duplicate_order_threshold=2,
        auto_trigger_enabled=False,
    )


@pytest.fixture
def eksp(cfg_no_autotrigger, tmp_path):
    """Fresh protector with auto-trigger disabled and temp state file."""
    protector = ExchangeKillSwitchProtector(cfg_no_autotrigger)
    # Override state file to a temp location
    protector.STATE_FILE = tmp_path / "exchange_kill_switch_state.json"
    return protector


@pytest.fixture
def eksp_autotrigger(tmp_path):
    """Protector with auto-trigger ENABLED for integration tests."""
    cfg = ExchangeKillSwitchConfig(
        api_burst_threshold=3,
        auto_trigger_enabled=True,
    )
    protector = ExchangeKillSwitchProtector(cfg)
    protector.STATE_FILE = tmp_path / "exchange_kill_switch_state.json"
    return protector


# ---------------------------------------------------------------------------
# Gate 1 — API error-rate
# ---------------------------------------------------------------------------

class TestApiErrorRateGate:

    def test_green_on_no_calls(self, eksp):
        gate = eksp._gate_api_error_rate()
        assert gate.status == GateStatus.GREEN

    def test_green_on_all_successes(self, eksp):
        for _ in range(10):
            eksp.record_api_call(success=True, latency_ms=50.0)
        gate = eksp._gate_api_error_rate()
        assert gate.status == GateStatus.GREEN

    def test_yellow_on_caution_consecutive_errors(self, eksp):
        # 10 successes + 3 errors → error rate 23% (below 50% RED threshold)
        # but consecutive = 3 = caution threshold → YELLOW
        for _ in range(10):
            eksp.record_api_call(success=True)
        for _ in range(3):
            eksp.record_api_call(success=False)
        gate = eksp._gate_api_error_rate()
        assert gate.status == GateStatus.YELLOW

    def test_red_on_burst_threshold(self, eksp):
        # 5 consecutive errors (burst threshold)
        for _ in range(5):
            eksp.record_api_call(success=False)
        gate = eksp._gate_api_error_rate()
        assert gate.status == GateStatus.RED

    def test_red_on_high_error_rate(self, eksp):
        # Alternating success/fail to prevent consecutive burst from firing first.
        # 4 successes interleaved with 6 errors → 60% error rate ≥ 50% threshold
        # but consecutive never exceeds burst_threshold (5) due to interleaving.
        for i in range(4):
            eksp.record_api_call(success=True)
            eksp.record_api_call(success=False)
        eksp.record_api_call(success=False)
        eksp.record_api_call(success=False)
        gate = eksp._gate_api_error_rate()
        assert gate.status == GateStatus.RED
        assert "error rate" in gate.reason.lower()

    def test_success_resets_consecutive_counter(self, eksp):
        for _ in range(4):
            eksp.record_api_call(success=False)
        eksp.record_api_call(success=True)  # reset
        gate = eksp._gate_api_error_rate()
        # consecutive should now be 0 → below burst threshold
        with eksp._lock:
            assert eksp._consecutive_api_errors == 0

    def test_detail_dict_populated(self, eksp):
        eksp.record_api_call(success=True, latency_ms=30.0)
        gate = eksp._gate_api_error_rate()
        assert "window_calls" in gate.detail
        assert gate.detail["window_calls"] >= 1


# ---------------------------------------------------------------------------
# Gate 2 — Price-feed anomaly
# ---------------------------------------------------------------------------

class TestPriceFeedGate:

    def test_green_on_no_data(self, eksp):
        gate = eksp._gate_price_feed()
        assert gate.status == GateStatus.GREEN

    def test_green_on_fresh_price(self, eksp):
        eksp.record_price_tick("BTC-USD", 60_000.0)
        gate = eksp._gate_price_feed()
        assert gate.status == GateStatus.GREEN

    def test_red_on_zero_price(self, eksp):
        eksp.record_price_tick("ETH-USD", 0.0)
        gate = eksp._gate_price_feed()
        assert gate.status == GateStatus.RED
        assert "invalid price" in gate.reason.lower()

    def test_red_on_negative_price(self, eksp):
        eksp.record_price_tick("ETH-USD", -1.0)
        gate = eksp._gate_price_feed()
        assert gate.status == GateStatus.RED

    def test_red_on_stale_price(self, eksp):
        # Directly inject a very old timestamp
        with eksp._lock:
            eksp._price_state["BTC-USD"] = (60_000.0, time.monotonic() - 200.0)
        gate = eksp._gate_price_feed()
        assert gate.status == GateStatus.RED
        assert "stale" in gate.reason.lower()

    def test_yellow_on_caution_stale_price(self, eksp):
        # Between caution (60s) and red (120s)
        with eksp._lock:
            eksp._price_state["BTC-USD"] = (60_000.0, time.monotonic() - 90.0)
        gate = eksp._gate_price_feed()
        assert gate.status == GateStatus.YELLOW

    def test_spike_detection_fires_on_large_jump(self, eksp):
        eksp.record_price_tick("BTC-USD", 60_000.0)
        eksp.record_price_tick("BTC-USD", 75_000.0)  # +25% > 15% threshold
        gate = eksp._gate_price_feed()
        assert gate.status == GateStatus.RED
        assert "spike" in gate.reason.lower()

    def test_spike_detection_does_not_fire_on_small_jump(self, eksp):
        eksp.record_price_tick("BTC-USD", 60_000.0)
        eksp.record_price_tick("BTC-USD", 60_500.0)  # +0.83% — well under threshold
        gate = eksp._gate_price_feed()
        # Should still be green (no stale, no spike)
        assert gate.status == GateStatus.GREEN


# ---------------------------------------------------------------------------
# Gate 3 — Order-rejection rate
# ---------------------------------------------------------------------------

class TestOrderRejectionGate:

    def test_green_on_no_orders(self, eksp):
        gate = eksp._gate_order_rejection()
        assert gate.status == GateStatus.GREEN

    def test_green_on_all_accepted(self, eksp):
        for i in range(5):
            eksp.record_order_result(f"order-{i}", accepted=True)
        gate = eksp._gate_order_rejection()
        assert gate.status == GateStatus.GREEN

    def test_yellow_on_elevated_rejection(self, eksp):
        # 3 accepted, 1 rejected → 25% = caution threshold
        for i in range(3):
            eksp.record_order_result(f"order-{i}", accepted=True)
        eksp.record_order_result("order-bad", accepted=False)
        gate = eksp._gate_order_rejection()
        assert gate.status == GateStatus.YELLOW

    def test_red_on_high_rejection_rate(self, eksp):
        # 5 rejected, 5 accepted → 50% ≥ threshold
        for i in range(5):
            eksp.record_order_result(f"ok-{i}", accepted=True)
        for i in range(5):
            eksp.record_order_result(f"bad-{i}", accepted=False)
        gate = eksp._gate_order_rejection()
        assert gate.status == GateStatus.RED
        assert "rejection rate" in gate.reason.lower()

    def test_rolling_window_evicts_old_results(self, eksp):
        # Fill window with bad orders, then fill with good orders
        for i in range(10):
            eksp.record_order_result(f"bad-{i}", accepted=False)
        for i in range(10):
            eksp.record_order_result(f"ok-{i}", accepted=True)
        gate = eksp._gate_order_rejection()
        # Window size is 10 → only last 10 (all good) should be visible
        assert gate.status == GateStatus.GREEN


# ---------------------------------------------------------------------------
# Gate 4 — API latency
# ---------------------------------------------------------------------------

class TestApiLatencyGate:

    def test_green_on_no_data(self, eksp):
        gate = eksp._gate_api_latency()
        assert gate.status == GateStatus.GREEN

    def test_green_on_low_latency(self, eksp):
        for _ in range(10):
            eksp.record_api_call(success=True, latency_ms=100.0)
        gate = eksp._gate_api_latency()
        assert gate.status == GateStatus.GREEN

    def test_yellow_on_elevated_latency(self, eksp):
        # Push p95 between caution (2000) and threshold (5000)
        for _ in range(20):
            eksp.record_api_call(success=True, latency_ms=3_000.0)
        gate = eksp._gate_api_latency()
        assert gate.status == GateStatus.YELLOW

    def test_red_on_high_latency(self, eksp):
        for _ in range(10):
            eksp.record_api_call(success=True, latency_ms=6_000.0)
        gate = eksp._gate_api_latency()
        assert gate.status == GateStatus.RED
        assert "latency" in gate.reason.lower()

    def test_detail_contains_p95(self, eksp):
        for _ in range(10):
            eksp.record_api_call(success=True, latency_ms=200.0)
        gate = eksp._gate_api_latency()
        assert "p95_ms" in gate.detail


# ---------------------------------------------------------------------------
# Gate 5 — Phantom fill / duplicate order
# ---------------------------------------------------------------------------

class TestPhantomFillGate:

    def test_green_on_no_data(self, eksp):
        gate = eksp._gate_phantom_fill()
        assert gate.status == GateStatus.GREEN

    def test_green_on_unique_fills(self, eksp):
        eksp.record_fill_event("fill-1")
        eksp.record_fill_event("fill-2")
        gate = eksp._gate_phantom_fill()
        assert gate.status == GateStatus.GREEN

    def test_red_on_duplicate_fill(self, eksp):
        eksp.record_fill_event("fill-abc")
        eksp.record_fill_event("fill-abc")  # phantom fill threshold = 2
        gate = eksp._gate_phantom_fill()
        assert gate.status == GateStatus.RED
        assert "phantom" in gate.reason.lower()

    def test_red_on_duplicate_order_submission(self, eksp):
        eksp.record_order_submission("client-order-xyz")
        eksp.record_order_submission("client-order-xyz")
        gate = eksp._gate_phantom_fill()
        assert gate.status == GateStatus.RED
        assert "duplicate order" in gate.reason.lower()

    def test_single_fill_does_not_trigger(self, eksp):
        eksp.record_fill_event("fill-once")
        gate = eksp._gate_phantom_fill()
        assert gate.status == GateStatus.GREEN


# ---------------------------------------------------------------------------
# Composite threat level
# ---------------------------------------------------------------------------

class TestThreatLevel:

    def test_normal_when_all_green(self, eksp):
        assert eksp.get_threat_level() == ThreatLevel.NORMAL

    def test_elevated_when_any_yellow(self, eksp):
        # 10 successes then 3 errors → caution-level consecutive but error rate < 50%
        for _ in range(10):
            eksp.record_api_call(success=True)
        for _ in range(3):
            eksp.record_api_call(success=False)
        assert eksp.get_threat_level() == ThreatLevel.ELEVATED

    def test_critical_when_any_red(self, eksp):
        # Inject burst of errors (5)
        for _ in range(5):
            eksp.record_api_call(success=False)
        assert eksp.get_threat_level() == ThreatLevel.CRITICAL


# ---------------------------------------------------------------------------
# Auto-trigger integration (kill-switch patched out)
# ---------------------------------------------------------------------------

class TestAutoTrigger:

    @patch("exchange_kill_switch.get_kill_switch", autospec=False)
    def test_auto_trigger_fires_on_red_gate(self, mock_get_ks, tmp_path):
        cfg = ExchangeKillSwitchConfig(
            api_burst_threshold=3,
            auto_trigger_enabled=True,
        )
        eksp = ExchangeKillSwitchProtector(cfg)
        eksp.STATE_FILE = tmp_path / "state.json"

        mock_ks = MagicMock()
        mock_get_ks.return_value = mock_ks

        # Trigger burst
        for _ in range(3):
            eksp.record_api_call(success=False)

        assert eksp.is_triggered()
        mock_ks.activate.assert_called_once()
        call_kwargs = mock_ks.activate.call_args
        # Either positional or keyword 'source' argument should be EXCHANGE_MONITOR
        assert "EXCHANGE_MONITOR" in str(call_kwargs)

    @patch("exchange_kill_switch.get_kill_switch", autospec=False)
    def test_auto_trigger_is_idempotent(self, mock_get_ks, tmp_path):
        cfg = ExchangeKillSwitchConfig(api_burst_threshold=2, auto_trigger_enabled=True)
        eksp = ExchangeKillSwitchProtector(cfg)
        eksp.STATE_FILE = tmp_path / "state.json"
        mock_ks = MagicMock()
        mock_get_ks.return_value = mock_ks

        # Trigger twice
        for _ in range(2):
            eksp.record_api_call(success=False)
        for _ in range(2):
            eksp.record_api_call(success=False)

        # activate() should only have been called once
        assert mock_ks.activate.call_count == 1

    def test_no_auto_trigger_when_disabled(self, eksp):
        """When auto_trigger_enabled=False, no kill switch fires."""
        for _ in range(20):
            eksp.record_api_call(success=False)
        # Gates are RED but trigger disabled
        assert not eksp.is_triggered()


# ---------------------------------------------------------------------------
# Manual trigger & reset
# ---------------------------------------------------------------------------

class TestManualTriggerAndReset:

    @patch("exchange_kill_switch.get_kill_switch", autospec=False)
    def test_manual_trigger(self, mock_get_ks, eksp, tmp_path):
        eksp.STATE_FILE = tmp_path / "state.json"
        mock_ks = MagicMock()
        mock_get_ks.return_value = mock_ks

        eksp.manual_trigger("Testing manual trigger")
        assert eksp.is_triggered()
        mock_ks.activate.assert_called_once()

    @patch("exchange_kill_switch.get_kill_switch", autospec=False)
    def test_reset_clears_triggered_state(self, mock_get_ks, eksp, tmp_path):
        eksp.STATE_FILE = tmp_path / "state.json"
        mock_ks = MagicMock()
        mock_get_ks.return_value = mock_ks

        eksp.manual_trigger("trigger for reset test")
        assert eksp.is_triggered()

        eksp.reset("investigation complete")
        assert not eksp.is_triggered()

    def test_reset_clears_rolling_windows(self, eksp, tmp_path):
        eksp.STATE_FILE = tmp_path / "state.json"
        eksp.record_api_call(success=False)
        eksp.record_price_tick("BTC-USD", 60_000.0)
        eksp.record_fill_event("fill-1")

        eksp.reset("test")

        with eksp._lock:
            assert len(eksp._api_calls) == 0
            assert len(eksp._price_state) == 0
            assert len(eksp._fill_counts) == 0


# ---------------------------------------------------------------------------
# Status dict
# ---------------------------------------------------------------------------

class TestGetStatus:

    def test_status_keys_present(self, eksp):
        status = eksp.get_status()
        assert "triggered" in status
        assert "threat_level" in status
        assert "gates" in status
        assert "auto_trigger_enabled" in status
        assert "metrics" in status

    def test_status_gate_list_length(self, eksp):
        gates = eksp.get_status()["gates"]
        # Should have 5 gates
        assert len(gates) == 5

    def test_status_triggered_false_initially(self, eksp):
        assert eksp.get_status()["triggered"] is False


# ---------------------------------------------------------------------------
# Evaluate all gates
# ---------------------------------------------------------------------------

class TestEvaluateAllGates:

    def test_returns_list_of_gate_results(self, eksp):
        results = eksp.evaluate_all_gates()
        assert isinstance(results, list)
        assert all(isinstance(r, GateResult) for r in results)

    def test_gate_names_are_unique(self, eksp):
        results = eksp.evaluate_all_gates()
        names = [r.gate_name for r in results]
        assert len(names) == len(set(names))


# ---------------------------------------------------------------------------
# Singleton factory
# ---------------------------------------------------------------------------

class TestSingletonFactory:

    def test_returns_same_instance(self, tmp_path):
        import exchange_kill_switch as eks_module
        # Reset module-level singleton for this test
        original = eks_module._protector
        eks_module._protector = None
        try:
            a = get_exchange_kill_switch_protector()
            b = get_exchange_kill_switch_protector()
            assert a is b
        finally:
            eks_module._protector = original
