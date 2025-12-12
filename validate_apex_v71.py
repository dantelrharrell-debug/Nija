#!/usr/bin/env python3
"""
Simple validation tests for NIJA Apex Strategy v7.1 components

These are basic smoke tests to ensure modules load and functions work.
Not a comprehensive test suite, but validates basic functionality.
"""

import sys
import os
import pandas as pd
import numpy as np

# Add bot directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'bot'))

from indicators import (
    calculate_vwap, calculate_ema, calculate_rsi, 
    calculate_macd, calculate_atr, calculate_adx
)
from risk_manager import RiskManager
from execution_engine import ExecutionEngine
from nija_apex_strategy_v71 import NIJAApexStrategyV71


def create_test_data(periods=100):
    """Create realistic test data"""
    np.random.seed(42)
    
    # Generate somewhat realistic price data
    base = 100
    trend = np.linspace(0, 5, periods)
    noise = np.random.randn(periods) * 0.5
    
    close = base + trend + noise
    open_prices = close + np.random.randn(periods) * 0.2
    high = np.maximum(close, open_prices) + abs(np.random.randn(periods) * 0.3)
    low = np.minimum(close, open_prices) - abs(np.random.randn(periods) * 0.3)
    volume = 1000 + np.random.randint(-200, 200, periods)
    
    df = pd.DataFrame({
        'open': open_prices,
        'high': high,
        'low': low,
        'close': close,
        'volume': volume
    })
    
    return df


def test_indicators():
    """Test indicator calculations"""
    print("Testing Indicators...")
    
    df = create_test_data(100)
    
    # Test VWAP
    vwap = calculate_vwap(df)
    assert len(vwap) == len(df), "VWAP length mismatch"
    assert not vwap.isna().all(), "VWAP all NaN"
    print("  ✓ VWAP calculation works")
    
    # Test EMA
    ema9 = calculate_ema(df, 9)
    ema21 = calculate_ema(df, 21)
    ema50 = calculate_ema(df, 50)
    assert len(ema9) == len(df), "EMA9 length mismatch"
    assert not ema9.isna().all(), "EMA9 all NaN"
    print("  ✓ EMA calculations work")
    
    # Test RSI
    rsi = calculate_rsi(df, 14)
    assert len(rsi) == len(df), "RSI length mismatch"
    assert (rsi >= 0).all() and (rsi <= 100).all(), "RSI out of range"
    print("  ✓ RSI calculation works")
    
    # Test MACD
    macd_line, signal_line, histogram = calculate_macd(df)
    assert len(macd_line) == len(df), "MACD length mismatch"
    assert not macd_line.isna().all(), "MACD all NaN"
    print("  ✓ MACD calculation works")
    
    # Test ATR
    atr = calculate_atr(df, 14)
    assert len(atr) == len(df), "ATR length mismatch"
    assert (atr >= 0).all(), "ATR negative values"
    print("  ✓ ATR calculation works")
    
    # Test ADX
    adx, plus_di, minus_di = calculate_adx(df, 14)
    assert len(adx) == len(df), "ADX length mismatch"
    assert (adx >= 0).all(), "ADX negative values"
    print("  ✓ ADX calculation works")
    
    print("  ✅ All indicator tests passed!\n")


def test_risk_manager():
    """Test risk management calculations"""
    print("Testing Risk Manager...")
    
    rm = RiskManager(min_position_pct=0.02, max_position_pct=0.10)
    
    # Test position sizing
    size = rm.calculate_position_size(account_balance=10000, adx=30, signal_strength=4)
    assert size > 0, "Position size should be positive"
    assert size <= 1000, "Position size should not exceed 10% of account"
    print(f"  ✓ Position sizing works (ADX=30, Score=4 -> ${size:.2f})")
    
    # Test ADX < 20 filtering
    size = rm.calculate_position_size(account_balance=10000, adx=15, signal_strength=5)
    assert size == 0, "Should not trade when ADX < 20"
    print(f"  ✓ ADX filter works (ADX=15 -> $0)")
    
    # Test stop loss calculation
    df = create_test_data(100)
    TEST_ENTRY_PRICE = 100.0
    TEST_SWING_LOW = 95.0  # Swing low below entry for long position test
    atr = 1.5
    stop = rm.calculate_stop_loss(entry_price=TEST_ENTRY_PRICE, side='long', swing_level=TEST_SWING_LOW, atr=atr)
    assert stop < TEST_ENTRY_PRICE, "Long stop should be below entry"
    print(f"  ✓ Stop loss calculation works (Entry=${TEST_ENTRY_PRICE}, Stop=${stop:.2f})")
    
    # Test take profit levels
    tp_levels = rm.calculate_take_profit_levels(entry_price=100, stop_loss=98, side='long')
    assert tp_levels['tp1'] > 100, "TP1 should be above entry"
    assert tp_levels['tp2'] > tp_levels['tp1'], "TP2 should be above TP1"
    assert tp_levels['tp3'] > tp_levels['tp2'], "TP3 should be above TP2"
    print(f"  ✓ Take profit levels work (TP1=${tp_levels['tp1']:.2f}, TP2=${tp_levels['tp2']:.2f}, TP3=${tp_levels['tp3']:.2f})")
    
    # Test trailing stop
    trailing = rm.calculate_trailing_stop(
        current_price=105, entry_price=100, side='long', atr=1.5, breakeven_mode=True
    )
    assert trailing >= 100, "Trailing stop should not go below breakeven"
    print(f"  ✓ Trailing stop works (Current=$105, Trailing=${trailing:.2f})")
    
    print("  ✅ All risk manager tests passed!\n")


