#!/usr/bin/env python3
"""
Integration test for micro account mode.
Simulates the complete flow from balance check to position calculation.
"""

import sys
import os

# Add bot directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'bot'))

def test_risk_manager_integration():
    """Test that risk manager correctly implements micro account mode"""
    print("\n" + "="*70)
    print("RISK MANAGER INTEGRATION TEST")
    print("="*70 + "\n")
    
    try:
        # Import risk manager
        from risk_manager import AdaptiveRiskManager
        
        # Create risk manager instance with fee-aware mode
        risk_manager = AdaptiveRiskManager(
            min_position_pct=0.01,
            max_position_pct=0.50
        )
        
        print("✅ Risk manager initialized with fee-aware mode\n")
        
        # Test cases
        test_cases = [
            {
                'balance': 2.25,
                'adx': 30,
                'signal_strength': 4,
                'ai_confidence': 0.6,
                'volatility_pct': 0.015,
                'expected_mode': 'micro',
                'expected_min_position': 1.0
            },
            {
                'balance': 4.50,
                'adx': 25,
                'signal_strength': 3,
                'ai_confidence': 0.5,
                'volatility_pct': 0.01,
                'expected_mode': 'micro',
                'expected_min_position': 1.0
            },
            {
                'balance': 5.00,
                'adx': 35,
                'signal_strength': 4,
                'ai_confidence': 0.7,
                'volatility_pct': 0.012,
                'expected_mode': 'normal',
                'expected_min_position': 1.0
            },
            {
                'balance': 25.00,
                'adx': 40,
                'signal_strength': 5,
                'ai_confidence': 0.8,
                'volatility_pct': 0.018,
                'expected_mode': 'normal',
                'expected_min_position': 5.0
            }
        ]
        
        all_passed = True
        
        for i, test in enumerate(test_cases, 1):
            print(f"Test Case {i}: ${test['balance']:.2f} balance")
            print(f"  Expected mode: {test['expected_mode']}")
            
            # Calculate position size
            position_size, breakdown = risk_manager.calculate_position_size(
                account_balance=test['balance'],
                adx=test['adx'],
                signal_strength=test['signal_strength'],
                ai_confidence=test['ai_confidence'],
                volatility_pct=test['volatility_pct']
            )
            
            # Check if micro account mode was used
            is_micro = breakdown.get('micro_account_mode', False)
            actual_mode = 'micro' if is_micro else 'normal'
            
            # Check position size
            position_ok = position_size >= test['expected_min_position']
            mode_ok = actual_mode == test['expected_mode']
            
            print(f"  Actual mode: {actual_mode}")
            print(f"  Position size: ${position_size:.2f}")
            print(f"  Quality multiplier: {breakdown.get('quality_multiplier', 'N/A')}")
            
            if position_ok and mode_ok:
                print(f"  ✅ PASS\n")
            else:
                print(f"  ❌ FAIL")
                print(f"     Position check: {position_ok} (got ${position_size:.2f}, need ${test['expected_min_position']:.2f})")
                print(f"     Mode check: {mode_ok} (expected {test['expected_mode']}, got {actual_mode})\n")
                all_passed = False
        
        print("="*70)
        if all_passed:
            print("✅ ALL TESTS PASSED")
        else:
            print("❌ SOME TESTS FAILED")
        print("="*70 + "\n")
        
        return all_passed
        
    except Exception as e:
        print(f"❌ ERROR: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_fee_aware_config():
    """Test fee-aware configuration"""
    print("\n" + "="*70)
    print("FEE-AWARE CONFIG TEST")
    print("="*70 + "\n")
    
    try:
        from fee_aware_config import (
            MIN_BALANCE_TO_TRADE,
            get_position_size_pct,
            should_trade
        )
        
        print(f"Minimum balance to trade: ${MIN_BALANCE_TO_TRADE}")
        print()
        
        # Test position sizing at various balances
        test_balances = [2.0, 2.25, 3.0, 5.0, 10.0, 50.0, 100.0]
        
        print(f"{'Balance':<12} {'Can Trade?':<12} {'Position %':<12}")
        print("-" * 70)
        
        all_working = True
        
        for balance in test_balances:
            can_trade, reason = should_trade(balance, trades_today=0, last_trade_time=0)
            position_pct = get_position_size_pct(balance)
            
            if balance >= MIN_BALANCE_TO_TRADE:
                if not can_trade:
                    print(f"${balance:<11.2f} {'❌ NO':<12} {position_pct*100:<11.1f}%  ❌ SHOULD ALLOW")
                    print(f"  Reason: {reason}")
                    all_working = False
                else:
                    print(f"${balance:<11.2f} {'✅ YES':<12} {position_pct*100:<11.1f}%")
            else:
                if can_trade:
                    print(f"${balance:<11.2f} {'✅ YES':<12} {position_pct*100:<11.1f}%  ❌ SHOULD BLOCK")
                    all_working = False
                else:
                    print(f"${balance:<11.2f} {'❌ NO':<12} {position_pct*100:<11.1f}%")
        
        print()
        print("="*70)
        if all_working:
            print("✅ FEE-AWARE CONFIG WORKING CORRECTLY")
        else:
            print("❌ FEE-AWARE CONFIG HAS ISSUES")
        print("="*70 + "\n")
        
        return all_working
        
    except Exception as e:
        print(f"❌ ERROR: {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    """Run all integration tests"""
    print("\n" + "="*70)
    print("MICRO ACCOUNT MODE - INTEGRATION TESTS")
    print("="*70)
    
    test1_passed = test_fee_aware_config()
    test2_passed = test_risk_manager_integration()
    
    print("\n" + "="*70)
    print("FINAL RESULTS")
    print("="*70)
    print(f"Fee-aware config: {'✅ PASS' if test1_passed else '❌ FAIL'}")
    print(f"Risk manager integration: {'✅ PASS' if test2_passed else '❌ FAIL'}")
    print()
    
    if test1_passed and test2_passed:
        print("✅ ALL INTEGRATION TESTS PASSED")
        print()
        print("The bot will now work with $2.25 balance:")
        print("  • Micro account mode activates for balances < $5")
        print("  • Quality multipliers bypassed to ensure $1+ positions")
        print("  • Trading enabled with simplified risk management")
        print()
        print("⚠️  IMPORTANT: Profitability is very limited with < $5 balance")
        print("    Recommend funding to $25+ for better results")
        print("="*70 + "\n")
        return 0
    else:
        print("❌ SOME INTEGRATION TESTS FAILED")
        print("="*70 + "\n")
        return 1


if __name__ == "__main__":
    sys.exit(main())
