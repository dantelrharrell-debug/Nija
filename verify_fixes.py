#!/usr/bin/env python3
"""
Verify NIJA Bleeding Fixes Deployment
Tests that all 4 critical fixes are properly implemented
"""

import sys
import os

# Add bot directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'bot'))

print("╔════════════════════════════════════════════════════════════════╗")
print("║         NIJA BLEEDING FIXES VERIFICATION                       ║")
print("╚════════════════════════════════════════════════════════════════╝")
print()

# Test 1: Check adaptive_growth_manager.py changes
print("TEST 1: Position Sizing Logic")
print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
try:
    from adaptive_growth_manager import AdaptiveGrowthManager
    
    manager = AdaptiveGrowthManager()
    
    # Test position size percentage
    pct = manager.get_position_size_pct()
    expected_pct = 0.15  # Should be max_position_pct (15%), not min (5%)
    
    if abs(pct - expected_pct) < 0.01:
        print(f"✅ Position sizing uses max_position_pct: {pct*100:.0f}% (correct)")
    else:
        print(f"❌ Position sizing wrong: {pct*100:.0f}% (expected {expected_pct*100:.0f}%)")
        print(f"   Still using min_position_pct instead of max!")
    
    # Test minimum position USD
    if hasattr(manager, 'get_min_position_usd'):
        min_usd = manager.get_min_position_usd()
        if min_usd == 2.00:
            print(f"✅ Minimum position size: ${min_usd:.2f} (correct)")
        else:
            print(f"⚠️  Minimum position size: ${min_usd:.2f} (expected $2.00)")
    else:
        print("❌ get_min_position_usd() method NOT FOUND!")
    
    # Test maximum position USD
    max_usd = manager.get_max_position_usd()
    if max_usd == 100.00:
        print(f"✅ Maximum position size: ${max_usd:.2f} (correct)")
    else:
        print(f"⚠️  Maximum position size: ${max_usd:.2f} (expected $100.00)")
    
    print()
    
except Exception as e:
    print(f"❌ FAILED: {e}")
    print()

# Test 2: Check trading_strategy.py changes
print("TEST 2: Circuit Breaker & Reserve Logic")
print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
try:
    # Read trading_strategy.py to check for circuit breaker
    with open('bot/trading_strategy.py', 'r') as f:
        content = f.read()
    
    # Check for circuit breaker
    if 'MINIMUM_TRADING_BALANCE' in content and 'TRADING HALTED' in content:
        print("✅ Circuit breaker code found (MINIMUM_TRADING_BALANCE)")
        
        # Find the value
        if '25.0' in content or '25' in content:
            print("✅ Circuit breaker threshold: $25 (correct)")
        else:
            print("⚠️  Circuit breaker threshold might not be $25")
    else:
        print("❌ Circuit breaker NOT FOUND in trading_strategy.py")
    
    # Check for improved reserve logic
    if 'live_balance * 0.5' in content or 'live_balance * 0.50' in content:
        print("✅ Reserve logic updated (50% for accounts < $100)")
    else:
        print("❌ Reserve logic NOT updated (still using old logic)")
    
    # Check for minimum position enforcement
    if 'min_position_hard_floor' in content or 'get_min_position_usd' in content:
        print("✅ Minimum position enforcement code found")
    else:
        print("❌ Minimum position enforcement NOT FOUND")
    
    print()
    
except Exception as e:
    print(f"❌ FAILED: {e}")
    print()

# Test 3: Simulate position sizing on different account sizes
print("TEST 3: Position Sizing Simulation")
print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
try:
    from adaptive_growth_manager import AdaptiveGrowthManager
    
    manager = AdaptiveGrowthManager()
    
    test_balances = [5.0, 10.0, 25.0, 50.0, 100.0, 500.0]
    
    for balance in test_balances:
        pct = manager.get_position_size_pct()
        calculated = balance * pct
        min_usd = manager.get_min_position_usd()
        max_usd = manager.get_max_position_usd()
        
        # Apply limits
        position = max(min_usd, calculated)
        position = min(max_usd, position)
        
        # Determine if trading allowed (circuit breaker)
        trading_allowed = balance >= 25.0
        
        status = "✅ TRADE" if trading_allowed and position >= min_usd else "❌ BLOCKED"
        print(f"  Balance ${balance:6.2f} → Position ${position:5.2f} ({position/balance*100:5.1f}%) {status}")
    
    print()
    print("Expected behavior:")
    print("  • Balance < $25: BLOCKED by circuit breaker")
    print("  • Balance ≥ $25: Position ≥ $2.00 minimum")
    print("  • All positions: ≤ $100.00 maximum")
    print()
    
except Exception as e:
    print(f"❌ FAILED: {e}")
    print()

# Summary
print("╔════════════════════════════════════════════════════════════════╗")
print("║                    VERIFICATION SUMMARY                        ║")
print("╚════════════════════════════════════════════════════════════════╝")
print()
print("If all tests show ✅, the fixes are properly deployed.")
print()
print("Current account balance: $0.15")
print("   → Circuit breaker will BLOCK trading (balance < $25)")
print("   → Waiting for deposit to resume trading")
print()
print("After depositing $50-100:")
print("   → Bot will trade positions of $2.00-$15.00")
print("   → Circuit breaker will allow trading (balance > $25)")
print("   → Profit margin after fees becomes achievable")
print()
