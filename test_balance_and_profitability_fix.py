#!/usr/bin/env python3
"""
Test Balance and Profitability Enhancements
===========================================

Tests the fixes for:
1. Enhanced balance visibility (held funds tracking)
2. Broker-specific profit targets
3. Kraken detailed balance method

Date: January 19, 2026
"""

import sys
import os

# Add bot directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'bot'))

def test_profit_targets():
    """Test that broker-specific profit targets are defined"""
    print("\n" + "=" * 70)
    print("TEST 1: Broker-Specific Profit Targets")
    print("=" * 70)
    
    try:
        # Check file contains the new constants instead of importing
        with open('bot/trading_strategy.py', 'r') as f:
            content = f.read()
        
        checks = [
            ('PROFIT_TARGETS_KRAKEN', 'Kraken-specific profit targets'),
            ('PROFIT_TARGETS_COINBASE', 'Coinbase-specific profit targets'),
            ('Net +0.64% after 0.36% fees', 'Kraken fee calculation'),
            ('Net +0.1% after 1.4% fees', 'Coinbase fee calculation'),
            ('broker_type == BrokerType.KRAKEN', 'Broker type checking'),
            ('profit_targets = PROFIT_TARGETS_KRAKEN', 'Kraken target assignment'),
        ]
        
        all_passed = True
        for check_str, desc in checks:
            if check_str in content:
                print(f"✅ {desc}: Found")
            else:
                print(f"❌ {desc}: NOT FOUND")
                all_passed = False
        
        return all_passed
    except Exception as e:
        print(f"❌ FAILED: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_balance_tracking_constants():
    """Test that balance tracking enhancements are in place"""
    print("\n" + "=" * 70)
    print("TEST 2: Balance Tracking Enhancement Constants")
    print("=" * 70)
    
    try:
        # Check that trading_strategy.py has the balance logging code
        with open('bot/trading_strategy.py', 'r') as f:
            content = f.read()
        
        # Look for the new balance visibility code
        checks = [
            ('total_held', 'Held funds tracking'),
            ('total_funds', 'Total funds tracking'),
            ('Held (in open orders)', 'Held funds logging'),
            ('TOTAL FUNDS', 'Total funds logging'),
        ]
        
        all_passed = True
        for check_str, desc in checks:
            if check_str in content:
                print(f"✅ {desc}: Found")
            else:
                print(f"❌ {desc}: NOT FOUND")
                all_passed = False
        
        return all_passed
    except Exception as e:
        print(f"❌ FAILED: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_kraken_detailed_balance_method():
    """Test that KrakenBroker has get_account_balance_detailed method"""
    print("\n" + "=" * 70)
    print("TEST 3: Kraken Detailed Balance Method")
    print("=" * 70)
    
    try:
        # Check that broker_manager.py has the new method
        with open('bot/broker_manager.py', 'r') as f:
            content = f.read()
        
        # Look for the new method in KrakenBroker
        checks = [
            ('def get_account_balance_detailed(self)', 'Method definition'),
            ('usd_held', 'USD held tracking'),
            ('usdt_held', 'USDT held tracking'),
            ('total_held', 'Total held calculation'),
            ('crypto_holdings', 'Crypto holdings tracking'),
        ]
        
        all_passed = True
        for check_str, desc in checks:
            if check_str in content:
                print(f"✅ Kraken {desc}: Found")
            else:
                print(f"❌ Kraken {desc}: NOT FOUND")
                all_passed = False
        
        return all_passed
    except Exception as e:
        print(f"❌ FAILED: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_kraken_balance_display():
    """Test that Kraken balance display is enhanced"""
    print("\n" + "=" * 70)
    print("TEST 4: Kraken Balance Display Enhancement")
    print("=" * 70)
    
    try:
        with open('bot/broker_manager.py', 'r') as f:
            content = f.read()
        
        # Look for enhanced Kraken balance logging
        checks = [
            ('Available USD', 'USD balance display'),
            ('Available USDT', 'USDT balance display'),
            ('Total Available', 'Total available display'),
            ('Held in open orders', 'Held funds display'),
            ('TOTAL FUNDS (Available + Held)', 'Total funds display'),
        ]
        
        all_passed = True
        for check_str, desc in checks:
            if check_str in content:
                print(f"✅ {desc}: Found")
            else:
                print(f"❌ {desc}: NOT FOUND")
                all_passed = False
        
        return all_passed
    except Exception as e:
        print(f"❌ FAILED: {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    """Run all tests"""
    print("\n" + "=" * 70)
    print("TESTING BALANCE AND PROFITABILITY ENHANCEMENTS")
    print("=" * 70)
    
    tests = [
        test_profit_targets,
        test_balance_tracking_constants,
        test_kraken_detailed_balance_method,
        test_kraken_balance_display,
    ]
    
    results = []
    for test in tests:
        result = test()
        results.append(result)
    
    # Summary
    print("\n" + "=" * 70)
    print("TEST SUMMARY")
    print("=" * 70)
    
    passed = sum(results)
    total = len(results)
    
    print(f"Tests passed: {passed}/{total}")
    
    if passed == total:
        print("\n✅ ALL TESTS PASSED")
        print("\nEnhancements implemented:")
        print("  ✅ Broker-specific profit targets (Kraken vs Coinbase)")
        print("  ✅ Enhanced balance visibility (held funds tracking)")
        print("  ✅ Kraken detailed balance method")
        print("  ✅ Improved Kraken balance display")
        return 0
    else:
        print(f"\n❌ {total - passed} TEST(S) FAILED")
        return 1


if __name__ == "__main__":
    sys.exit(main())
