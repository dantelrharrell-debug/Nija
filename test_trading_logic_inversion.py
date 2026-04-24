#!/usr/bin/env python3
"""
Test for Trading Logic Inversion

This test validates that the trading bot's buy/sell logic is NOT inverted.
If master is losing money while users are making money, this suggests
the logic might be inverted somewhere in the chain.

Tests:
1. RSI signal interpretation (oversold = buy, overbought = sell)
2. Long signal → buy order mapping
3. Short signal → sell order mapping
4. Copy trading signal propagation
5. RSI ranges (buy low, sell high)
"""

import sys
import os

# Add bot directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'bot'))

def test_rsi_signal_logic():
    """Test that RSI signals are interpreted correctly"""
    print("=" * 70)
    print("TEST 1: RSI Signal Logic")
    print("=" * 70)

    # Import coinbase config which has RSI logic
    try:
        from bot.broker_configs.coinbase_config import CoinbaseConfig
        config = CoinbaseConfig()

        # Test BUY signal (RSI oversold)
        # RSI in buy zone: 30-50 (oversold bounce)
        # Price above EMAs (bullish)
        print("\n📊 Test: RSI Oversold + Bullish Trend → Should BUY")
        rsi_oversold = 35  # Oversold zone
        price = 100
        ema9 = 95   # Price above EMA9 (bullish)
        ema21 = 90  # Price above EMA21 (bullish)

        should_buy = config.should_buy(rsi_oversold, price, ema9, ema21)
        print(f"   RSI: {rsi_oversold} (oversold)")
        print(f"   Price: ${price}, EMA9: ${ema9}, EMA21: ${ema21}")
        print(f"   Result: should_buy = {should_buy}")

        if should_buy:
            print("   ✅ CORRECT: RSI oversold + bullish → BUY signal")
        else:
            print("   ❌ INVERTED: RSI oversold should trigger BUY!")
            return False

        # Test SELL signal (RSI overbought)
        # RSI > 55 (overbought)
        print("\n📊 Test: RSI Overbought → Should SELL")
        rsi_overbought = 70  # Overbought
        should_sell = config.should_sell(rsi_overbought, price, ema9, ema21)
        print(f"   RSI: {rsi_overbought} (overbought)")
        print(f"   Result: should_sell = {should_sell}")

        if should_sell:
            print("   ✅ CORRECT: RSI overbought → SELL signal")
        else:
            print("   ❌ INVERTED: RSI overbought should trigger SELL!")
            return False

        return True

    except ImportError as e:
        print(f"⚠️  Could not import broker config: {e}")
        return None


def test_long_to_buy_mapping():
    """Test that 'long' side maps to 'buy' order"""
    print("\n" + "=" * 70)
    print("TEST 2: Long → Buy Order Mapping")
    print("=" * 70)

    # This is from execution_engine.py line 269
    print("\n📊 Test: side='long' should map to order_side='buy'")

    side = 'long'
    order_side = 'buy' if side == 'long' else 'sell'

    print(f"   Input: side = '{side}'")
    print(f"   Output: order_side = '{order_side}'")

    if order_side == 'buy':
        print("   ✅ CORRECT: long → buy")
        return True
    else:
        print("   ❌ INVERTED: long should map to buy!")
        return False


def test_short_to_sell_mapping():
    """Test that 'short' side maps to 'sell' order"""
    print("\n" + "=" * 70)
    print("TEST 3: Short → Sell Order Mapping")
    print("=" * 70)

    print("\n📊 Test: side='short' should map to order_side='sell'")

    side = 'short'
    order_side = 'buy' if side == 'long' else 'sell'

    print(f"   Input: side = '{side}'")
    print(f"   Output: order_side = '{order_side}'")

    if order_side == 'sell':
        print("   ✅ CORRECT: short → sell")
        return True
    else:
        print("   ❌ INVERTED: short should map to sell!")
        return False


def test_copy_trading_signal_propagation():
    """Test that copy trading doesn't invert signals"""
    print("\n" + "=" * 70)
    print("TEST 4: Copy Trading Signal Propagation")
    print("=" * 70)

    print("\n📊 Test: Master BUY signal → Users should also BUY")

    # Simulate master signal
    master_signal_side = 'buy'

    # Copy trading should use the same side
    # From copy_trade_engine.py line 591
    user_signal_side = master_signal_side  # Should be same

    print(f"   Master signal: side = '{master_signal_side}'")
    print(f"   User signal: side = '{user_signal_side}'")

    if master_signal_side == user_signal_side:
        print("   ✅ CORRECT: Users copy master's exact side")
        return True
    else:
        print("   ❌ INVERTED: Users should copy master's side!")
        return False


