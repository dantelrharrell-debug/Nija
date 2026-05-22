import unittest

from bot.observability_dashboard import MetricCollector


class TestLiveDispatchTriageGateInference(unittest.TestCase):
    def test_classify_gate_reason_tokens(self):
        self.assertEqual(
            MetricCollector._classify_gate_reason("confidence_below_threshold"),
            "signal_confidence_thresholds",
        )
        self.assertEqual(
            MetricCollector._classify_gate_reason("volatility_explosion_long"),
            "adx_volatility_gating",
        )
        self.assertEqual(
            MetricCollector._classify_gate_reason("market_quality_gate:0.12"),
            "orderbook_liquidity_filters",
        )

    def test_infer_signal_gate_from_funnel_aggregate(self):
        signal_payload = {
            "available": True,
            "aggregate": {
                "signals_seen": 10,
                "confidence_pass": 10,
                "adx_pass": 0,
                "volume_pass": 0,
                "ai_gate_pass": 0,
            },
        }
        compiler_payload = {"available": True, "rejection_reasons": {}}
        inferred = MetricCollector._infer_signal_gate_blocker(signal_payload, compiler_payload)
        self.assertEqual(inferred, "adx_volatility_gating")

    def test_infer_signal_gate_prefers_compiler_rejection_reasons(self):
        signal_payload = {"available": True, "aggregate": {}}
        compiler_payload = {
            "available": True,
            "rejection_reasons": {"k_gate:confidence_below_threshold": 3},
        }
        inferred = MetricCollector._infer_signal_gate_blocker(signal_payload, compiler_payload)
        self.assertEqual(inferred, "signal_confidence_thresholds")

    def test_infer_execution_gate_from_trace_rejection_reason(self):
        traces = [
            {
                "status": "rejected",
                "terminal_reason": "cooldown_window_active",
                "stages": {},
            }
        ]
        inferred = MetricCollector._infer_trace_gate_blocker(traces)
        self.assertEqual(inferred, "cooldown_windows")


if __name__ == "__main__":
    unittest.main()
