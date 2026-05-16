import unittest

from bot.failure_cluster_engine import FailureClusterEngine


class TestFailureClusterEngine(unittest.TestCase):
    def test_clusters_rejections_by_path_and_regime(self):
        engine = FailureClusterEngine()

        base_trace = {
            "status": "rejected",
            "terminal_reason": "ecel_min_notional",
            "regime": "strong_trend",
            "events": [
                {"stage": "signal", "outcome": "pass"},
                {"stage": "ai_gate", "outcome": "pass"},
                {"stage": "ecel", "outcome": "rejected"},
            ],
            "confidence": 0.72,
            "adx": 28.0,
        }

        engine.ingest_terminal_trace(dict(base_trace, trace_id="t1"))
        engine.ingest_terminal_trace(dict(base_trace, trace_id="t2"))

        patterns = engine.get_top_failure_patterns(limit=5)
        self.assertGreaterEqual(len(patterns), 1)
        top = patterns[0]
        self.assertEqual(top["regime"], "strong_trend")
        self.assertEqual(top["sample_count"], 2)
        self.assertEqual(top["rejection_rate"], 1.0)


if __name__ == "__main__":
    unittest.main()
