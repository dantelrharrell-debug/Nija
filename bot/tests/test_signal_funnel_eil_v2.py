import unittest

from bot.signal_funnel_diagnostics import SignalFunnelDiagnostics


class TestSignalFunnelEILV2(unittest.TestCase):
    def test_quality_prediction_is_included_in_execution_traces(self):
        funnel = SignalFunnelDiagnostics()

        funnel.start_execution_trace(
            pair="BTC-USD",
            side="long",
            reason="test",
            extra={"regime": "strong_trend", "confidence": 0.8, "adx": 24.0},
        )
        funnel.record_execution_stage(
            pair="BTC-USD",
            side="long",
            stage="ai_gate",
            outcome="pass",
            reason="ok",
            extra={"gate_score": 5.0, "confidence": 0.8, "adx": 24.0, "regime": "strong_trend"},
        )
        funnel.record_execution_stage(
            pair="BTC-USD",
            side="long",
            stage="ecel",
            outcome="pass",
            reason="compiled",
            extra={"gate_score": 5.0, "regime": "strong_trend"},
        )

        traces = funnel.get_execution_traces(limit=5)
        self.assertTrue(traces)
        latest = traces[0]
        self.assertIn("quality_prediction", latest)
        self.assertIsNotNone(latest["quality_prediction"])
        self.assertIn("expected_grade", latest["quality_prediction"])


if __name__ == "__main__":
    unittest.main()
