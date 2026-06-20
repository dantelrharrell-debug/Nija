"""Regression coverage for master-router bootstrap recursion."""

from __future__ import annotations

import inspect

from bot.master_strategy_router import MasterStrategyRouter


def test_master_router_apex_loader_does_not_instantiate_trading_strategy():
    """The router must not recursively construct TradingStrategy while locked."""
    source = inspect.getsource(MasterStrategyRouter._load_apex)

    assert '("bot.trading_strategy", "TradingStrategy")' not in source
    assert '("bot.nija_apex_strategy_v71", "NIJAApexStrategyV71")' in source


def test_trading_strategy_construction_does_not_deadlock():
    """Constructing TradingStrategy should return and wire the master router once."""
    from bot.trading_strategy import TradingStrategy

    strategy = TradingStrategy()

    assert strategy is not None
    if strategy.independent_trader is not None:
        assert strategy.independent_trader.master_router is not None
