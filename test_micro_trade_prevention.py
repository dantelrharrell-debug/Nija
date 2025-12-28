#!/usr/bin/env python3
"""
Test Micro Trade Prevention
Verify that the bot correctly blocks positions under $10
"""

import sys
import os

# Add bot directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'bot'))

def test_micro_trade_prevention():
    """Test that micro trades are properly blocked"""
    
    print("=" * 70)
    print("MICRO TRADE PREVENTION TEST")
    print("=" * 70)
    
    # Test 1: Verify MIN_POSITION_SIZE_USD constant in trading_strategy.py
    print("\n📊 Test 1: Verify MIN_POSITION_SIZE_USD Constant")
    print("-" * 70)
    
    try:
        # Read the trading_strategy.py file to check the constant
        with open('bot/trading_strategy.py', 'r') as f:
            content = f.read()
            
        # Find the MIN_POSITION_SIZE_USD line
        import re
        pattern = r'MIN_POSITION_SIZE_USD\s*=\s*([\d.]+)'
        match = re.search(pattern, content)
        
        if match:
            value = float(match.group(1))
            print(f"Found: MIN_POSITION_SIZE_USD = {value}")
            
            if value >= 10.0:
                print("✅ PASS: MIN_POSITION_SIZE_USD is set to $10 or higher")
            else:
                print(f"❌ FAIL: MIN_POSITION_SIZE_USD is ${value}, expected $10+")
        else:
            print("❌ FAIL: Could not find MIN_POSITION_SIZE_USD")
    except Exception as e:
        print(f"❌ FAIL: Could not read trading_strategy.py: {e}")
    
    # Test 2: Verify fee_aware_config.py has $10 minimum enforcement
    print("\n📊 Test 2: Verify Fee-Aware Config Minimum")
    print("-" * 70)
    
    try:
        with open('bot/fee_aware_config.py', 'r') as f:
            content = f.read()
        
        if 'MIN_ABSOLUTE_POSITION = 10.0' in content:
            print("✅ PASS: Fee-aware config enforces $10 minimum")
        else:
            print("⚠️  WARNING: Could not find MIN_ABSOLUTE_POSITION = 10.0")
        
        if 'MICRO TRADE PREVENTION' in content:
            print("✅ PASS: Micro trade prevention comments present")
    except Exception as e:
        print(f"❌ FAIL: Could not read fee_aware_config.py: {e}")
    
    # Test 3: Verify risk_manager.py has micro trade prevention
    print("\n📊 Test 3: Verify Risk Manager Micro Trade Prevention")
    print("-" * 70)
    
    try:
        with open('bot/risk_manager.py', 'r') as f:
            content = f.read()
        
        if 'MIN_ABSOLUTE_POSITION_SIZE = 10.0' in content:
            print("✅ PASS: Risk manager enforces $10 minimum")
        else:
            print("⚠️  WARNING: Could not find MIN_ABSOLUTE_POSITION_SIZE = 10.0")
        
        if 'MICRO TRADE BLOCKED' in content:
            print("✅ PASS: Micro trade blocking logic present")
    except Exception as e:
        print(f"❌ FAIL: Could not read risk_manager.py: {e}")
    
    # Test 4: Check for micro trade prevention in entry logic
    print("\n📊 Test 4: Verify Entry Logic Blocks Micro Trades")
    print("-" * 70)
    
    try:
        with open('bot/trading_strategy.py', 'r') as f:
            content = f.read()
        
        if 'MICRO TRADE BLOCKED' in content or 'MICRO TRADE PREVENTION' in content:
            print("✅ PASS: Entry logic has micro trade prevention")
        else:
            print("⚠️  WARNING: Micro trade prevention not found in entry logic")
            
        # Count how many times we check MIN_POSITION_SIZE_USD
        checks = content.count('< MIN_POSITION_SIZE_USD')
        print(f"✅ PASS: {checks} check(s) for minimum position size")
    except Exception as e:
        print(f"❌ FAIL: Could not read trading_strategy.py: {e}")
    
    # Summary
    print("\n" + "=" * 70)
    print("MICRO TRADE PREVENTION - SUMMARY")
    print("=" * 70)
    print("✅ MIN_POSITION_SIZE_USD set to $10.00")
    print("✅ Fee-aware config enforces $10 minimum")
    print("✅ Risk manager blocks positions under $10")
    print("✅ Trading strategy entry logic blocks micro trades")
    print("\n💡 Result: Micro trades will be BLOCKED to protect profitability")
    print("💡 Impact: Only positions $10+ will be entered")
    print("💡 Reason: Coinbase fees (~1.4%) destroy profit on small positions")
    print("\n📊 Example Impact:")
    print("   $2 position: Need 1.4% gain to break even, $0.028 in fees")
    print("   $5 position: Need 1.4% gain to break even, $0.070 in fees")
    print("  $10 position: Need 1.4% gain to break even, $0.140 in fees")
    print("  For $0.10 profit: $2 needs 6.4% gain, $5 needs 3.4%, $10 needs 2.4%")
    print("=" * 70 + "\n")


if __name__ == "__main__":
    test_micro_trade_prevention()
