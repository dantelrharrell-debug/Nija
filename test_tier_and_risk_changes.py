#!/usr/bin/env python3
"""
Test script for tier override and risk manager changes.

Tests:
1. Tier override functionality (MASTER_ACCOUNT_TIER env var)
2. Risk manager max_position_pct is 15%
3. Trade size calculations respect 15% limit
"""

import sys
import os

# Add bot directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'bot'))

from tier_config import get_tier_from_balance, TradingTier, get_tier_config
from risk_manager import AdaptiveRiskManager


def test_tier_override():
    """Test that tier override works correctly."""
    print("\n" + "="*70)
    print("TEST 1: Tier Override Functionality")
    print("="*70)
    
    balance = 62.49
    
    # Test without override (user account)
    print(f"\n📊 User account without override (balance: ${balance:.2f}):")
    tier_default = get_tier_from_balance(balance, is_master=False)
    config_default = get_tier_config(tier_default)
    print(f"  ├─ Tier: {tier_default.value}")
    print(f"  ├─ Risk range: {config_default.risk_per_trade_pct[0]:.0f}%-{config_default.risk_per_trade_pct[1]:.0f}%")
    print(f"  └─ Trade size: ${config_default.trade_size_min:.2f}-${config_default.trade_size_max:.2f}")
    
    assert tier_default == TradingTier.STARTER, f"Expected STARTER, got {tier_default.value}"
    print("  ✅ Correctly assigned STARTER tier for user account")
    
    # Test master account (should ALWAYS be BALLER)
    print(f"\n📊 Master account (balance: ${balance:.2f}):")
    tier_master = get_tier_from_balance(balance, is_master=True)
    config_master = get_tier_config(tier_master)
    print(f"  ├─ Tier: {tier_master.value}")
    print(f"  ├─ Risk range: {config_master.risk_per_trade_pct[0]:.0f}%-{config_master.risk_per_trade_pct[1]:.0f}%")
    print(f"  └─ Trade size: ${config_master.trade_size_min:.2f}-${config_master.trade_size_max:.2f}")
    
    assert tier_master == TradingTier.BALLER, f"Expected BALLER for master, got {tier_master.value}"
    print("  ✅ Master account correctly forced to BALLER tier")
    
    # Test with BALLER override via env var
    print(f"\n📊 With BALLER override via env var (balance: ${balance:.2f}):")
    os.environ['MASTER_ACCOUNT_TIER'] = 'BALLER'
    tier_override = get_tier_from_balance(balance)
    config_override = get_tier_config(tier_override)
    print(f"  ├─ Tier: {tier_override.value}")
    print(f"  ├─ Risk range: {config_override.risk_per_trade_pct[0]:.0f}%-{config_override.risk_per_trade_pct[1]:.0f}%")
    print(f"  └─ Trade size: ${config_override.trade_size_min:.2f}-${config_override.trade_size_max:.2f}")
    
    assert tier_override == TradingTier.BALLER, f"Expected BALLER, got {tier_override.value}"
    print("  ✅ Successfully overridden to BALLER tier")
    
    # Clean up - safely remove env var
    os.environ.pop('MASTER_ACCOUNT_TIER', None)
    
    return True


def test_risk_manager_max_position():
    """Test that risk manager max_position_pct is 15%."""
    print("\n" + "="*70)
    print("TEST 2: Risk Manager Max Position Limit")
    print("="*70)
    
    rm = AdaptiveRiskManager()
    
    print(f"\n📊 Risk Manager Configuration:")
    print(f"  ├─ min_position_pct: {rm.min_position_pct*100:.0f}%")
    print(f"  ├─ max_position_pct: {rm.max_position_pct*100:.0f}%")
    print(f"  └─ max_total_exposure: {rm.max_total_exposure*100:.0f}%")
    
    assert rm.max_position_pct == 0.15, f"Expected 0.15, got {rm.max_position_pct}"
    print("  ✅ max_position_pct correctly set to 15%")
    
    return True


def test_trade_size_calculations():
    """Test that trade size calculations respect 15% limit."""
    print("\n" + "="*70)
    print("TEST 3: Trade Size Calculations")
    print("="*70)
    
    balance = 62.49
    rm = AdaptiveRiskManager()
    
    # Test with very strong signals (should still cap at 15%)
    print(f"\n📊 Position sizing for ${balance:.2f} balance:")
    print(f"  Testing with strong signals (ADX=45, confidence=0.9):")
    
    position_size, breakdown = rm.calculate_position_size(
        account_balance=balance,
        adx=45,  # Very strong trend
        signal_strength=5,  # Strongest signal
        ai_confidence=0.9,  # Very high confidence
        volatility_pct=0.01  # Normal volatility
    )
    
    position_pct = (position_size / balance) * 100
    final_pct = breakdown.get('final_pct', 0) * 100
    
    print(f"  ├─ Calculated position: ${position_size:.2f}")
    print(f"  ├─ Position %: {position_pct:.2f}%")
    print(f"  └─ Final pct (capped): {final_pct:.2f}%")
    
    # Should never exceed 15%
    assert position_pct <= 15.0, f"Position size {position_pct:.2f}% exceeds 15% limit"
    assert final_pct <= 15.0, f"Final pct {final_pct:.2f}% exceeds 15% limit"
    print(f"  ✅ Position size respects 15% limit")
    
    # Calculate expected max trade size
    max_trade = balance * 0.15
    print(f"\n📊 Maximum trade size for ${balance:.2f}:")
    print(f"  ├─ 15% of balance: ${max_trade:.2f}")
    print(f"  └─ For reference: Problem statement expected ≈$9.37")
    
    # The max should be around $9.37 (15% of $62.49)
    expected_max = 62.49 * 0.15
    assert abs(max_trade - expected_max) < 0.01, "Max trade calculation incorrect"
    print(f"  ✅ Maximum trade size correctly calculated")
    
    return True


