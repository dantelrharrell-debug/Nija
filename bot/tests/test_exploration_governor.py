"""
Tests for bot/exploration_governor.py
"""

from __future__ import annotations

import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from bot.exploration_governor import ExplorationCandidate, get_exploration_governor


class ExplorationGovernorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.gov = get_exploration_governor(reset=True)

    def test_asymmetric_damping_tightens_faster_than_it_recovers(self) -> None:
        self.gov.get_confidence_adjustment(
            win_rate_delta=0.12,
            trade_frequency_delta=0.0,
            regime="trending",
        )
        tighten = self.gov.get_confidence_adjustment(
            win_rate_delta=0.12,
            trade_frequency_delta=0.0,
            regime="trending",
        )
        self.assertGreater(tighten, 0.05)

        recover = self.gov.get_confidence_adjustment(
            win_rate_delta=-0.12,
            trade_frequency_delta=0.0,
            regime="trending",
        )
        self.assertGreater(recover, -0.05)
        self.assertGreater(recover, -tighten)

    def test_mode_hysteresis_requires_persistence_before_flip(self) -> None:
        first = self.gov.get_confidence_adjustment(
            win_rate_delta=0.08,
            trade_frequency_delta=0.0,
            regime="trending",
        )
        first_confirmed = self.gov.get_confidence_adjustment(
            win_rate_delta=0.08,
            trade_frequency_delta=0.0,
            regime="trending",
        )
        second = self.gov.get_confidence_adjustment(
            win_rate_delta=-0.08,
            trade_frequency_delta=0.0,
            regime="trending",
        )
        self.assertGreaterEqual(second, 0.0)

        third = self.gov.get_confidence_adjustment(
            win_rate_delta=-0.08,
            trade_frequency_delta=0.0,
            regime="trending",
        )
        self.assertLessEqual(third, second)
        self.assertEqual(first, 0.0)
        self.assertGreater(first_confirmed, 0.0)

    def test_regime_aware_cluster_decay_is_faster_in_high_volatility(self) -> None:
        self.gov.record_outcome(symbol="BTC-USD", regime="volatile", pnl_usd=-100.0, is_win=False)
        self.gov.record_outcome(symbol="ETH-USD", regime="trending", pnl_usd=-100.0, is_win=False)

        vol_key = "volatile|BTC-USD"
        calm_key = "trending|ETH-USD"
        now = time.time()
        self.gov._cluster_buckets[vol_key].last_update_ts = now - 1800.0
        self.gov._cluster_buckets[calm_key].last_update_ts = now - 1800.0

        vol_pressure = self.gov.get_cluster_pressure("BTC-USD", "volatile")
        calm_pressure = self.gov.get_cluster_pressure("ETH-USD", "trending")
        self.assertLess(vol_pressure, calm_pressure)

    def test_near_miss_candidate_stays_shadow_only_when_live_disabled(self) -> None:
        decision = self.gov.evaluate_candidate(
            ExplorationCandidate(
                symbol="SOL-USD",
                regime="trending",
                side="long",
                gate_score=3.2,
                effective_threshold=4.0,
                confidence=0.62,
                volume_ratio=1.1,
            )
        )
        self.assertTrue(decision.shadow_sampled)
        self.assertFalse(decision.allow_live)


if __name__ == "__main__":
    unittest.main()
