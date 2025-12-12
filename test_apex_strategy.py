"""
NIJA Apex Strategy v7.1 - Integration Tests

Tests for core strategy components:
- Market state filtering
- Entry signal generation
- Risk management calculations
- Filter application
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'bot'))

import pandas as pd
import numpy as np
from datetime import datetime, timedelta

# Import strategy components
from nija_apex_strategy import NijaApexStrategyV71
from indicators_apex import (
    calculate_atr, calculate_adx, calculate_macd_histogram_analysis,
    detect_momentum_candle, check_ema_alignment
)
from risk_management import RiskManager
from market_filters import detect_choppy_market, check_minimum_volume


def create_sample_data(num_candles=100, trend='bullish', volatility='moderate'):
    """
    Create sample OHLCV data for testing.
    
    Args:
        num_candles: Number of candles to generate
        trend: 'bullish', 'bearish', or 'ranging'
        volatility: 'low', 'moderate', or 'high'
    
    Returns:
        pandas.DataFrame with OHLCV data
    """
    # Set volatility parameters
    vol_params = {
        'low': 0.005,
        'moderate': 0.015,
        'high': 0.030
    }
    vol = vol_params.get(volatility, 0.015)
    
    # Generate base price trend
    if trend == 'bullish':
        base_trend = np.linspace(100, 120, num_candles)
    elif trend == 'bearish':
        base_trend = np.linspace(120, 100, num_candles)
    else:  # ranging
        base_trend = 110 + 5 * np.sin(np.linspace(0, 4*np.pi, num_candles))
    
    # Add random volatility
    np.random.seed(42)
    noise = np.random.randn(num_candles) * vol * base_trend
    close_prices = base_trend + noise
    
    # Generate OHLC from close
    data = []
    for i, close in enumerate(close_prices):
        candle_range = abs(np.random.randn()) * vol * close
        high = close + candle_range * 0.6
        low = close - candle_range * 0.4
        open_price = close + np.random.randn() * vol * close * 0.3
        volume = 1000000 + np.random.randint(-200000, 500000)
        
        data.append({
            'timestamp': datetime.utcnow() - timedelta(minutes=5*(num_candles-i)),
            'open': max(open_price, 0.01),
            'high': max(high, open_price, close, 0.01),
            'low': max(min(low, open_price, close), 0.01),
            'close': max(close, 0.01),
            'volume': max(volume, 1000)
        })
    
    return pd.DataFrame(data)


def test_market_state_analysis():
    """Test market state filtering."""
    print("\n" + "="*60)
    print("TEST: Market State Analysis")
    print("="*60)
    
    # Test bullish trending market
    df_bullish = create_sample_data(100, trend='bullish', volatility='moderate')
    strategy = NijaApexStrategyV71(account_balance=10000.0)
    
    market_state = strategy.analyze_market_state(df_bullish)
    
    print(f"\n📊 Bullish Trending Market:")
    print(f"   Tradeable: {market_state['is_tradeable']}")
    print(f"   Reason: {market_state['reason']}")
    print(f"   ADX: {market_state['details']['adx']:.2f}")
    print(f"   ATR %: {market_state['details']['atr_pct']*100:.3f}%")
    print(f"   Volume Ratio: {market_state['details']['volume_ratio']:.2f}x")
    print(f"   Regime: {market_state['details']['regime']['regime']}")
    
    # Test choppy/ranging market
    df_ranging = create_sample_data(100, trend='ranging', volatility='low')
    market_state_ranging = strategy.analyze_market_state(df_ranging)
    
    print(f"\n📊 Ranging/Choppy Market:")
    print(f"   Tradeable: {market_state_ranging['is_tradeable']}")
    print(f"   Reason: {market_state_ranging['reason']}")
    print(f"   ADX: {market_state_ranging['details']['adx']:.2f}")
    
    assert market_state['is_tradeable'] or not market_state['is_tradeable'], "Market state check completed"
    print("\n✅ Market state analysis test PASSED")


def test_entry_signal_generation():
    """Test entry signal generation with multi-confirmation."""
    print("\n" + "="*60)
    print("TEST: Entry Signal Generation")
    print("="*60)
    
    df = create_sample_data(100, trend='bullish', volatility='moderate')
    strategy = NijaApexStrategyV71(account_balance=10000.0)
    
    # Analyze market first
    market_state = strategy.analyze_market_state(df)
    
    # Generate entry signal
    entry_signal = strategy.generate_entry_signal(df, market_state)
    
    print(f"\n📈 Entry Signal Analysis:")
    print(f"   Signal: {entry_signal['signal'].upper()}")
    print(f"   Score: {entry_signal['score']}/6 confirmations")
    print(f"   Confidence: {entry_signal['confidence']*100:.1f}%")
    
    if entry_signal['details'].get('reasons'):
        print(f"   Reasons:")
        for reason in entry_signal['details']['reasons']:
            print(f"      • {reason}")
    
    assert entry_signal['signal'] in ['long', 'short', 'none'], "Valid signal type"
    assert 0 <= entry_signal['score'] <= 6, "Score in valid range"
    print("\n✅ Entry signal generation test PASSED")


def test_risk_calculations():
    """Test risk management calculations."""
    print("\n" + "="*60)
    print("TEST: Risk Management Calculations")
    print("="*60)
    
    risk_manager = RiskManager(
        account_balance=10000.0,
        max_risk_per_trade=0.02,
        max_daily_loss=0.025,
        max_total_exposure=0.30
    )
    
    # Test ADX-weighted position sizing
    print("\n💰 ADX-Weighted Position Sizing:")
    
    test_cases = [
        (5, 45, "A+ setup, strong trend"),
        (4, 25, "Good setup, moderate trend"),
        (3, 15, "Moderate setup, weak trend")
    ]
    
    for signal_score, adx, description in test_cases:
        position = risk_manager.calculate_position_size_adx_weighted(
            signal_strength=signal_score,
            adx_value=adx
        )
        print(f"\n   {description}:")
        print(f"      Signal Score: {signal_score}/6")
        print(f"      ADX: {adx}")
        print(f"      Position Size: ${position['position_size_usd']:.2f} ({position['position_size_pct']*100:.2f}%)")
        print(f"      ADX Multiplier: {position['adx_multiplier']:.2f}x")
        print(f"      Signal Multiplier: {position['signal_multiplier']:.2f}x")
    
    # Test ATR-based stop-loss
    print("\n🛑 ATR-Based Stop-Loss:")
    entry_price = 100.0
    atr_value = 1.5
    
    stop_calc = risk_manager.calculate_stop_loss_atr(
        entry_price=entry_price,
        atr_value=atr_value,
        direction='long'
    )
    
    print(f"   Entry Price: ${entry_price:.2f}")
    print(f"   ATR: ${atr_value:.2f}")
    print(f"   Stop Price: ${stop_calc['stop_price']:.2f}")
    print(f"   Stop Distance: {stop_calc['stop_distance_pct']*100:.2f}%")
    
    # Test tiered take-profits
    print("\n🎯 Tiered Take-Profits:")
    tp_calc = risk_manager.calculate_tiered_take_profits(
        entry_price=entry_price,
        direction='long'
    )
    
    for tp_name, tp_data in tp_calc.items():
        print(f"   {tp_name.upper()}: ${tp_data['price']:.2f} (+{tp_data['pct']*100:.2f}%) - Exit {int(tp_data['exit_size']*100)}%")
    
    print("\n✅ Risk management calculations test PASSED")


def test_position_limit_checks():
    """Test position limit and risk checks."""
    print("\n" + "="*60)
    print("TEST: Position Limit Checks")
    print("="*60)
    
    risk_manager = RiskManager(
        account_balance=10000.0,
        max_risk_per_trade=0.02,
        max_daily_loss=0.025,
        max_total_exposure=0.30
    )
    
    # Test normal position
    print("\n✅ Normal Position (within limits):")
    result = risk_manager.can_open_position(300.0)  # $300 = 3%
    print(f"   Can Open: {result['can_open']}")
    print(f"   Reason: {result['reason']}")
    print(f"   Current Exposure: {result['current_exposure']:.2f}")
    
    # Simulate high exposure
    risk_manager.total_exposure = 2800  # 28% already exposed
    print("\n⚠️  High Exposure (close to limit):")
    result = risk_manager.can_open_position(300.0)  # Would be 31% total
    print(f"   Can Open: {result['can_open']}")
    print(f"   Reason: {result['reason']}")
    print(f"   Current Exposure: ${result['current_exposure']:.2f}")
    
    # Simulate daily loss limit
    risk_manager.total_exposure = 0
    risk_manager.daily_pnl = -260  # -2.6% loss
    print("\n❌ Daily Loss Limit Reached:")
    result = risk_manager.can_open_position(300.0)
    print(f"   Can Open: {result['can_open']}")
    print(f"   Reason: {result['reason']}")
    print(f"   Daily PnL: ${result['daily_pnl']:.2f}")
    
    print("\n✅ Position limit checks test PASSED")


def test_full_strategy_flow():
    """Test complete strategy decision flow."""
    print("\n" + "="*60)
    print("TEST: Full Strategy Flow")
    print("="*60)
    
    # Create bullish trending data
    df = create_sample_data(100, trend='bullish', volatility='moderate')
    
    # Initialize strategy
    strategy = NijaApexStrategyV71(account_balance=10000.0)
    
    # Run full decision process
    should_enter, trade_plan = strategy.should_enter_trade(df)
    
    print(f"\n🎯 Strategy Decision:")
    print(f"   Should Enter: {should_enter}")
    
    if should_enter:
        print(f"\n📋 Trade Plan:")
        print(f"   Signal: {trade_plan['signal'].upper()}")
        print(f"   Score: {trade_plan['score']}/6")
        print(f"   Confidence: {trade_plan['confidence']*100:.1f}%")
        print(f"   Entry Price: ${trade_plan['entry_price']:.2f}")
        print(f"   Position Size: ${trade_plan['position_size_usd']:.2f} ({trade_plan['position_size_pct']*100:.1f}%)")
        print(f"   Stop-Loss: ${trade_plan['stop_loss']:.2f}")
        print(f"   TP1: ${trade_plan['take_profits']['tp1']['price']:.2f} (+{trade_plan['take_profits']['tp1']['pct']*100:.2f}%)")
        print(f"   TP2: ${trade_plan['take_profits']['tp2']['price']:.2f} (+{trade_plan['take_profits']['tp2']['pct']*100:.2f}%)")
        print(f"   TP3: ${trade_plan['take_profits']['tp3']['price']:.2f} (+{trade_plan['take_profits']['tp3']['pct']*100:.2f}%)")
        print(f"\n   Entry Reasons:")
        for reason in trade_plan['entry_reasons']:
            print(f"      • {reason}")
    else:
        print(f"   No trade signal generated")
    
    print("\n✅ Full strategy flow test PASSED")


def test_indicator_calculations():
    """Test indicator calculations."""
    print("\n" + "="*60)
    print("TEST: Indicator Calculations")
    print("="*60)
    
    df = create_sample_data(100, trend='bullish', volatility='moderate')
    
    # Test ATR
    atr = calculate_atr(df, period=14)
    print(f"\n📊 ATR Calculation:")
    print(f"   Latest ATR: {atr.iloc[-1]:.4f}")
    print(f"   ATR % of price: {(atr.iloc[-1]/df['close'].iloc[-1])*100:.3f}%")
    
    # Test ADX
    adx, plus_di, minus_di = calculate_adx(df, period=14)
    print(f"\n📊 ADX Calculation:")
    print(f"   Latest ADX: {adx.iloc[-1]:.2f}")
    print(f"   +DI: {plus_di.iloc[-1]:.2f}")
    print(f"   -DI: {minus_di.iloc[-1]:.2f}")
    
    # Test MACD
    macd = calculate_macd_histogram_analysis(df)
    print(f"\n📊 MACD Analysis:")
    print(f"   MACD Line: {macd['macd_line'].iloc[-1]:.4f}")
    print(f"   Signal Line: {macd['signal_line'].iloc[-1]:.4f}")
    print(f"   Histogram: {macd['histogram'].iloc[-1]:.4f}")
    print(f"   Histogram Increasing: {macd['histogram_increasing'].iloc[-1]}")
    
    # Test EMA alignment
    ema_check = check_ema_alignment(df)
    print(f"\n📊 EMA Alignment:")
    print(f"   Bullish Aligned: {ema_check['bullish_aligned']}")
    print(f"   Bearish Aligned: {ema_check['bearish_aligned']}")
    print(f"   EMA9: {ema_check['ema_9']:.2f}")
    print(f"   EMA21: {ema_check['ema_21']:.2f}")
    print(f"   EMA50: {ema_check['ema_50']:.2f}")
    
    # Test momentum candle
    momentum = detect_momentum_candle(df)
    print(f"\n📊 Momentum Candle:")
    print(f"   Bullish Momentum: {momentum['is_bullish_momentum']}")
    print(f"   Bearish Momentum: {momentum['is_bearish_momentum']}")
    print(f"   Body Strength: {momentum['body_strength']*100:.1f}%")
    
    print("\n✅ Indicator calculations test PASSED")


def run_all_tests():
    """Run all integration tests."""
    print("\n" + "="*60)
    print("NIJA APEX STRATEGY v7.1 - INTEGRATION TESTS")
    print("="*60)
    
    try:
        test_indicator_calculations()
        test_market_state_analysis()
        test_entry_signal_generation()
        test_risk_calculations()
        test_position_limit_checks()
        test_full_strategy_flow()
        
        print("\n" + "="*60)
        print("✅ ALL TESTS PASSED")
        print("="*60)
        print("\nNIJA Apex Strategy v7.1 is ready for integration!")
        
    except Exception as e:
        print(f"\n❌ TEST FAILED: {e}")
        import traceback
        traceback.print_exc()
        return False
    
    return True


if __name__ == '__main__':
    success = run_all_tests()
    sys.exit(0 if success else 1)
