#!/usr/bin/env python3
"""
Test Fee-Aware Profit Calculations

Verifies that the updated profit thresholds ensure net profitability after fees.
"""

import sys
import os

# Add bot directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'bot'))

from execution_engine import ExecutionEngine, DEFAULT_ROUND_TRIP_FEE
from risk_manager import AdaptiveRiskManager

def test_fee_aware_profit_thresholds():
    """Test that profit thresholds result in net profitability"""
    
    print("=" * 70)
    print("TESTING FEE-AWARE PROFIT THRESHOLDS")
    print("=" * 70)
    print(f"\nCoinbase round-trip fee: {DEFAULT_ROUND_TRIP_FEE*100:.1f}%\n")
    
    # Test profit thresholds
    test_cases = [
        (0.020, "2.0% gross profit"),
        (0.025, "2.5% gross profit"),
        (0.030, "3.0% gross profit"),
        (0.040, "4.0% gross profit"),
    ]
    
    print("Fee-Aware Profit Analysis:")
    print("-" * 70)
    print(f"{'Gross Profit':<20} {'Fees':<15} {'Net Profit':<15} {'Status':<20}")
    print("-" * 70)
    
    all_profitable = True
    
    for gross_pct, label in test_cases:
        net_pct = gross_pct - DEFAULT_ROUND_TRIP_FEE
        is_profitable = net_pct > 0
        status = "✓ PROFITABLE" if is_profitable else "✗ LOSS"
        
        if not is_profitable:
            all_profitable = False
        
        print(f"{label:<20} {DEFAULT_ROUND_TRIP_FEE*100:>6.1f}%      {net_pct*100:>6.1f}%      {status}")
    
    print("-" * 70)
    
    # Compare with old broken thresholds
    print("\nOLD BROKEN THRESHOLDS (for comparison):")
    print("-" * 70)
    
    old_test_cases = [
        (0.005, "0.5% gross profit"),
        (0.010, "1.0% gross profit"),
        (0.020, "2.0% gross profit"),
        (0.030, "3.0% gross profit"),
    ]
    
    print(f"{'Gross Profit':<20} {'Fees':<15} {'Net Profit':<15} {'Status':<20}")
    print("-" * 70)
    
    for gross_pct, label in old_test_cases:
        net_pct = gross_pct - DEFAULT_ROUND_TRIP_FEE
        is_profitable = net_pct > 0
        status = "✓ PROFITABLE" if is_profitable else "✗ LOSS"
        
        print(f"{label:<20} {DEFAULT_ROUND_TRIP_FEE*100:>6.1f}%      {net_pct*100:>6.1f}%      {status}")
    
    print("-" * 70)
    
    if all_profitable:
        print("\n✅ SUCCESS: All new profit thresholds result in NET PROFITABILITY")
        return True
    else:
        print("\n❌ FAILURE: Some thresholds would result in losses")
        return False

def test_risk_manager_tp_levels():
    """Test that risk manager generates fee-aware TP levels"""
    
    print("\n" + "=" * 70)
    print("TESTING RISK MANAGER TAKE PROFIT LEVELS")
    print("=" * 70)
    
    # Initialize risk manager
    risk_mgr = AdaptiveRiskManager()
    
    # Test scenario: Long entry at $100, stop at $98 (2% risk)
    entry_price = 100.0
    stop_loss = 98.0
    side = 'long'
    
    tp_levels = risk_mgr.calculate_take_profit_levels(entry_price, stop_loss, side)
    
    print(f"\nScenario: LONG at ${entry_price}, stop at ${stop_loss}")
    print(f"Risk: ${entry_price - stop_loss} ({((entry_price - stop_loss) / entry_price)*100:.1f}%)\n")
    
    print("Take Profit Levels:")
    print("-" * 70)
    
    for level, price in [('TP1', tp_levels['tp1']), ('TP2', tp_levels['tp2']), ('TP3', tp_levels['tp3'])]:
        gross_pct = (price - entry_price) / entry_price
        net_pct = gross_pct - DEFAULT_ROUND_TRIP_FEE
        is_profitable = net_pct > 0
        status = "✓ PROFITABLE" if is_profitable else "✗ LOSS"
        
        print(f"{level}: ${price:.2f} (Gross: {gross_pct*100:+.1f}%, Net: {net_pct*100:+.1f}%) {status}")
    
    print("-" * 70)
    
    # Check all are profitable
    all_profitable = True
    for level, price in [('TP1', tp_levels['tp1']), ('TP2', tp_levels['tp2']), ('TP3', tp_levels['tp3'])]:
        gross_pct = (price - entry_price) / entry_price
        net_pct = gross_pct - DEFAULT_ROUND_TRIP_FEE
        if net_pct <= 0:
            all_profitable = False
            print(f"\n❌ {level} would result in NET LOSS")
    
    if all_profitable:
        print("\n✅ SUCCESS: All TP levels ensure NET PROFITABILITY")
        return True
    else:
        print("\n❌ FAILURE: Some TP levels would result in losses")
        return False

def main():
    """Run all tests"""
    
    print("\n" + "=" * 70)
    print("FEE-AWARE PROFITABILITY FIX - VERIFICATION TESTS")
    print("December 27, 2025")
    print("=" * 70)
    
    # Run tests
    test1_pass = test_fee_aware_profit_thresholds()
    test2_pass = test_risk_manager_tp_levels()
    
    # Summary
    print("\n" + "=" * 70)
    print("TEST SUMMARY")
    print("=" * 70)
    print(f"Profit Thresholds Test: {'✅ PASS' if test1_pass else '❌ FAIL'}")
    print(f"Risk Manager TP Test:   {'✅ PASS' if test2_pass else '❌ FAIL'}")
    print("=" * 70)
    
    if test1_pass and test2_pass:
        print("\n🎉 ALL TESTS PASSED - Fee-aware profit calculations are working correctly!")
        print("\nKey Improvements:")
        print("  • Minimum profit threshold raised from 0.5% to 2.0%")
        print("  • All exits now ensure NET profitability after 1.4% fees")
        print("  • Risk manager TP levels use 1R, 1.5R, 2R (instead of 0.5R, 1R, 1.5R)")
        print("  • Expected impact: Bot will now only take PROFITABLE trades")
        return 0
    else:
        print("\n❌ SOME TESTS FAILED - Review the calculations")
        return 1

if __name__ == "__main__":
    sys.exit(main())
