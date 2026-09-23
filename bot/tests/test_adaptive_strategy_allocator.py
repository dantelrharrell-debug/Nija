from __future__ import annotations

from dataclasses import dataclass

import pytest

from bot.adaptive_strategy_allocator import AdaptiveStrategyAllocator


class FakeCalibrator:
    def __init__(self, reports):
        self.reports = reports

    def get_recommendation(self, regime, strategy):
        return dict(self.reports.get((str(regime), str(strategy)), {
            "sample_size": 0,
            "reliability": 0.0,
            "expectancy": 0.0,
            "profit_factor": 0.0,
            "win_rate": 0.0,
            "calibration_score": 0.0,
            "freeze_recommended": False,
            "eligible_for_review": False,
        }))


@dataclass
class Candidate:
    strategy: str
    market_regime: str
    direction: str


def _report(score, samples=40, freeze=False):
    return {
        "sample_size": samples,
        "reliability": 0.67,
        "expectancy": 0.01 if score > 0 else -0.01,
        "profit_factor": 1.4 if score > 0 else 0.7,
        "win_rate": 0.58 if score > 0 else 0.42,
        "calibration_score": score,
        "freeze_recommended": freeze,
        "eligible_for_review": samples >= 20,
    }


def test_shadow_mode_observes_but_does_not_change_selection(monkeypatch):
    monkeypatch.setenv("NIJA_ADAPTIVE_STRATEGY_MODE", "shadow")
    monkeypatch.setenv("NIJA_ADAPTIVE_STRATEGY_APPROVED", "true")
    allocator = AdaptiveStrategyAllocator()
    allocator._calibrator = FakeCalibrator({
        ("trending", "BREAK_RETEST"): _report(0.8),
    })

    detail = allocator.evaluate(
        strategy="BREAK_RETEST",
        regime="trending",
        direction="long",
        base_score=0.60,
        same_direction_confirmations=2,
    )

    assert detail.active is False
    assert detail.adaptive_score > detail.base_score
    assert detail.selection_score == pytest.approx(0.60)


def test_active_mode_requires_double_gate(monkeypatch):
    monkeypatch.setenv("NIJA_ADAPTIVE_STRATEGY_MODE", "active")
    monkeypatch.setenv("NIJA_ADAPTIVE_STRATEGY_APPROVED", "false")
    allocator = AdaptiveStrategyAllocator()
    assert allocator.active is False

    monkeypatch.setenv("NIJA_ADAPTIVE_STRATEGY_APPROVED", "true")
    allocator = AdaptiveStrategyAllocator()
    assert allocator.active is True


def test_cold_start_does_not_learn_from_tiny_sample(monkeypatch):
    monkeypatch.setenv("NIJA_ADAPTIVE_STRATEGY_MODE", "active")
    monkeypatch.setenv("NIJA_ADAPTIVE_STRATEGY_APPROVED", "true")
    monkeypatch.setenv("NIJA_ADAPTIVE_STRATEGY_MIN_SAMPLES", "20")
    allocator = AdaptiveStrategyAllocator()
    allocator._calibrator = FakeCalibrator({
        ("volatile", "LIQUIDITY_FVG_RETRACE"): _report(1.0, samples=5),
    })

    detail = allocator.evaluate(
        strategy="LIQUIDITY_FVG_RETRACE",
        regime="volatile",
        direction="short",
        base_score=0.55,
        same_direction_confirmations=1,
    )

    assert detail.eligible_for_learning is False
    assert detail.performance_adjustment == pytest.approx(0.0)
    assert detail.selection_score == pytest.approx(0.55)


def test_freeze_recommendation_can_only_reduce_rank(monkeypatch):
    monkeypatch.setenv("NIJA_ADAPTIVE_STRATEGY_MODE", "active")
    monkeypatch.setenv("NIJA_ADAPTIVE_STRATEGY_APPROVED", "true")
    allocator = AdaptiveStrategyAllocator()
    allocator._calibrator = FakeCalibrator({
        ("ranging", "MEAN_REVERSION"): _report(0.9, samples=80, freeze=True),
    })

    detail = allocator.evaluate(
        strategy="MEAN_REVERSION",
        regime="ranging",
        direction="long",
        base_score=0.70,
        same_direction_confirmations=1,
    )

    assert detail.freeze_recommended is True
    assert detail.performance_adjustment <= 0.0
    assert detail.selection_score < detail.base_score


def test_active_rank_can_select_better_regime_strategy(monkeypatch):
    monkeypatch.setenv("NIJA_ADAPTIVE_STRATEGY_MODE", "active")
    monkeypatch.setenv("NIJA_ADAPTIVE_STRATEGY_APPROVED", "true")
    allocator = AdaptiveStrategyAllocator()
    allocator._calibrator = FakeCalibrator({
        ("trending", "BREAK_RETEST"): _report(0.9, samples=60),
        ("trending", "FIRST_CANDLE_ORB"): _report(-0.8, samples=60),
    })

    rows = [
        (Candidate("FIRST_CANDLE_ORB", "trending", "long"), 0.72),
        (Candidate("BREAK_RETEST", "trending", "long"), 0.68),
    ]
    ranked = allocator.rank(rows)

    assert ranked[0][0].strategy == "BREAK_RETEST"
    assert ranked[0][2].active is True
    assert ranked[0][2].adaptive_score > ranked[1][2].adaptive_score


def test_confluence_bonus_is_bounded(monkeypatch):
    monkeypatch.setenv("NIJA_ADAPTIVE_STRATEGY_MODE", "active")
    monkeypatch.setenv("NIJA_ADAPTIVE_STRATEGY_APPROVED", "true")
    monkeypatch.setenv("NIJA_ADAPTIVE_STRATEGY_MAX_CONFLUENCE", "0.06")
    allocator = AdaptiveStrategyAllocator()
    allocator._calibrator = FakeCalibrator({})

    detail = allocator.evaluate(
        strategy="BREAK_RETEST",
        regime="trending",
        direction="long",
        base_score=0.50,
        same_direction_confirmations=20,
    )

    assert detail.confluence_bonus == pytest.approx(0.06)
    assert 0.0 <= detail.selection_score <= 1.0
