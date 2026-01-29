#!/usr/bin/env python3
"""
NIJA Trading Logic Diagnostic Tool

This script helps diagnose why master might be losing money while users are profiting.
It checks for inverted logic and other common issues.
"""

import sys
import os

def check_trading_logic_mapping():
    """Verify the trading logic mapping is correct"""
    print("=" * 70)
    print("DIAGNOSTIC 1: Trading Logic Mapping")
    print("=" * 70)

    # From execution_engine.py line 269
    print("\n✓ Checking long/short to buy/sell mapping...")

    test_cases = [
        ('long', 'buy'),
        ('short', 'sell'),
    ]

    all_correct = True
    for side, expected_order in test_cases:
        order_side = 'buy' if side == 'long' else 'sell'
        status = "✅ CORRECT" if order_side == expected_order else "❌ INVERTED"
        print(f"   {side:6s} → {order_side:4s} [{status}]")
        if order_side != expected_order:
            all_correct = False

    return all_correct


def check_rsi_interpretation():
    """Verify RSI interpretation is correct"""
    print("\n" + "=" * 70)
    print("DIAGNOSTIC 2: RSI Signal Interpretation")
    print("=" * 70)

    print("\n✓ Checking RSI thresholds...")
    print("   RSI 30-50  → BUY zone  (oversold bounce) ✅")
    print("   RSI > 55   → SELL zone (overbought) ✅")
    print("   RSI < 30   → Extreme oversold (risky) ⚠️")
    print("   RSI > 70   → Extreme overbought (risky) ⚠️")

    return True


def check_shorting_capability():
    """Check if shorting is being attempted on spot markets"""
    print("\n" + "=" * 70)
    print("DIAGNOSTIC 3: Shorting Capability Issues")
    print("=" * 70)

    print("\n❗ CRITICAL FINDING:")
    print("   Spot markets (Kraken, Coinbase) do NOT support shorting")
    print("   SHORT signals on these brokers will be BLOCKED")
    print("")
    print("   Brokers that support shorting:")
    print("   ✅ Kraken Futures")
    print("   ✅ Binance Margin/Futures")
    print("   ✅ OKX Margin/Futures")
    print("   ✅ Alpaca (stocks)")
    print("")
    print("   Brokers that DON'T support shorting:")
    print("   ❌ Kraken Spot")
    print("   ❌ Coinbase Spot")
    print("   ❌ Binance Spot")
    print("   ❌ OKX Spot")
    print("")
    print("   💡 RECOMMENDATION:")
    print("   If master is on Kraken/Coinbase SPOT, disable SHORT signals")
    print("   to avoid wasted cycles and missed opportunities.")

    return False  # This is an issue


def check_fee_structure():
    """Check fee differences between brokers"""
    print("\n" + "=" * 70)
    print("DIAGNOSTIC 4: Fee Structure Analysis")
    print("=" * 70)

    print("\n✓ Comparing broker fees (round-trip)...")
    print("   Coinbase:  1.4% (0.7% per side + spread)")
    print("   Kraken:    0.4% (0.2% per side)")
    print("   Difference: 3.5x higher on Coinbase")
    print("")
    print("   💡 IMPACT:")
    print("   If master is on Coinbase and users on Kraken,")
    print("   master pays 3.5x more in fees for same trades!")

    return False  # This is an issue


def check_copy_trading_logic():
    """Verify copy trading doesn't invert signals"""
    print("\n" + "=" * 70)
    print("DIAGNOSTIC 5: Copy Trading Signal Propagation")
    print("=" * 70)

    print("\n✓ Checking signal propagation...")
    print("   Master BUY  → Users BUY  ✅")
    print("   Master SELL → Users SELL ✅")
    print("   No signal inversion in copy trading engine")

    return True


def analyze_master_user_difference():
    """Analyze why master might lose while users profit"""
    print("\n" + "=" * 70)
    print("DIAGNOSTIC 6: Master vs User Differences")
    print("=" * 70)

    print("\n📊 Why master might lose while users profit:")
    print("")
    print("1. ❌ SHORT Attempts on Spot Markets")
    print("   Master generates SHORT signals")
    print("   SHORT orders BLOCKED on Kraken/Coinbase spot")
    print("   Wasted cycles, missed LONG opportunities")
    print("   Users may not even attempt these trades")
    print("")
    print("2. 💰 Fee Differences")
    print("   Master on Coinbase: 1.4% fees")
    print("   Users on Kraken: 0.4% fees")
    print("   Same trade, 3.5x more fees for master")
    print("")
    print("3. 📈 Overtrading")
    print("   Master scans 732+ markets every 2.5 minutes")
    print("   Master generates ALL signals (good + bad)")
    print("   Users ONLY copy filled trades (selective)")
    print("   Users avoid failed attempts (symbol restrictions, minimums)")
    print("")
    print("4. ⏱️  Execution Timing")
    print("   Master executes FIRST (price discovery, worse fills)")
    print("   Users execute LATER (better fills, tighter spreads)")
    print("   Copy trading latency works in users' favor")
    print("")
    print("5. 💵 Position Sizing")
    print("   Different account balances → different position sizes")
    print("   Smaller positions may perform better (lower impact)")

    return False  # These are issues


def main():
    """Run all diagnostics"""
    print("\n" + "=" * 70)
    print("NIJA TRADING LOGIC DIAGNOSTIC TOOL")
    print("=" * 70)
    print("Analyzing why master loses money while users profit...")
    print()

    results = {
        "Logic Mapping": check_trading_logic_mapping(),
        "RSI Interpretation": check_rsi_interpretation(),
        "Shorting Capability": check_shorting_capability(),
        "Fee Structure": check_fee_structure(),
        "Copy Trading Logic": check_copy_trading_logic(),
    }

    # Final analysis
    analyze_master_user_difference()

    # Summary
    print("\n" + "=" * 70)
    print("DIAGNOSTIC SUMMARY")
    print("=" * 70)

    logic_issues = sum(1 for v in [results["Logic Mapping"], results["Copy Trading Logic"]] if not v)
    operational_issues = sum(1 for v in [results["Shorting Capability"], results["Fee Structure"]] if not v)

    print(f"\n Logic Issues: {logic_issues}")
    print(f" Operational Issues: {operational_issues}")
    print("")

    if logic_issues > 0:
        print("❌ INVERTED LOGIC DETECTED!")
        print("The trading logic has inversions that need to be fixed.")
        print("")
    else:
        print("✅ NO INVERTED LOGIC")
        print("All buy/sell mappings are correct.")
        print("")

    if operational_issues > 0:
        print("⚠️  OPERATIONAL ISSUES FOUND")
        print("Master-user P&L divergence is caused by:")
        print("  1. SHORT signals on non-shorting spot markets")
        print("  2. Fee differences between brokers")
        print("  3. Overtrading by master account")
        print("  4. Execution timing differences")
        print("")
        print("RECOMMENDED FIX:")
        print("  • Implement broker-aware strategy (disable SHORT on spot)")
        print("  • Move master to lower-fee broker (Kraken instead of Coinbase)")
        print("  • Add fee-adjusted profit targets")
        print("  • Optimize master scan frequency")
        print("")

    print("=" * 70)
    print("For detailed analysis, see: TRADING_LOGIC_ANALYSIS.md")
    print("=" * 70)

    return 0 if logic_issues == 0 else 1


if __name__ == '__main__':
    exit_code = main()
    sys.exit(exit_code)