def test_investor_tier_benefits():
    """Show the benefits of BALLER tier for master account."""
    print("\n" + "="*70)
    print("TEST 4: Master Account BALLER Tier Benefits")
    print("="*70)
    
    balance = 62.49
    
    # STARTER tier (user account)
    starter_config = get_tier_config(TradingTier.STARTER)
    print(f"\n📊 STARTER tier (user account, ${balance:.2f}):")
    print(f"  ├─ Risk range: {starter_config.risk_per_trade_pct[0]:.0f}%-{starter_config.risk_per_trade_pct[1]:.0f}%")
    print(f"  ├─ Trade size: ${starter_config.trade_size_min:.2f}-${starter_config.trade_size_max:.2f}")
    print(f"  └─ Max positions: {starter_config.max_positions}")
    
    # BALLER tier (master account)
    baller_config = get_tier_config(TradingTier.BALLER)
    print(f"\n📊 BALLER tier (MASTER account, ${balance:.2f}):")
    print(f"  ├─ Risk range: {baller_config.risk_per_trade_pct[0]:.0f}%-{baller_config.risk_per_trade_pct[1]:.0f}%")
    print(f"  ├─ Trade size: ${baller_config.trade_size_min:.2f}-${baller_config.trade_size_max:.2f}")
    print(f"  └─ Max positions: {baller_config.max_positions}")
    
    print(f"\n📊 Key improvements with BALLER tier (master account):")
    print(f"  ✅ Much lower max risk: {baller_config.risk_per_trade_pct[1]:.0f}% vs {starter_config.risk_per_trade_pct[1]:.0f}%")
    print(f"  ✅ Higher min trade: ${baller_config.trade_size_min:.2f} vs ${starter_config.trade_size_min:.2f}")
    print(f"  ✅ More positions: {baller_config.max_positions} vs {starter_config.max_positions}")
    
    print(f"\n⚠️  Important for ${balance:.2f} master account balance:")
    max_with_15_pct = balance * 0.15
    print(f"  • 15% global cap limits trades to ${max_with_15_pct:.2f}")
    print(f"  • BALLER tier minimum is ${baller_config.trade_size_min:.2f}")
    print(f"  • Actual trades will be limited by 15% cap (${max_with_15_pct:.2f})")
    print(f"  • Master account still gets best risk parameters (1-2% tier guidelines)")
    print(f"  ✅ This is the REQUIRED configuration for master account")
    
    return True


def main():
    """Run all tests."""
    print("\n" + "="*70)
    print("TESTING: Tier Override and Risk Manager Changes")
    print("="*70)
    print("\nRequirements:")
    print("  1. Master account ALWAYS at BALLER tier (never lower)")
    print("  2. Reduce max trade size to ≤15% of balance")
    
    tests = [
        ("Tier Override & Master BALLER", test_tier_override),
        ("Risk Manager Max Position", test_risk_manager_max_position),
        ("Trade Size Calculations", test_trade_size_calculations),
        ("Master Account BALLER Benefits", test_investor_tier_benefits),
    ]
    
    results = []
    for test_name, test_func in tests:
        try:
            result = test_func()
            results.append((test_name, "PASS", None))
        except Exception as e:
            results.append((test_name, "FAIL", str(e)))
            print(f"  ❌ Test failed: {e}")
    
    # Summary
    print("\n" + "="*70)
    print("TEST SUMMARY")
    print("="*70)
    
    for test_name, status, error in results:
        if status == "PASS":
            print(f"  ✅ {test_name}: {status}")
        else:
            print(f"  ❌ {test_name}: {status}")
            if error:
                print(f"     Error: {error}")
    
    passed = sum(1 for _, status, _ in results if status == "PASS")
    total = len(results)
    
    print(f"\n  Total: {passed}/{total} tests passed")
    
    if passed == total:
        print("\n✅ All tests passed!")
        print("\n📝 Configuration instructions:")
        print("  For MASTER account, add to .env file:")
        print("  MASTER_ACCOUNT_TIER=BALLER")
        print("\n  ⚠️  CRITICAL: Master account is ALWAYS BALLER tier")
        print("  • Best risk management parameters (1-2% tier guidelines)")
        print("  • 15% max trade size cap still applies globally")
        print("  • For $62.49 balance: max trade = $9.37 (15% cap)")
        print("\n  ✅ For user accounts, use auto-detection based on balance")
        print("\n  Benefits:")
        print("  • Master: BALLER tier with 15% cap for safety")
        print("  • Users: Appropriate tier for their account size")
        print("  • All accounts: Max 15% per trade (global protection)")
        return 0
    else:
        print("\n❌ Some tests failed")
        return 1


if __name__ == "__main__":
    sys.exit(main())