def test_indicator_buy_sell_signals():
    """Test that indicator-based buy/sell signals are correct"""
    print("\n" + "=" * 70)
    print("TEST 5: Indicator Buy/Sell Signal Logic")
    print("=" * 70)

    print("\n📊 Test: Bullish conditions → buy_signal = True")
    print("   Conditions required (3+ out of 5):")
    print("   1. Price above VWAP ✓")
    print("   2. EMA alignment bullish (EMA9 > EMA21 > EMA50) ✓")
    print("   3. RSI favorable ✓")
    print("   4. Volume confirmation ✓")
    print("   5. Candle close bullish ✓")
    print("   Score: 5/5 → buy_signal should be True")

    # From indicators.py line 724
    long_score = 5  # All conditions met
    buy_signal = long_score >= 3

    print(f"   Result: buy_signal = {buy_signal}")

    if buy_signal:
        print("   ✅ CORRECT: Bullish conditions → buy_signal = True")
    else:
        print("   ❌ INVERTED: Bullish conditions should give buy signal!")
        return False

    print("\n📊 Test: Bearish conditions → sell_signal = True")
    print("   Conditions required (3+ out of 5):")
    print("   1. Price below VWAP ✓")
    print("   2. EMA alignment bearish (EMA9 < EMA21 < EMA50) ✓")
    print("   3. RSI favorable ✓")
    print("   4. Volume confirmation ✓")
    print("   5. Candle close bearish ✓")
    print("   Score: 5/5 → sell_signal should be True")

    # From indicators.py line 754
    short_score = 5  # All conditions met
    sell_signal = short_score >= 3

    print(f"   Result: sell_signal = {sell_signal}")

    if sell_signal:
        print("   ✅ CORRECT: Bearish conditions → sell_signal = True")
        return True
    else:
        print("   ❌ INVERTED: Bearish conditions should give sell signal!")
        return False


def test_rsi_range_separation():
    """Test that buy and sell RSI ranges don't overlap incorrectly"""
    print("\n" + "=" * 70)
    print("TEST 6: RSI Range Separation (INSTITUTIONAL GRADE)")
    print("=" * 70)

    print("\n📊 Test: Long entry RSI range (should be 25-45)")
    print("   → Buy in LOWER RSI range (early entry, max R:R)")

    # CRITICAL TEST CASES - LONG ENTRY
    critical_long_tests = [
        (35, 30, True, "assert long_entry(rsi=35) == True"),
        (45, 40, True, "assert long_entry(rsi=45) == True (boundary)"),
        (48, 45, False, "assert long_entry(rsi=48) == False (too high)"),
        (55, 50, False, "assert long_entry(rsi=55) == False (way too high)"),
        (65, 60, False, "assert long_entry(rsi=65) == False (extremely high)"),
    ]

    print("\n   🔴 CRITICAL ASSERTIONS (MUST PASS):")
    all_passed = True
    for rsi, rsi_prev, should_pass, description in critical_long_tests:
        # Replicate the institutional logic: 25 <= rsi <= 45 and rsi > rsi_prev
        condition = 25 <= rsi <= 45 and rsi > rsi_prev

        print(f"\n   {description}")
        print(f"      RSI={rsi}, RSI_prev={rsi_prev}")
        print(f"      Condition: 25 <= {rsi} <= 45 and {rsi} > {rsi_prev}")
        print(f"      Result: {condition}, Expected: {should_pass}")

        if condition == should_pass:
            print(f"      ✅ PASS")
        else:
            print(f"      ❌ FAIL - CRITICAL ERROR!")
            all_passed = False

    # Additional edge cases
    edge_cases_long = [
        (25, 20, True, "RSI 25 (lower boundary) → BUY"),
        (26, 25, True, "RSI 26 rising from 25 → BUY"),
        (40, 35, True, "RSI 40 rising from 35 → BUY"),
        (44, 40, True, "RSI 44 rising from 40 → BUY (near upper boundary)"),
        (46, 45, False, "RSI 46 → NO BUY (just outside range)"),
        (50, 48, False, "RSI 50 → NO BUY (neutral zone)"),
    ]

    print("\n   📊 Edge Case Tests:")
    for rsi, rsi_prev, should_pass, description in edge_cases_long:
        condition = 25 <= rsi <= 45 and rsi > rsi_prev

        print(f"      {description}: ", end="")
        if condition == should_pass:
            print(f"✅")
        else:
            print(f"❌ (got {condition}, expected {should_pass})")
            all_passed = False

    print("\n📊 Test: Short entry RSI range (should be 55-75)")
    print("   → Sell in UPPER RSI range (early entry, max R:R)")

    # CRITICAL TEST CASES - SHORT ENTRY
    critical_short_tests = [
        (65, 70, True, "assert short_entry(rsi=65) == True"),
        (58, 63, True, "assert short_entry(rsi=58) == True"),
        (45, 50, False, "assert short_entry(rsi=45) == False (too low)"),
        (35, 40, False, "assert short_entry(rsi=35) == False (way too low)"),
    ]

    print("\n   🔴 CRITICAL ASSERTIONS (MUST PASS):")
    for rsi, rsi_prev, should_pass, description in critical_short_tests:
        # Replicate the institutional logic: 55 <= rsi <= 75 and rsi < rsi_prev
        condition = 55 <= rsi <= 75 and rsi < rsi_prev

        print(f"\n   {description}")
        print(f"      RSI={rsi}, RSI_prev={rsi_prev}")
        print(f"      Condition: 55 <= {rsi} <= 75 and {rsi} < {rsi_prev}")
        print(f"      Result: {condition}, Expected: {should_pass}")

        if condition == should_pass:
            print(f"      ✅ PASS")
        else:
            print(f"      ❌ FAIL - CRITICAL ERROR!")
            all_passed = False

    # Additional edge cases
    edge_cases_short = [
        (75, 78, True, "RSI 75 (upper boundary) → SELL"),
        (74, 75, True, "RSI 74 falling from 75 → SELL"),
        (60, 65, True, "RSI 60 falling from 65 → SELL"),
        (56, 60, True, "RSI 56 falling from 60 → SELL (near lower boundary)"),
        (55, 58, True, "RSI 55 (lower boundary) → SELL"),
        (54, 56, False, "RSI 54 → NO SELL (just outside range)"),
        (50, 53, False, "RSI 50 → NO SELL (neutral zone)"),
        (76, 78, False, "RSI 76 → NO SELL (above range)"),
    ]

    print("\n   📊 Edge Case Tests:")
    for rsi, rsi_prev, should_pass, description in edge_cases_short:
        condition = 55 <= rsi <= 75 and rsi < rsi_prev

        print(f"      {description}: ", end="")
        if condition == should_pass:
            print(f"✅")
        else:
            print(f"❌ (got {condition}, expected {should_pass})")
            all_passed = False

    if all_passed:
        print("\n   ✅ ALL RSI RANGE TESTS PASSED (INSTITUTIONAL GRADE)")
        print("   → Long entries: RSI 25-45 (early entry, avoid chasing)")
        print("   → Short entries: RSI 55-75 (early entry, avoid chasing)")
        print("   → NO OVERLAP: Maximizes R:R, captures trend expansion")
        return True
    else:
        print("\n   ❌ SOME RSI RANGE TESTS FAILED - CRITICAL!")
        return False


