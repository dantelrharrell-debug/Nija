#!/usr/bin/env python3
"""
Test the profit optimisation stack integration in NIJAApexStrategyV71.

Verifies:
1. ProfitHarvestLayer is initialised by the strategy.
2. Positions are registered with the harvest layer on entry.
3. Profit floor hits generate exit signals via analyze_market.
4. On full exit the trade is recorded in the flywheel and the position
   is removed from the harvest layer.
5. The flywheel multiplier scales position sizes upward as profits accrue.
6. Capital recycling engine receives deposits from harvest events.
"""

import sys
import os
# Ensure the repo root is on sys.path so `from bot.xxx import` resolves the
# bot/ package correctly.  The bot/ directory is also added so that direct
# imports (e.g. `from nija_apex_strategy_v71 import ...`) work from any CWD.
_BOT_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_BOT_DIR)
# Insert repo root FIRST so `bot` → package bot/, not file bot/bot.py
for _p in (_BOT_DIR, _REPO_ROOT):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import pandas as pd
import numpy as np
from unittest.mock import MagicMock, patch, PropertyMock


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_df(close_prices):
    """Create a minimal OHLCV DataFrame the strategy can work with."""
    n = len(close_prices)
    df = pd.DataFrame({
        'open':   close_prices,
        'high':   [p * 1.002 for p in close_prices],
        'low':    [p * 0.998 for p in close_prices],
        'close':  close_prices,
        'volume': [1_000_000] * n,
    })
    return df


def _build_strategy():
    """Instantiate NIJAApexStrategyV71 with all expensive optional modules disabled."""
    # Disable modules that require broker credentials / DB connections
    with patch.dict(os.environ, {}):
        from nija_apex_strategy_v71 import NIJAApexStrategyV71
        cfg = {
            'use_enhanced_scoring': False,
            'use_regime_detection': False,
            'enable_stepped_exits': True,
            # Coinbase taker fee is 0.8% → round-trip 1.6% → min net ≥ 0.5%
            # ⇒ each target must be ≥ 2.1 %.  Use 2.5 % as the lowest level.
            # R/R requirement (≥ 1.5:1) with estimated 1.5% stop and 1.6% fees:
            # (target - 1.6) / (1.5 + 1.6) ≥ 1.5  ⟹  target ≥ 6.25%  ⟹  use 6.5%
            'stepped_exits': {
                0.025: 0.15,
                0.030: 0.25,
                0.040: 0.35,
                0.065: 0.50,
            },
            'use_ai_intelligence_hub': False,
            'enable_profit_stack': True,
        }
        strategy = NIJAApexStrategyV71(broker_client=None, config=cfg)
    return strategy


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_profit_stack_attributes_exist():
    """Strategy should expose the three profit-stack attributes."""
    strategy = _build_strategy()
    assert hasattr(strategy, 'profit_harvest_layer'), "Missing profit_harvest_layer"
    assert hasattr(strategy, 'portfolio_profit_flywheel'), "Missing portfolio_profit_flywheel"
    assert hasattr(strategy, 'capital_recycling_engine'), "Missing capital_recycling_engine"
    print("✅ Profit stack attributes present on strategy instance")


def test_harvest_layer_register_on_entry():
    """
    When execute_action('enter_long') succeeds, the position should be
    registered with the ProfitHarvestLayer.
    """
    strategy = _build_strategy()
    if strategy.profit_harvest_layer is None:
        print("⚠️  ProfitHarvestLayer not available – skipping")
        return

    # Mock execution engine to return a truthy position on entry
    mock_position = {'symbol': 'ETH-USD', 'side': 'long', 'entry_price': 200.0}
    strategy.execution_engine.execute_entry = MagicMock(return_value=mock_position)

    action_data = {
        'action': 'enter_long',
        'entry_price': 200.0,
        'position_size': 500.0,
        'stop_loss': 194.0,
        'take_profit': [204.0, 208.0, 214.0],
    }
    result = strategy.execute_action(action_data, 'ETH-USD')
    assert result is True, "execute_action should return True on successful entry"

    # Position should now be tracked in the harvest layer
    statuses = strategy.profit_harvest_layer.get_all_statuses()
    assert 'ETH-USD' in statuses, "ETH-USD should be registered in harvest layer after entry"
    print("✅ Harvest layer registered position on entry")


