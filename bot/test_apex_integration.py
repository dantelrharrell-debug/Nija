"""
NIJA Apex Strategy v7.1 - Integration Tests
============================================

Basic tests to verify core functionality.
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__)))

import pandas as pd
import numpy as np
from datetime import datetime, timedelta

# Import modules to test
from apex_indicators import (
    calculate_adx, calculate_atr, calculate_enhanced_macd,
    calculate_vwap, calculate_rsi, calculate_ema_alignment
)
from apex_risk_manager import ApexRiskManager
from apex_filters import ApexSmartFilters
from apex_trailing_system import ApexTrailingSystem
from apex_strategy_v7 import ApexStrategyV7


def generate_test_data(num_candles=150):
    """Generate test OHLCV data"""
    np.random.seed(42)
    base_price = 50000.0
    prices = [base_price]

    for _ in range(num_candles - 1):
        change = np.random.normal(0, 0.01)
        new_price = prices[-1] * (1 + change)
        prices.append(new_price)

    data = []
    for close in prices:
        high = close * (1 + abs(np.random.normal(0, 0.005)))
        low = close * (1 - abs(np.random.normal(0, 0.005)))
        open_price = close * (1 + np.random.normal(0, 0.003))
        volume = np.random.uniform(100000, 1000000)

        data.append({
            'open': open_price,
            'high': high,
            'low': low,
            'close': close,
            'volume': volume,
        })

    return pd.DataFrame(data)


def test_indicators():
    """Test indicator calculations"""
    print("\n" + "="*60)
    print("TEST 1: Indicator Calculations")
    print("="*60)

    df = generate_test_data()

    # Test ADX
    adx, plus_di, minus_di = calculate_adx(df, period=14)
    assert len(adx) == len(df), "ADX length mismatch"
    assert not adx.isna().all(), "ADX all NaN"
    print(f"✅ ADX: Last value = {adx.iloc[-1]:.2f}")

    # Test ATR
    atr = calculate_atr(df, period=14)
    assert len(atr) == len(df), "ATR length mismatch"
    assert not atr.isna().all(), "ATR all NaN"
    print(f"✅ ATR: Last value = {atr.iloc[-1]:.2f}")

    # Test VWAP
    vwap = calculate_vwap(df)
    assert len(vwap) == len(df), "VWAP length mismatch"
    assert not vwap.isna().all(), "VWAP all NaN"
    print(f"✅ VWAP: Last value = {vwap.iloc[-1]:.2f}")

    # Test RSI
    rsi = calculate_rsi(df, period=14)
    assert len(rsi) == len(df), "RSI length mismatch"
    assert not rsi.isna().all(), "RSI all NaN"
    print(f"✅ RSI: Last value = {rsi.iloc[-1]:.2f}")

    # Test MACD
    macd_line, signal_line, histogram, hist_direction = calculate_enhanced_macd(df)
    assert len(macd_line) == len(df), "MACD length mismatch"
    print(f"✅ MACD: Histogram = {histogram.iloc[-1]:.2f}")

    # Test EMA alignment
    ema_data = calculate_ema_alignment(df)
    assert 'ema9' in ema_data, "Missing EMA9"
    assert 'ema21' in ema_data, "Missing EMA21"
    print(f"✅ EMA Alignment: Bullish = {ema_data['bullish_alignment']}")

    print("\n✅ All indicator tests passed!")


def test_risk_manager():
    """Test risk manager"""
    print("\n" + "="*60)
    print("TEST 2: Risk Manager")
    print("="*60)

    risk_mgr = ApexRiskManager(account_balance=10000.0)

    # Test trend quality assessment
    trend_quality = risk_mgr.assess_trend_quality(adx=35, plus_di=30, minus_di=15)
    assert trend_quality == 'strong', f"Expected 'strong', got '{trend_quality}'"
    print(f"✅ Trend quality (ADX=35): {trend_quality}")

    # Test position sizing
    entry_price = 50000.0
    stop_loss = 49500.0
    size_usd, size_pct, risk = risk_mgr.calculate_position_size(
        'strong', entry_price, stop_loss
    )
    assert size_pct == 0.07, f"Expected 0.07, got {size_pct}"
    print(f"✅ Position size (strong trend): {size_pct*100:.0f}% = ${size_usd:,.2f}")

    # Test risk limits
    can_open, reason = risk_mgr.can_open_position()
    assert can_open, f"Should be able to open position: {reason}"
    print(f"✅ Risk limits check: {reason}")

    # Test R-multiple calculation
    r_multiple = risk_mgr.calculate_r_multiple(50000, 51000, 49500)
    assert r_multiple > 0, "R-multiple should be positive for profitable trade"
    print(f"✅ R-multiple: {r_multiple:.2f}R")

    print("\n✅ All risk manager tests passed!")


def test_smart_filters():
    """Test smart filters"""
    print("\n" + "="*60)
    print("TEST 3: Smart Filters")
    print("="*60)

    filters = ApexSmartFilters()
    df = generate_test_data()

    # Test volume filter
    is_blocked, reason = filters.check_low_volume(df)
    print(f"✅ Volume filter: Blocked = {is_blocked}, Reason: {reason}")

    # Test chop detection
    is_blocked, reason = filters.check_chop_detection(adx=25)
    assert not is_blocked, "Should not be blocked with ADX=25"
    print(f"✅ Chop detection (ADX=25): {reason}")

    is_blocked, reason = filters.check_chop_detection(adx=15)
    assert is_blocked, "Should be blocked with ADX=15"
    print(f"✅ Chop detection (ADX=15): {reason}")

    # Test all filters
    any_blocked, reasons = filters.check_all_filters(df, adx=25)
    print(f"✅ All filters check: Blocked = {any_blocked}")

    print("\n✅ All smart filter tests passed!")


def test_trailing_system():
    """Test trailing system"""
    print("\n" + "="*60)
    print("TEST 4: Trailing System")
    print("="*60)

    trailing = ApexTrailingSystem()

    # Test breakeven stop
    be_stop = trailing.calculate_breakeven_stop(50000, 'long')
    assert be_stop > 50000, "Breakeven stop should be above entry for long"
    print(f"✅ Breakeven stop (long @ 50000): ${be_stop:,.2f}")

    # Test ATR trailing stop
    atr_stop = trailing.calculate_atr_trailing_stop(51000, 500, 'long')
    assert atr_stop < 51000, "ATR stop should be below current price for long"
    print(f"✅ ATR trailing stop: ${atr_stop:,.2f}")

    # Test update trailing stop
    result = trailing.update_trailing_stop(
        position_id='test_1',
        current_price=51000,
        entry_price=50000,
        stop_loss_price=49500,
        atr=500,
        side='long',
        r_multiple=1.5
    )
    assert 'new_stop' in result, "Missing new_stop in result"
    assert result['position_state']['breakeven_activated'], "Breakeven should be activated"
    print(f"✅ Trailing stop update: New stop = ${result['new_stop']:,.2f}")

    print("\n✅ All trailing system tests passed!")


def test_apex_strategy():
    """Test main Apex strategy"""
    print("\n" + "="*60)
    print("TEST 5: Apex Strategy Integration")
    print("="*60)

    strategy = ApexStrategyV7(account_balance=10000.0, enable_ai=False)
    df = generate_test_data()

    # Test indicator calculation
    indicators = strategy.calculate_all_indicators(df)
    assert indicators is not None, "Indicators should not be None"
    assert 'adx' in indicators, "Missing ADX"
    assert 'atr' in indicators, "Missing ATR"
    print(f"✅ Strategy indicators: ADX={indicators['adx']:.1f}, ATR={indicators['atr']:.2f}")

    # Test market filter
    passes, trend, reason = strategy.check_market_filter(df, indicators)
    print(f"✅ Market filter: Passes={passes}, Trend={trend}, Reason={reason}")

    # Test entry analysis
    analysis = strategy.analyze_entry_opportunity(df, "BTC-USD")
    assert 'symbol' in analysis, "Missing symbol in analysis"
    assert 'should_enter' in analysis, "Missing should_enter in analysis"
    print(f"✅ Entry analysis: Should enter = {analysis['should_enter']}")

    if not analysis['should_enter']:
        print(f"   Reason: {analysis['reason']}")

    print("\n✅ All Apex strategy tests passed!")


def run_all_tests():
    """Run all tests"""
    print("\n" + "="*60)
    print("NIJA APEX STRATEGY v7.1 - INTEGRATION TESTS")
    print("="*60)

    try:
        test_indicators()
        test_risk_manager()
        test_smart_filters()
        test_trailing_system()
        test_apex_strategy()

        print("\n" + "="*60)
        print("✅ ALL TESTS PASSED!")
        print("="*60 + "\n")

        return True

    except AssertionError as e:
        print(f"\n❌ TEST FAILED: {e}\n")
        return False
    except Exception as e:
        print(f"\n❌ ERROR: {e}\n")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)
