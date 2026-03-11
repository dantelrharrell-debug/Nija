"""
Tests for bot/strategy_allocation_engine.py
"""

from __future__ import annotations

import sys
import math
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from bot.strategy_allocation_engine import (
    StrategyAllocationEngine,
    StrategyRecord,
    ShiftOrder,
    MIN_ALLOCATION,
    MAX_ALLOCATION,
    DEFAULT_EMA_DECAY,
    MIN_TRADES_BEFORE_LEARNING,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def engine(tmp_path):
    """Fresh engine (no state file, no singleton) with $100,000 capital."""
    return StrategyAllocationEngine(
        strategies=["Alpha", "Beta", "Gamma"],
        total_capital=100_000.0,
        state_file=tmp_path / "engine_state.json",
    )


@pytest.fixture
def engine_no_capital(tmp_path):
    """Fresh engine without pre-set capital."""
    return StrategyAllocationEngine(
        strategies=["Alpha", "Beta", "Gamma"],
        total_capital=0.0,
        state_file=tmp_path / "engine_state_nocap.json",
    )


def _fill_trades(engine: StrategyAllocationEngine, strategy: str,
                 n_wins: int, n_losses: int,
                 win_pnl: float = 50.0, loss_pnl: float = -20.0,
                 position_size: float = 100.0) -> None:
    """Helper: record a series of wins then losses for a strategy."""
    for _ in range(n_wins):
        engine.record_trade(strategy, pnl_usd=win_pnl, is_win=True,
                            position_size_usd=position_size)
    for _ in range(n_losses):
        engine.record_trade(strategy, pnl_usd=loss_pnl, is_win=False,
                            position_size_usd=position_size)


# ---------------------------------------------------------------------------
# Initialisation
# ---------------------------------------------------------------------------

class TestInit:
    def test_strategies_registered(self, engine):
        allocs = engine.get_allocations()
        assert set(allocs.keys()) == {"Alpha", "Beta", "Gamma"}

    def test_total_capital_set(self, engine):
        assert engine.total_capital == 100_000.0

    def test_allocations_sum_to_capital(self, engine):
        total = sum(engine.get_allocations().values())
        assert abs(total - 100_000.0) < 0.01

    def test_equal_weight_before_learning(self, engine):
        allocs = engine.get_allocations()
        for v in allocs.values():
            assert abs(v - 100_000.0 / 3) < 1.0

    def test_ema_decay_clamped_low(self, tmp_path):
        e = StrategyAllocationEngine(strategies=["A"], total_capital=1000.0,
                                     ema_decay=0.01,
                                     state_file=tmp_path / "s.json")
        assert e.ema_decay >= 0.1

    def test_ema_decay_clamped_high(self, tmp_path):
        e = StrategyAllocationEngine(strategies=["A"], total_capital=1000.0,
                                     ema_decay=1.5,
                                     state_file=tmp_path / "s.json")
        assert e.ema_decay <= 0.99

    def test_default_strategies_used_when_none_provided(self, tmp_path):
        e = StrategyAllocationEngine(state_file=tmp_path / "s.json")
        names = set(e.get_allocations().keys())
        assert "ApexTrend" in names

    def test_zero_capital_gives_zero_usd_allocations(self, engine_no_capital):
        allocs = engine_no_capital.get_allocations()
        assert all(v == 0.0 for v in allocs.values())


# ---------------------------------------------------------------------------
# update_capital
# ---------------------------------------------------------------------------

class TestUpdateCapital:
    def test_capital_updated(self, engine):
        engine.update_capital(200_000.0)
        assert engine.total_capital == 200_000.0

    def test_allocations_rescale(self, engine):
        engine.update_capital(50_000.0)
        total = sum(engine.get_allocations().values())
        assert abs(total - 50_000.0) < 0.01

    def test_weights_preserved_after_capital_change(self, engine):
        # Record enough trades so Alpha dominates
        _fill_trades(engine, "Alpha", 20, 2)
        _fill_trades(engine, "Beta", 5, 15)
        _fill_trades(engine, "Gamma", 5, 15)

        w_before = engine.get_weights()
        engine.update_capital(200_000.0)
        w_after = engine.get_weights()

        for name in ("Alpha", "Beta", "Gamma"):
            assert abs(w_before[name] - w_after[name]) < 1e-6


# ---------------------------------------------------------------------------
# record_trade
# ---------------------------------------------------------------------------

class TestRecordTrade:
    def test_total_trades_incremented(self, engine):
        engine.record_trade("Alpha", pnl_usd=50.0, is_win=True)
        stats = engine.get_stats("Alpha")
        assert stats["total_trades"] == 1

    def test_winning_trades_incremented(self, engine):
        engine.record_trade("Alpha", pnl_usd=50.0, is_win=True)
        stats = engine.get_stats("Alpha")
        assert stats["winning_trades"] == 1

    def test_losing_trade_not_counted_as_win(self, engine):
        engine.record_trade("Alpha", pnl_usd=-20.0, is_win=False)
        stats = engine.get_stats("Alpha")
        assert stats["winning_trades"] == 0

    def test_pnl_accumulated(self, engine):
        engine.record_trade("Alpha", pnl_usd=50.0, is_win=True)
        engine.record_trade("Alpha", pnl_usd=-20.0, is_win=False)
        stats = engine.get_stats("Alpha")
        assert abs(stats["total_pnl_usd"] - 30.0) < 1e-9

    def test_ema_return_non_zero_after_win(self, engine):
        engine.record_trade("Alpha", pnl_usd=50.0, is_win=True,
                            position_size_usd=100.0)
        stats = engine.get_stats("Alpha")
        assert stats["ema_return"] > 0.0

    def test_ema_return_negative_after_loss(self, engine):
        engine.record_trade("Alpha", pnl_usd=-50.0, is_win=False,
                            position_size_usd=100.0)
        stats = engine.get_stats("Alpha")
        assert stats["ema_return"] < 0.0

    def test_unknown_strategy_auto_registered(self, engine):
        engine.record_trade("NewStrat", pnl_usd=10.0, is_win=True)
        assert "NewStrat" in engine.get_allocations()

    def test_gross_profit_tracked(self, engine):
        engine.record_trade("Beta", pnl_usd=80.0, is_win=True)
        stats = engine.get_stats("Beta")
        assert abs(stats["gross_profit"] - 80.0) < 1e-9

    def test_gross_loss_tracked(self, engine):
        engine.record_trade("Beta", pnl_usd=-30.0, is_win=False)
        stats = engine.get_stats("Beta")
        assert abs(stats["gross_loss"] - 30.0) < 1e-9


# ---------------------------------------------------------------------------
# rebalance – weights and USD amounts
# ---------------------------------------------------------------------------

class TestRebalance:
    def test_returns_dict_with_all_strategies(self, engine):
        result = engine.rebalance()
        assert set(result.keys()) == {"Alpha", "Beta", "Gamma"}

    def test_allocations_sum_to_capital_after_rebalance(self, engine):
        _fill_trades(engine, "Alpha", 15, 3)
        result = engine.rebalance()
        assert abs(sum(result.values()) - 100_000.0) < 0.01

    def test_best_performer_gets_most_capital(self, engine):
        _fill_trades(engine, "Alpha", 20, 2)   # strong performer
        _fill_trades(engine, "Beta", 5, 15)    # poor performer
        _fill_trades(engine, "Gamma", 8, 12)   # mediocre

        result = engine.rebalance()
        assert result["Alpha"] > result["Beta"]
        assert result["Alpha"] > result["Gamma"]

    def test_worst_performer_gets_floor_allocation(self, engine):
        _fill_trades(engine, "Alpha", 20, 2)
        _fill_trades(engine, "Beta", 2, 20)
        _fill_trades(engine, "Gamma", 10, 10)

        result = engine.rebalance()
        min_usd = 100_000.0 * MIN_ALLOCATION
        assert result["Beta"] >= min_usd * 0.99  # tolerance for rounding

    def test_best_performer_capped_at_max_allocation(self, engine):
        # Simulate an extremely dominant strategy
        _fill_trades(engine, "Alpha", 30, 0, win_pnl=100.0)
        _fill_trades(engine, "Beta", 0, 30, loss_pnl=-10.0)
        _fill_trades(engine, "Gamma", 0, 30, loss_pnl=-10.0)

        result = engine.rebalance()
        max_usd = 100_000.0 * MAX_ALLOCATION
        assert result["Alpha"] <= max_usd * 1.001  # tolerance

    def test_no_capital_set_returns_zeros(self, engine_no_capital):
        result = engine_no_capital.rebalance()
        assert all(v == 0.0 for v in result.values())


# ---------------------------------------------------------------------------
# get_shift_plan
# ---------------------------------------------------------------------------

class TestGetShiftPlan:
    def test_no_shifts_when_current_not_provided(self, engine):
        plan = engine.get_shift_plan()
        assert plan == []

    def test_shift_plan_from_equal_to_performance_weighted(self, engine):
        _fill_trades(engine, "Alpha", 20, 2)
        _fill_trades(engine, "Beta", 2, 20)
        _fill_trades(engine, "Gamma", 10, 10)
        engine.rebalance()

        equal = {s: 100_000.0 / 3 for s in ["Alpha", "Beta", "Gamma"]}
        plan = engine.get_shift_plan(current_usd=equal)

        # Capital should flow toward Alpha (best performer)
        assert any(s.to_strategy == "Alpha" for s in plan)
        # Capital should leave Beta (worst performer)
        assert any(s.from_strategy == "Beta" for s in plan)

    def test_shift_orders_are_shift_order_instances(self, engine):
        _fill_trades(engine, "Alpha", 20, 2)
        _fill_trades(engine, "Beta", 2, 20)
        _fill_trades(engine, "Gamma", 10, 10)
        engine.rebalance()
        equal = {s: 100_000.0 / 3 for s in ["Alpha", "Beta", "Gamma"]}
        plan = engine.get_shift_plan(current_usd=equal)
        for item in plan:
            assert isinstance(item, ShiftOrder)

    def test_shift_amounts_positive(self, engine):
        _fill_trades(engine, "Alpha", 20, 2)
        _fill_trades(engine, "Beta", 2, 20)
        _fill_trades(engine, "Gamma", 10, 10)
        engine.rebalance()
        equal = {s: 100_000.0 / 3 for s in ["Alpha", "Beta", "Gamma"]}
        plan = engine.get_shift_plan(current_usd=equal)
        for item in plan:
            assert item.amount_usd > 0

    def test_shift_plan_sorted_descending(self, engine):
        _fill_trades(engine, "Alpha", 20, 2)
        _fill_trades(engine, "Beta", 2, 20)
        _fill_trades(engine, "Gamma", 10, 10)
        engine.rebalance()
        equal = {s: 100_000.0 / 3 for s in ["Alpha", "Beta", "Gamma"]}
        plan = engine.get_shift_plan(current_usd=equal)
        amounts = [s.amount_usd for s in plan]
        assert amounts == sorted(amounts, reverse=True)

    def test_no_shifts_when_already_at_target(self, engine):
        engine.rebalance()
        # Use exact current allocations as "current"
        current = engine.get_allocations()
        plan = engine.get_shift_plan(current_usd=current)
        assert plan == []


# ---------------------------------------------------------------------------
# get_allocation / get_allocations
# ---------------------------------------------------------------------------

class TestGetAllocation:
    def test_get_allocation_known_strategy(self, engine):
        val = engine.get_allocation("Alpha")
        assert val > 0.0

    def test_get_allocation_unknown_strategy(self, engine):
        val = engine.get_allocation("NonExistent")
        assert val == 0.0

    def test_get_allocations_all_strategies(self, engine):
        allocs = engine.get_allocations()
        assert "Alpha" in allocs
        assert "Beta" in allocs
        assert "Gamma" in allocs


# ---------------------------------------------------------------------------
# get_weights
# ---------------------------------------------------------------------------

class TestGetWeights:
    def test_weights_sum_to_one(self, engine):
        weights = engine.get_weights()
        assert abs(sum(weights.values()) - 1.0) < 1e-6

    def test_weights_sum_to_one_after_learning(self, engine):
        _fill_trades(engine, "Alpha", 20, 2)
        _fill_trades(engine, "Beta", 2, 20)
        engine.rebalance()
        weights = engine.get_weights()
        assert abs(sum(weights.values()) - 1.0) < 1e-6

    def test_weights_all_positive(self, engine):
        weights = engine.get_weights()
        assert all(w > 0.0 for w in weights.values())

    def test_best_strategy_has_highest_weight(self, engine):
        _fill_trades(engine, "Alpha", 20, 2)
        _fill_trades(engine, "Beta", 2, 20)
        _fill_trades(engine, "Gamma", 5, 15)
        engine.rebalance()
        weights = engine.get_weights()
        assert weights["Alpha"] == max(weights.values())


# ---------------------------------------------------------------------------
# get_best_strategy
# ---------------------------------------------------------------------------

class TestGetBestStrategy:
    def test_returns_string(self, engine):
        result = engine.get_best_strategy()
        assert isinstance(result, str)

    def test_returns_highest_allocated_strategy(self, engine):
        _fill_trades(engine, "Alpha", 20, 2)
        _fill_trades(engine, "Beta", 2, 20)
        _fill_trades(engine, "Gamma", 5, 15)
        engine.rebalance()
        best = engine.get_best_strategy()
        allocs = engine.get_allocations()
        assert allocs[best] == max(allocs.values())

    def test_none_on_empty_engine(self, tmp_path):
        e = StrategyAllocationEngine(strategies=[], state_file=tmp_path / "s.json")
        assert e.get_best_strategy() is None


# ---------------------------------------------------------------------------
# get_stats
# ---------------------------------------------------------------------------

class TestGetStats:
    def test_single_strategy_stats(self, engine):
        engine.record_trade("Alpha", pnl_usd=50.0, is_win=True)
        stats = engine.get_stats("Alpha")
        assert "total_trades" in stats
        assert "win_rate" in stats
        assert "profit_factor" in stats
        assert "ema_return" in stats

    def test_all_stats(self, engine):
        engine.record_trade("Alpha", pnl_usd=50.0, is_win=True)
        all_stats = engine.get_stats()
        assert "Alpha" in all_stats
        assert "Beta" in all_stats

    def test_unknown_strategy_returns_empty(self, engine):
        stats = engine.get_stats("DoesNotExist")
        assert stats == {}


# ---------------------------------------------------------------------------
# add_strategy
# ---------------------------------------------------------------------------


class TestAddStrategy:
    def test_new_strategy_added(self, engine):
        engine.add_strategy("Delta")
        allocs = engine.get_allocations()
        assert "Delta" in allocs

    def test_duplicate_add_is_safe(self, engine):
        engine.add_strategy("Alpha")  # already exists
        allocs = engine.get_allocations()
        # Should still only have one entry for Alpha
        assert list(allocs.keys()).count("Alpha") == 1

    def test_allocations_still_sum_to_capital(self, engine):
        engine.add_strategy("Delta")
        total = sum(engine.get_allocations().values())
        assert abs(total - 100_000.0) < 0.01


# ---------------------------------------------------------------------------
# get_report
# ---------------------------------------------------------------------------

class TestGetReport:
    def test_report_is_string(self, engine):
        report = engine.get_report()
        assert isinstance(report, str)

    def test_report_contains_strategy_names(self, engine):
        report = engine.get_report()
        assert "Alpha" in report
        assert "Beta" in report

    def test_report_contains_capital_header(self, engine):
        report = engine.get_report()
        assert "100,000" in report


# ---------------------------------------------------------------------------
# StrategyRecord computed properties
# ---------------------------------------------------------------------------

class TestStrategyRecord:
    def test_win_rate_zero_with_no_trades(self):
        rec = StrategyRecord(name="Test")
        assert rec.win_rate == 0.0

    def test_win_rate_calculated(self):
        rec = StrategyRecord(name="Test", total_trades=10, winning_trades=7)
        assert abs(rec.win_rate - 0.7) < 1e-9

    def test_profit_factor_zero_no_trades(self):
        rec = StrategyRecord(name="Test")
        assert rec.profit_factor == 0.0

    def test_profit_factor_no_loss(self):
        rec = StrategyRecord(name="Test", gross_profit=100.0, gross_loss=0.0)
        assert rec.profit_factor == 999.99

    def test_profit_factor_calculated(self):
        rec = StrategyRecord(name="Test", gross_profit=200.0, gross_loss=100.0)
        assert abs(rec.profit_factor - 2.0) < 1e-6

    def test_avg_pnl_no_trades(self):
        rec = StrategyRecord(name="Test")
        assert rec.avg_pnl == 0.0

    def test_avg_pnl_calculated(self):
        rec = StrategyRecord(name="Test", total_trades=4, total_pnl_usd=200.0)
        assert abs(rec.avg_pnl - 50.0) < 1e-9

    def test_sharpe_estimate_no_returns(self):
        rec = StrategyRecord(name="Test")
        assert rec.sharpe_estimate == 0.0

    def test_sharpe_estimate_positive_with_wins(self):
        rec = StrategyRecord(name="Test",
                             _recent_returns=[0.3, 0.4, 0.2, 0.5, 0.3])
        assert rec.sharpe_estimate > 0.0

    def test_to_dict_contains_computed_fields(self):
        rec = StrategyRecord(name="Test", total_trades=10, winning_trades=7,
                             gross_profit=500.0, gross_loss=100.0)
        d = rec.to_dict()
        assert "win_rate" in d
        assert "profit_factor" in d
        assert "avg_pnl" in d
        assert "sharpe_estimate" in d


# ---------------------------------------------------------------------------
# ShiftOrder
# ---------------------------------------------------------------------------

class TestShiftOrder:
    def test_to_dict(self):
        so = ShiftOrder(from_strategy="A", to_strategy="B", amount_usd=500.0,
                        reason="test")
        d = so.to_dict()
        assert d["from_strategy"] == "A"
        assert d["to_strategy"] == "B"
        assert d["amount_usd"] == 500.0
        assert d["reason"] == "test"

    def test_default_reason_empty(self):
        so = ShiftOrder(from_strategy="A", to_strategy="B", amount_usd=100.0)
        assert so.reason == ""


# ---------------------------------------------------------------------------
# Thread safety (basic smoke-test)
# ---------------------------------------------------------------------------

class TestThreadSafety:
    def test_concurrent_record_trades(self, engine):
        import threading

        errors = []

        def worker(strategy: str, n: int) -> None:
            try:
                for i in range(n):
                    pnl = 50.0 if i % 2 == 0 else -20.0
                    engine.record_trade(strategy, pnl_usd=pnl, is_win=(pnl > 0))
            except Exception as exc:
                errors.append(exc)

        threads = [
            threading.Thread(target=worker, args=("Alpha", 20)),
            threading.Thread(target=worker, args=("Beta", 20)),
            threading.Thread(target=worker, args=("Gamma", 20)),
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert errors == [], f"Errors during concurrent access: {errors}"
        total = sum(engine.get_allocations().values())
        assert abs(total - 100_000.0) < 0.01