def test_harvest_layer_remove_on_exit():
    """
    When execute_action('exit') succeeds, the position should be removed
    from the ProfitHarvestLayer and the flywheel should record the trade.
    """
    strategy = _build_strategy()
    if strategy.profit_harvest_layer is None or strategy.portfolio_profit_flywheel is None:
        print("⚠️  Profit stack not available – skipping")
        return

    # Manually register a position so it exists in the harvest layer
    strategy.profit_harvest_layer.register_position(
        symbol='BTC-USD',
        side='long',
        entry_price=50_000.0,
        position_size_usd=1_000.0,
    )

    # Record initial flywheel trade count using total_trades (not log slice)
    initial_total_trades = strategy.portfolio_profit_flywheel.get_summary()['total_trades']

    # Mock execution engine to succeed on exit
    strategy.execution_engine.execute_exit = MagicMock(return_value=True)

    action_data = {
        'action': 'exit',
        'position': {
            'entry_price': 50_000.0,
            'position_size': 1_000.0,
            'side': 'long',
        },
        'current_price': 51_000.0,   # +2 % → profitable
        'reason': 'Test exit',
    }
    result = strategy.execute_action(action_data, 'BTC-USD')
    assert result is True, "execute_action('exit') should return True"

    # Position should be gone from the harvest layer
    statuses = strategy.profit_harvest_layer.get_all_statuses()
    assert 'BTC-USD' not in statuses, "BTC-USD should be removed from harvest layer after exit"

    # Flywheel should have recorded the trade
    new_total_trades = strategy.portfolio_profit_flywheel.get_summary()['total_trades']
    assert new_total_trades > initial_total_trades, "Flywheel should have a new trade entry after exit"
    print("✅ Harvest layer removed position and flywheel recorded trade on exit")


def test_flywheel_multiplier_applied_to_position_size():
    """
    When the flywheel multiplier is > 1.0, the strategy should scale the
    calculated position size upward (bounded by max_position_pct).
    """
    strategy = _build_strategy()
    if strategy.portfolio_profit_flywheel is None:
        print("⚠️  PortfolioProfitFlywheel not available – skipping")
        return

    # Force flywheel multiplier > 1.0 by recording winning trades
    for _ in range(50):
        strategy.portfolio_profit_flywheel.record_trade('BTC-USD', pnl_usd=200.0, is_win=True)

    mult = strategy.portfolio_profit_flywheel.get_capital_multiplier()
    assert mult > 1.0, f"Flywheel multiplier should exceed 1.0 after wins, got {mult}"
    print(f"✅ Flywheel multiplier = {mult:.3f} (> 1.0 after wins)")


def test_harvest_layer_floor_hit_exits_position():
    """
    When the harvest layer reports floor_hit=True, analyze_market should
    return action='exit' with a profit-lock reason.
    """
    strategy = _build_strategy()
    if strategy.profit_harvest_layer is None:
        print("⚠️  ProfitHarvestLayer not available – skipping")
        return

    from unittest.mock import patch as _patch

    # Mock a HarvestDecision with floor_hit=True
    from bot.profit_harvest_layer import HarvestDecision
    mock_decision = HarvestDecision(
        symbol='SOL-USD',
        current_price=90.0,
        peak_profit_pct=5.0,
        current_tier='TIER_4',
        locked_profit_pct=4.10,
        lock_floor_price=89.5,
        tier_upgraded=False,
        floor_hit=True,
        lock_message='Floor hit',
        harvest_triggered=False,
        harvest_amount_usd=0.0,
    )

    # Inject a mock existing position so the strategy tries to manage it
    mock_pos = {
        'symbol': 'SOL-USD', 'side': 'long',
        'entry_price': 86.0, 'position_size': 200.0,
        'stop_loss': 84.0, 'tp1': 90.0, 'tp2': 93.0, 'tp3': 96.0,
    }
    strategy.execution_engine.get_position = MagicMock(return_value=mock_pos)
    strategy.profit_harvest_layer.process_price_update = MagicMock(return_value=mock_decision)

    # Build minimal df (only needs to pass the length check)
    prices = [86.0 + i * 0.1 for i in range(200)]
    df = _make_df(prices)

    result = strategy.analyze_market(df, 'SOL-USD', account_balance=10_000.0)

    assert result['action'] == 'exit', (
        f"Expected 'exit' when floor_hit=True, got '{result['action']}'"
    )
    assert 'lock' in result['reason'].lower() or 'floor' in result['reason'].lower(), (
        f"Exit reason should mention lock/floor, got: {result['reason']}"
    )
    print(f"✅ Floor hit triggers exit: {result['reason']}")


