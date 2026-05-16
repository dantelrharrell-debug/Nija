import unittest

from bot.regime_gate_calibrator import RegimeGateCalibrator


class TestRegimeGateCalibrator(unittest.TestCase):
    def test_laplace_probability_and_heatmap(self):
        calibrator = RegimeGateCalibrator()

        # No data: Laplace prior = 0.5
        p0 = calibrator.get_gate_pass_probability("strong_trend", ["signal:pass", "ai_gate:pass"])
        self.assertAlmostEqual(p0, 0.5)

        calibrator.update("strong_trend", ["signal:pass", "ai_gate:pass"], True)
        calibrator.update("strong_trend", ["signal:pass", "ai_gate:pass"], False)
        calibrator.update("strong_trend", ["signal:pass", "ai_gate:pass"], True)

        p = calibrator.get_gate_pass_probability("strong_trend", ["signal:pass", "ai_gate:pass"])
        # (passes + 1) / (total + 2) => (2 + 1)/(3 + 2) = 0.6
        self.assertAlmostEqual(p, 0.6)

        heatmap = calibrator.get_regime_heatmap()
        self.assertIn("strong_trend", heatmap)
        self.assertTrue(any(key.startswith("signal:pass") for key in heatmap["strong_trend"].keys()))


if __name__ == "__main__":
    unittest.main()