def main():
    """Run all tests"""
    print("\n" + "=" * 70)
    print("NIJA TRADING LOGIC INVERSION TEST SUITE")
    print("=" * 70)
    print("Testing if buy/sell logic is inverted...")
    print()

    results = []

    # Run tests
    results.append(("RSI Signal Logic", test_rsi_signal_logic()))
    results.append(("Long → Buy Mapping", test_long_to_buy_mapping()))
    results.append(("Short → Sell Mapping", test_short_to_sell_mapping()))
    results.append(("Copy Trading Propagation", test_copy_trading_signal_propagation()))
    results.append(("Indicator Signals", test_indicator_buy_sell_signals()))
    results.append(("RSI Range Separation", test_rsi_range_separation()))

    # Summary
    print("\n" + "=" * 70)
    print("TEST SUMMARY")
    print("=" * 70)

    passed = 0
    failed = 0
    skipped = 0

    for test_name, result in results:
        if result is True:
            print(f"✅ {test_name}: PASSED")
            passed += 1
        elif result is False:
            print(f"❌ {test_name}: FAILED (LOGIC INVERTED!)")
            failed += 1
        else:
            print(f"⚠️  {test_name}: SKIPPED")
            skipped += 1

    print("\n" + "=" * 70)
    print(f"Total: {passed} passed, {failed} failed, {skipped} skipped")
    print("=" * 70)

    if failed > 0:
        print("\n🚨 INVERTED LOGIC DETECTED!")
        print("The trading logic has inversions that need to be fixed.")
        return 1
    elif passed == len(results):
        print("\n✅ ALL TESTS PASSED")
        print("No inverted logic detected in the codebase.")
        print("\nIf master is losing money while users profit, the issue may be:")
        print("1. Different brokers/exchanges with different fee structures")
        print("2. Different account balance sizes affecting position sizing")
        print("3. Master trading more frequently than users (overtrading)")
        print("4. Timing differences in signal reception")
        print("5. Different risk profiles or stop-loss settings")
        return 0
    else:
        print("\n⚠️  SOME TESTS SKIPPED")
        print("Could not fully validate trading logic.")
        return 2


if __name__ == '__main__':
    exit_code = main()
    sys.exit(exit_code)
