from __future__ import annotations

from bot.self_learning_strategy_allocator import SelfLearningStrategyAllocator


def test_rl_store_fee_argument_is_accepted_without_double_charging(tmp_path, monkeypatch):
    monkeypatch.setattr(SelfLearningStrategyAllocator, "DATA_DIR", tmp_path)
    monkeypatch.setattr(
        SelfLearningStrategyAllocator,
        "STATE_FILE",
        tmp_path / "allocator.json",
    )

    allocator = SelfLearningStrategyAllocator(
        strategies=["BREAK_RETEST"],
        min_trades_before_learning=1,
    )
    allocator.record_trade(
        "BREAK_RETEST",
        pnl_usd=5.0,
        is_win=True,
        position_size_usd=100.0,
        fees_usd=0.75,
    )

    stats = allocator.get_stats("BREAK_RETEST")
    assert stats["total_trades"] == 1
    assert stats["total_pnl_usd"] == 5.0
    assert stats["trade_history"][-1]["fees_usd"] == 0.75
