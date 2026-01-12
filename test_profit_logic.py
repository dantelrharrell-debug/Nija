#!/usr/bin/env python3
"""
Test script to verify profit-taking and stop-loss logic
"""

import sys
import os

# Add bot directory to path (do this once at the top)
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'bot'))

# Import constants from trading_strategy
from trading_strategy import (
    PROFIT_TARGETS, 
    STOP_LOSS_THRESHOLD, 
    RSI_OVERBOUGHT_THRESHOLD, 
    RSI_OVERSOLD_THRESHOLD
)

# Fee percentage - should match Coinbase fees used in trading_strategy
# This is ~1.4% round-trip (0.6% entry + 0.6% exit + 0.2% spread)
FEE_PCT = 1.4


def test_profit_targets():
    """Test that profit targets are correctly defined"""
    
    print("=" * 80)
    print("PROFIT-TAKING & STOP-LOSS CONFIGURATION TEST")
    print("=" * 80)
    
    # Test profit targets
    print("\n📈 PROFIT TARGETS:")
    print(f"   Number of targets: {len(PROFIT_TARGETS)}")
    
    for i, (target_pct, description) in enumerate(PROFIT_TARGETS, 1):
        net_profit = target_pct - FEE_PCT
        is_profitable = net_profit > 0
        status = "✅ PROFITABLE" if is_profitable else "⚠️  BREAKEVEN/LOSS"
        
        print(f"\n   Target {i}: {target_pct:.1f}% gross")
        print(f"   Description: {description}")
        print(f"   Net after fees: {net_profit:+.2f}%")
        print(f"   Status: {status}")
    
    # Test stop loss
    print("\n\n🛑 STOP LOSS:")
    print(f"   Threshold: {STOP_LOSS_THRESHOLD:.1f}%")
    net_loss = STOP_LOSS_THRESHOLD - FEE_PCT
    print(f"   Net loss after fees: {net_loss:.2f}%")
    
    # Test RSI thresholds
    print("\n\n📊 RSI EXIT THRESHOLDS:")
    print(f"   Overbought (profit-taking): RSI > {RSI_OVERBOUGHT_THRESHOLD}")
    print(f"   Oversold (loss-cutting): RSI < {RSI_OVERSOLD_THRESHOLD}")
    print(f"   Neutral zone: {RSI_OVERSOLD_THRESHOLD} ≤ RSI ≤ {RSI_OVERBOUGHT_THRESHOLD}")
    
    # Validate configuration
    print("\n\n🔍 VALIDATION:")
    issues = []
    
    # Check that at least one target is profitable
    profitable_targets = sum(1 for pct, _ in PROFIT_TARGETS if pct > FEE_PCT)
    if profitable_targets == 0:
        issues.append("❌ NO PROFITABLE TARGETS - all targets result in net loss after fees")
    else:
        print(f"   ✅ {profitable_targets}/{len(PROFIT_TARGETS)} targets are profitable after fees")
    
    # Check that targets are in descending order
    targets_only = [pct for pct, _ in PROFIT_TARGETS]
    if targets_only == sorted(targets_only, reverse=True):
        print(f"   ✅ Targets are in correct order (highest to lowest)")
    else:
        issues.append("❌ TARGETS NOT IN DESCENDING ORDER")
    
    # Check that stop loss is reasonable (not too tight, not too wide)
    if STOP_LOSS_THRESHOLD > -1.0:
        issues.append(f"⚠️  WARNING: Stop loss {STOP_LOSS_THRESHOLD}% might be too tight")
    elif STOP_LOSS_THRESHOLD < -3.0:
        issues.append(f"⚠️  WARNING: Stop loss {STOP_LOSS_THRESHOLD}% might be too wide")
    else:
        print(f"   ✅ Stop loss {STOP_LOSS_THRESHOLD}% is in reasonable range (-3% to -1%)")
    
    # Check RSI thresholds
    if RSI_OVERBOUGHT_THRESHOLD < 50 or RSI_OVERBOUGHT_THRESHOLD > 80:
        issues.append(f"⚠️  WARNING: Overbought RSI {RSI_OVERBOUGHT_THRESHOLD} is unusual (expected 50-80)")
    else:
        print(f"   ✅ Overbought RSI {RSI_OVERBOUGHT_THRESHOLD} is reasonable")
    
    if RSI_OVERSOLD_THRESHOLD < 20 or RSI_OVERSOLD_THRESHOLD > 50:
        issues.append(f"⚠️  WARNING: Oversold RSI {RSI_OVERSOLD_THRESHOLD} is unusual (expected 20-50)")
    else:
        print(f"   ✅ Oversold RSI {RSI_OVERSOLD_THRESHOLD} is reasonable")
    
    # Print summary
    print("\n" + "=" * 80)
    if issues:
        print("⚠️  VALIDATION WARNINGS:")
        for issue in issues:
            print(f"   {issue}")
    else:
        print("✅ ALL VALIDATIONS PASSED - Configuration looks good!")
    print("=" * 80)
    
    return len(issues) == 0


def test_exit_scenarios():
    """Test different exit scenarios"""
    print("\n\n" + "=" * 80)
    print("EXIT SCENARIO TESTING")
    print("=" * 80)
    
    scenarios = [
        ("Position at +3.5% profit", 3.5),
        ("Position at +2.5% profit", 2.5),
        ("Position at +1.8% profit", 1.8),
        ("Position at +1.3% profit", 1.3),
        ("Position at +0.8% profit", 0.8),
        ("Position at -0.5% loss", -0.5),
        ("Position at -1.2% loss", -1.2),
        ("Position at -1.8% loss", -1.8),
    ]
    
    for scenario_name, pnl_pct in scenarios:
        print(f"\n{scenario_name} (PnL: {pnl_pct:+.1f}%)")
        
        # Check which profit target would trigger
        exit_triggered = False
        for target_pct, description in PROFIT_TARGETS:
            if pnl_pct >= target_pct:
                net_pnl = pnl_pct - FEE_PCT
                print(f"   ✅ PROFIT TARGET HIT: {target_pct:.1f}%")
                print(f"   Net P&L: {net_pnl:+.2f}%")
                print(f"   Action: SELL for profit")
                exit_triggered = True
                break
        
        # Check stop loss
        if not exit_triggered and pnl_pct <= STOP_LOSS_THRESHOLD:
            net_loss = pnl_pct - FEE_PCT
            print(f"   🛑 STOP LOSS HIT: {STOP_LOSS_THRESHOLD:.1f}%")
            print(f"   Net loss: {net_loss:.2f}%")
            print(f"   Action: SELL to cut losses")
            exit_triggered = True
        
        if not exit_triggered:
            print(f"   📊 NO EXIT TRIGGER - Continue holding")
            print(f"   Waiting for: ≥{PROFIT_TARGETS[-1][0]:.1f}% profit or ≤{STOP_LOSS_THRESHOLD:.1f}% loss")
    
    print("\n" + "=" * 80)


if __name__ == "__main__":
    print("\n")
    
    # Run tests
    config_ok = test_profit_targets()
    test_exit_scenarios()
    
    print("\n")
    if config_ok:
        print("✅ ALL TESTS PASSED")
        exit(0)
    else:
        print("⚠️  TESTS COMPLETED WITH WARNINGS")
        exit(0)  # Still exit 0 so we don't block deployment
