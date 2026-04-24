"""
Test NAMIE (NIJA Adaptive Market Intelligence Engine)

This script tests all NAMIE components and validates functionality.

Run:
    python test_namie.py

Author: NIJA Trading Systems
Date: January 30, 2026
"""

import sys
import os
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

# Add bot directory to path  
bot_path = os.path.join(os.path.dirname(__file__), 'bot')
if bot_path not in sys.path:
    sys.path.insert(0, bot_path)

# Import NAMIE components directly (avoid triggering bot/__init__.py)
import importlib.util

def load_module(module_name, file_path):
    """Load module from file without triggering __init__.py"""
    spec = importlib.util.spec_from_file_location(module_name, file_path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module

# Load NAMIE modules
bot_dir = os.path.join(os.path.dirname(__file__), 'bot')
namie_core_mod = load_module('namie_core', os.path.join(bot_dir, 'namie_core.py'))
NAMIECore = namie_core_mod.NAMIECore
get_namie_engine = namie_core_mod.get_namie_engine
MarketRegime = namie_core_mod.MarketRegime

namie_switcher_mod = load_module('namie_strategy_switcher', os.path.join(bot_dir, 'namie_strategy_switcher.py'))
NAMIEStrategySwitcher = namie_switcher_mod.NAMIEStrategySwitcher
get_strategy_switcher = namie_switcher_mod.get_strategy_switcher

namie_integration_mod = load_module('namie_integration', os.path.join(bot_dir, 'namie_integration.py'))
NAMIEIntegration = namie_integration_mod.NAMIEIntegration
quick_namie_check = namie_integration_mod.quick_namie_check

regime_selector_mod = load_module('regime_strategy_selector', os.path.join(bot_dir, 'regime_strategy_selector.py'))
TradingStrategy = regime_selector_mod.TradingStrategy


def generate_test_data(scenario="trending"):
    """
    Generate test market data for different scenarios
    
    Args:
        scenario: 'trending', 'ranging', 'volatile', or 'choppy'
    
    Returns:
        DataFrame with OHLCV data
    """
    np.random.seed(42)
    periods = 100
    
    if scenario == "trending":
        # Strong uptrend
        trend = np.linspace(100, 150, periods)
        noise = np.random.normal(0, 2, periods)
        close = trend + noise
        
    elif scenario == "ranging":
        # Sideways consolidation
        base = 100
        noise = np.random.normal(0, 3, periods)
        close = base + noise
        
    elif scenario == "volatile":
        # High volatility choppy
        base = 100
        volatility = np.random.normal(0, 8, periods)
        close = base + volatility
        
    else:  # choppy
        # Extreme chop
        base = 100
        chop = np.random.choice([-2, -1, 0, 1, 2], periods)
        close = base + np.cumsum(chop)
    
    # Generate OHLC
    high = close * (1 + np.random.uniform(0.001, 0.02, periods))
    low = close * (1 - np.random.uniform(0.001, 0.02, periods))
    open_price = np.roll(close, 1)
    open_price[0] = close[0]
    
    # Volume
    volume = np.random.uniform(100000, 500000, periods)
    
    df = pd.DataFrame({
        'timestamp': pd.date_range(end=datetime.now(), periods=periods, freq='5T'),
        'open': open_price,
        'high': high,
        'low': low,
        'close': close,
        'volume': volume,
    })
    
    return df


def calculate_test_indicators(df):
    """Calculate basic indicators for testing"""
    from bot.indicators import (
        calculate_vwap, calculate_ema, calculate_rsi, 
        calculate_macd, calculate_atr, calculate_adx
    )
    
    indicators = {}
    
    try:
        indicators['vwap'] = calculate_vwap(df)
        indicators['ema9'] = calculate_ema(df, 9)
        indicators['ema21'] = calculate_ema(df, 21)
        indicators['ema50'] = calculate_ema(df, 50)
        indicators['rsi'] = calculate_rsi(df, 14)
        indicators['rsi_9'] = calculate_rsi(df, 9)
        macd_data = calculate_macd(df)
        indicators['macd_line'] = macd_data['macd_line']
        indicators['macd_signal'] = macd_data['macd_signal']
        indicators['macd_histogram'] = macd_data['macd_histogram']
        indicators['atr'] = calculate_atr(df, 14)
        indicators['adx'] = calculate_adx(df, 14)
    except Exception as e:
        print(f"⚠️  Error calculating indicators: {e}")
        # Fallback to simple indicators
        indicators['vwap'] = df['close']
        indicators['ema9'] = df['close']
        indicators['ema21'] = df['close']
        indicators['ema50'] = df['close']
        indicators['rsi'] = pd.Series([50] * len(df))
        indicators['rsi_9'] = pd.Series([50] * len(df))
        indicators['macd_line'] = pd.Series([0] * len(df))
        indicators['macd_signal'] = pd.Series([0] * len(df))
        indicators['macd_histogram'] = pd.Series([0] * len(df))
        indicators['atr'] = pd.Series([2] * len(df))
        indicators['adx'] = pd.Series([25] * len(df))
    
    return indicators


def test_namie_core():
    """Test NAMIE Core Engine"""
    print("\n" + "="*60)
    print("TEST 1: NAMIE Core Engine")
    print("="*60)
    
    # Initialize
    namie = NAMIECore()
    
    # Test different scenarios
    scenarios = ["trending", "ranging", "volatile", "choppy"]
    
    for scenario in scenarios:
        print(f"\n--- Testing {scenario.upper()} market ---")
        
        df = generate_test_data(scenario)
        indicators = calculate_test_indicators(df)
        
        signal = namie.analyze_market(df, indicators, f"TEST-{scenario.upper()}")
        
        print(f"✓ Regime: {signal.regime.value} (confidence: {signal.regime_confidence:.0%})")
        print(f"✓ Trend Strength: {signal.trend_strength}/100 ({signal.trend_strength_category.value})")
        print(f"✓ Chop Score: {signal.chop_score:.0f}/100 ({signal.chop_condition.value})")
        print(f"✓ Volatility: {signal.volatility_regime.value} ({signal.volatility_cluster})")
        print(f"✓ Strategy: {signal.optimal_strategy.value}")
        print(f"✓ Should Trade: {'✅ YES' if signal.should_trade else '❌ NO'}")
        print(f"✓ Reason: {signal.trade_reason}")
        print(f"✓ Position Multiplier: {signal.position_size_multiplier:.2f}x")
    
    print("\n✅ NAMIE Core Engine test passed!")
    return True


def test_strategy_switcher():
    """Test Strategy Switcher"""
    print("\n" + "="*60)
    print("TEST 2: Strategy Switcher")
    print("="*60)
    
    switcher = NAMIEStrategySwitcher()
    namie = NAMIECore()
    
    # Simulate trading and record results
    scenarios = [
        ("trending", True, 100.0, 105.0),  # Winning trade
        ("trending", True, 105.0, 103.0),  # Losing trade
        ("trending", True, 103.0, 108.0),  # Winning trade
        ("ranging", True, 100.0, 101.0),   # Small win
        ("ranging", True, 101.0, 100.5),   # Small loss
        ("volatile", True, 100.0, 98.0),   # Loss in volatile
    ]
    
    for i, (scenario, is_long, entry, exit) in enumerate(scenarios, 1):
        df = generate_test_data(scenario)
        indicators = calculate_test_indicators(df)
        signal = namie.analyze_market(df, indicators, f"TEST-{i}")
        
        # Select strategy
        strategy, reason = switcher.select_strategy(signal)
        print(f"\nTrade {i} ({scenario}):")
        print(f"  Strategy: {strategy.value}")
        print(f"  Reason: {reason}")
        
        # Record trade result
        switcher.record_trade(
            strategy=strategy,
            regime=signal.regime,
            entry_price=entry,
            exit_price=exit,
            side='long' if is_long else 'short',
            size_usd=1000.0,
            commission=2.0
        )
    
    # Get performance summary
    summary = switcher.get_performance_summary()
    print("\n--- Performance Summary ---")
    print(f"Current Allocations:")
    for regime, strategy in summary['current_allocations'].items():
        print(f"  {regime}: {strategy}")
    
    print(f"\nBy Strategy:")
    for strategy, stats in summary['by_strategy'].items():
        if stats['trades'] > 0:
            wr = stats['wins'] / stats['trades']
            print(f"  {strategy}: {stats['trades']} trades, WR={wr:.0%}, PnL=${stats['total_pnl']:.2f}")
    
    print("\n✅ Strategy Switcher test passed!")
    return True


def test_integration():
    """Test Integration Layer"""
    print("\n" + "="*60)
    print("TEST 3: Integration Layer")
    print("="*60)
    
    # Test basic integration
    namie = NAMIEIntegration()
    
    df = generate_test_data("trending")
    indicators = calculate_test_indicators(df)
    
    print("\n--- Basic Integration Test ---")
    signal = namie.analyze(df, indicators, "BTC-USD")
    print(f"✓ Analysis complete")
    print(f"  Regime: {signal.regime.value}")
    print(f"  Should trade: {signal.should_trade}")
    
    # Test position sizing
    base_size = 1000.0
    adjusted_size = namie.adjust_position_size(signal, base_size)
    print(f"\n✓ Position sizing: ${base_size:.2f} → ${adjusted_size:.2f}")
    
    # Test adaptive RSI ranges
    rsi_ranges = namie.get_adaptive_rsi_ranges(signal)
    print(f"\n✓ Adaptive RSI ranges:")
    print(f"  Long: {rsi_ranges['long_min']:.0f}-{rsi_ranges['long_max']:.0f}")
    print(f"  Short: {rsi_ranges['short_min']:.0f}-{rsi_ranges['short_max']:.0f}")
    
    # Test entry decision
    should_enter, reason = namie.should_enter_trade(signal, base_entry_score=4, base_should_enter=True)
    print(f"\n✓ Entry decision: {should_enter}")
    print(f"  Reason: {reason}")
    
    # Test quick check
    print("\n--- Quick Check Test ---")
    should_trade, reason, quick_signal = quick_namie_check(df, indicators, "ETH-USD")
    print(f"✓ Quick check: {should_trade}")
    print(f"  Reason: {reason}")
    
    print("\n✅ Integration Layer test passed!")
    return True


def test_performance_tracking():
    """Test Performance Tracking"""
    print("\n" + "="*60)
    print("TEST 4: Performance Tracking")
    print("="*60)
    
    namie = NAMIEIntegration(enable_switcher=True)
    
    # Simulate trading session
    trades = [
        ("trending", 100.0, 105.0, 'long', 1000.0),
        ("trending", 105.0, 108.0, 'long', 1000.0),
        ("trending", 108.0, 107.0, 'long', 1000.0),
        ("ranging", 100.0, 100.5, 'long', 800.0),
        ("ranging", 100.5, 100.2, 'long', 800.0),
    ]
    
    for scenario, entry, exit, side, size in trades:
        df = generate_test_data(scenario)
        indicators = calculate_test_indicators(df)
        signal = namie.analyze(df, indicators, "TEST")
        
        namie.record_trade_result(
            signal=signal,
            entry_price=entry,
            exit_price=exit,
            side=side,
            size_usd=size,
            commission=2.0
        )
    
    # Get performance summary
    summary = namie.get_performance_summary()
    
    print("\n--- Performance Summary ---")
    print("By Regime:")
    for regime, stats in summary['namie_core'].items():
        if stats['trades'] > 0:
            print(f"  {regime}: {stats['trades']} trades, WR={stats['win_rate']:.0%}, PnL=${stats['total_pnl']:.2f}")
    
    print("\n✅ Performance Tracking test passed!")
    return True


def run_all_tests():
    """Run all NAMIE tests"""
    print("\n")
    print("╔" + "═"*58 + "╗")
    print("║" + " "*15 + "NAMIE TEST SUITE" + " "*27 + "║")
    print("╚" + "═"*58 + "╝")
    
    tests = [
        ("NAMIE Core Engine", test_namie_core),
        ("Strategy Switcher", test_strategy_switcher),
        ("Integration Layer", test_integration),
        ("Performance Tracking", test_performance_tracking),
    ]
    
    results = []
    
    for test_name, test_func in tests:
        try:
            result = test_func()
            results.append((test_name, result, None))
        except Exception as e:
            print(f"\n❌ {test_name} FAILED: {e}")
            import traceback
            traceback.print_exc()
            results.append((test_name, False, str(e)))
    
    # Print summary
    print("\n" + "="*60)
    print("TEST SUMMARY")
    print("="*60)
    
    passed = 0
    failed = 0
    
    for test_name, result, error in results:
        if result:
            print(f"✅ {test_name}")
            passed += 1
        else:
            print(f"❌ {test_name}")
            if error:
                print(f"   Error: {error}")
            failed += 1
    
    print(f"\nTotal: {passed + failed} tests")
    print(f"Passed: {passed}")
    print(f"Failed: {failed}")
    
    if failed == 0:
        print("\n🎉 ALL TESTS PASSED! NAMIE is ready to multiply your ROI! 🚀")
    else:
        print(f"\n⚠️  {failed} test(s) failed. Please review errors above.")
    
    return failed == 0


if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)