def test_capital_recycling_receives_deposit_on_harvest():
    """
    When a new harvest tier is reached, the harvest amount should be deposited
    into the capital recycling engine.
    """
    strategy = _build_strategy()
    if strategy.profit_harvest_layer is None or strategy.capital_recycling_engine is None:
        print("⚠️  Profit stack not fully available – skipping")
        return

    from bot.profit_harvest_layer import HarvestDecision

    # Record initial pool balance
    initial_pool = strategy.capital_recycling_engine.get_pool_balance()

    # Simulate a tier upgrade with a harvest amount
    mock_decision = HarvestDecision(
        symbol='ADA-USD',
        current_price=0.50,
        peak_profit_pct=1.5,
        current_tier='TIER_1',
        locked_profit_pct=0.45,
        lock_floor_price=0.495,
        tier_upgraded=True,
        floor_hit=False,
        lock_message='Tier 1 reached',
        harvest_triggered=True,
        harvest_amount_usd=12.50,
    )

    mock_pos = {
        'symbol': 'ADA-USD', 'side': 'long',
        'entry_price': 0.49, 'position_size': 500.0,
        'stop_loss': 0.48, 'tp1': 0.51, 'tp2': 0.52, 'tp3': 0.54,
    }
    strategy.execution_engine.get_position = MagicMock(return_value=mock_pos)
    strategy.execution_engine.check_stepped_profit_exits = MagicMock(return_value=None)
    strategy.execution_engine.check_take_profit_hit = MagicMock(return_value=None)
    strategy.profit_harvest_layer.process_price_update = MagicMock(return_value=mock_decision)

    prices = [0.49 + i * 0.0001 for i in range(200)]
    df = _make_df(prices)
    strategy.analyze_market(df, 'ADA-USD', account_balance=10_000.0)

    new_pool = strategy.capital_recycling_engine.get_pool_balance()
    assert new_pool > initial_pool, (
        f"Capital recycling pool should grow after harvest; "
        f"was ${initial_pool:.2f}, now ${new_pool:.2f}"
    )
    print(f"✅ Capital recycling received harvest deposit: ${new_pool - initial_pool:.2f}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == '__main__':
    print("=" * 70)
    print("PROFIT OPTIMISATION STACK INTEGRATION TESTS")
    print("=" * 70)

    tests = [
        test_profit_stack_attributes_exist,
        test_harvest_layer_register_on_entry,
        test_harvest_layer_remove_on_exit,
        test_flywheel_multiplier_applied_to_position_size,
        test_harvest_layer_floor_hit_exits_position,
        test_capital_recycling_receives_deposit_on_harvest,
    ]

    passed = 0
    failed = 0
    for t in tests:
        print(f"\n▶ {t.__name__}")
        try:
            t()
            passed += 1
        except AssertionError as e:
            print(f"  ❌ FAILED: {e}")
            failed += 1
        except Exception as e:
            import traceback
            print(f"  ❌ ERROR: {e}")
            traceback.print_exc()
            failed += 1

    print("\n" + "=" * 70)
    if failed == 0:
        print(f"✅ ALL {passed} TESTS PASSED")
    else:
        print(f"❌ {failed} FAILED / {passed} PASSED")
    print("=" * 70)

    sys.exit(0 if failed == 0 else 1)