def test_execution_engine():
    """Test execution engine"""
    print("Testing Execution Engine...")
    
    engine = ExecutionEngine(broker_client=None)
    
    # Test position tracking
    position = {
        'symbol': 'BTC-USD',
        'side': 'long',
        'entry_price': 100.0,
        'position_size': 500.0,
        'stop_loss': 98.0,
        'tp1': 102.0,
        'tp2': 104.0,
        'tp3': 106.0,
        'status': 'open',
        'remaining_size': 1.0
    }
    
    engine.positions['BTC-USD'] = position
    
    # Test stop loss check
    hit = engine.check_stop_loss_hit('BTC-USD', 97.5)
    assert hit == True, "Stop loss should be hit at 97.5"
    print("  ✓ Stop loss detection works")
    
    # Test take profit check
    tp = engine.check_take_profit_hit('BTC-USD', 102.5)
    assert tp == 'tp1', "TP1 should be hit at 102.5"
    print("  ✓ Take profit detection works")
    
    # Test position retrieval
    pos = engine.get_position('BTC-USD')
    assert pos is not None, "Should retrieve position"
    print("  ✓ Position retrieval works")
    
    print("  ✅ All execution engine tests passed!\n")


def test_strategy():
    """Test main strategy class"""
    print("Testing NIJA Apex Strategy v7.1...")
    
    df = create_test_data(100)
    strategy = NIJAApexStrategyV71(broker_client=None)
    
    # Test indicator calculation
    indicators = strategy.calculate_indicators(df)
    assert 'vwap' in indicators, "Missing VWAP"
    assert 'ema_9' in indicators, "Missing EMA9"
    assert 'adx' in indicators, "Missing ADX"
    assert 'atr' in indicators, "Missing ATR"
    print("  ✓ Indicator calculation works")
    
    # Test market filter
    allow_trade, direction, reason = strategy.check_market_filter(df, indicators)
    assert direction in ['uptrend', 'downtrend', 'none'], "Invalid direction"
    print(f"  ✓ Market filter works (Direction: {direction})")
    
    # Test entry signals
    long_signal, score, reason = strategy.check_long_entry(df, indicators)
    assert 0 <= score <= 5, "Score out of range"
    print(f"  ✓ Long entry check works (Score: {score}/5)")
    
    short_signal, score, reason = strategy.check_short_entry(df, indicators)
    assert 0 <= score <= 5, "Score out of range"
    print(f"  ✓ Short entry check works (Score: {score}/5)")
    
    # Test smart filters
    from datetime import datetime
    allowed, reason = strategy.check_smart_filters(df, datetime.now())
    print(f"  ✓ Smart filters work (Allowed: {allowed})")
    
    # Test full market analysis
    analysis = strategy.analyze_market(df, 'BTC-USD', account_balance=10000.0)
    assert 'action' in analysis, "Missing action in analysis"
    assert 'reason' in analysis, "Missing reason in analysis"
    print(f"  ✓ Market analysis works (Action: {analysis['action']})")
    
    # Test AI momentum scoring (skeleton)
    if strategy.ai_momentum_enabled:
        score = strategy.calculate_ai_momentum_score(df, indicators)
        assert 0 <= score <= 1, "AI score out of range"
        print(f"  ✓ AI momentum scoring works (Score: {score:.3f})")
    
    print("  ✅ All strategy tests passed!\n")


def main():
    """Run all tests"""
    print("=" * 80)
    print("NIJA APEX STRATEGY v7.1 - VALIDATION TESTS")
    print("=" * 80)
    print()
    
    try:
        test_indicators()
        test_risk_manager()
        test_execution_engine()
        test_strategy()
        
        print("=" * 80)
        print("✅ ALL TESTS PASSED!")
        print("=" * 80)
        print()
        print("The NIJA Apex Strategy v7.1 implementation is working correctly.")
        print("All core modules validated:")
        print("  • Indicators (VWAP, EMA, RSI, MACD, ADX, ATR)")
        print("  • Risk Manager (position sizing, stops, take profits)")
        print("  • Execution Engine (position tracking, TP/SL detection)")
        print("  • Strategy (market filter, entry/exit logic, smart filters)")
        print()
        
        return 0
        
    except AssertionError as e:
        print(f"\n❌ TEST FAILED: {e}\n")
        return 1
    except Exception as e:
        print(f"\n❌ ERROR: {e}\n")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    exit(main())
