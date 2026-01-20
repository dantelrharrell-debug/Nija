#!/usr/bin/env python3
"""
Test Copy Trading Implementation
=================================

Validates the new copy trading architecture:
1. XRP blacklist enforcement
2. on_master_trade hook integration
3. Kraken copy-only mode
4. Independent trading disabled for Kraken users
"""

import sys
import os

# Add bot directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'bot'))

def test_xrp_blacklist():
    """Test that XRP is properly blacklisted."""
    print("\n" + "="*70)
    print("TEST 1: XRP Blacklist Enforcement")
    print("="*70)
    
    try:
        # Try to import without dotenv (just check the constants directly)
        import importlib.util
        
        # Load apex_config without executing imports
        apex_config_path = os.path.join(os.path.dirname(__file__), 'bot', 'apex_config.py')
        strategy_path = os.path.join(os.path.dirname(__file__), 'bot', 'trading_strategy.py')
        
        # Read files and check for XRP in DISABLED_PAIRS
        with open(apex_config_path, 'r') as f:
            apex_content = f.read()
        
        with open(strategy_path, 'r') as f:
            strategy_content = f.read()
        
        # Check for XRP variants
        xrp_variants = ["XRP-USD", "XRPUSD", "XRP-USDT", "XRPUSDT"]
        
        apex_has_xrp = any(xrp in apex_content for xrp in xrp_variants)
        strategy_has_xrp = any(xrp in strategy_content for xrp in xrp_variants)
        
        print(f"Apex config contains XRP variants: {apex_has_xrp}")
        print(f"Strategy contains XRP variants: {strategy_has_xrp}")
        
        # Also check for DISABLED_PAIRS definition
        apex_has_disabled = 'DISABLED_PAIRS' in apex_content
        strategy_has_disabled = 'DISABLED_PAIRS' in strategy_content
        
        print(f"Apex config has DISABLED_PAIRS: {apex_has_disabled}")
        print(f"Strategy has DISABLED_PAIRS: {strategy_has_disabled}")
        
        if apex_has_xrp and strategy_has_xrp and apex_has_disabled and strategy_has_disabled:
            print("✅ PASS: XRP variants found in blacklists")
            return True
        else:
            print(f"❌ FAIL: XRP not properly blacklisted")
            return False
            
    except Exception as e:
        print(f"❌ FAIL: Error testing XRP blacklist: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_on_master_trade_hook_exists():
    """Test that on_master_trade hook is properly defined."""
    print("\n" + "="*70)
    print("TEST 2: on_master_trade Hook Availability")
    print("="*70)
    
    try:
        from kraken_copy_trading import on_master_trade
        
        # Check if callable
        if callable(on_master_trade):
            print("✅ PASS: on_master_trade hook is callable")
            
            # Check signature
            import inspect
            sig = inspect.signature(on_master_trade)
            params = list(sig.parameters.keys())
            print(f"   Parameters: {params}")
            
            if 'trade' in params:
                print("✅ PASS: Hook has 'trade' parameter")
                return True
            else:
                print("❌ FAIL: Hook missing 'trade' parameter")
                return False
        else:
            print("❌ FAIL: on_master_trade is not callable")
            return False
            
    except ImportError as e:
        print(f"❌ FAIL: Could not import on_master_trade: {e}")
        return False
    except Exception as e:
        print(f"❌ FAIL: Error testing on_master_trade: {e}")
        return False


def test_hook_integration_in_broker_manager():
    """Test that broker_manager calls on_master_trade."""
    print("\n" + "="*70)
    print("TEST 3: on_master_trade Integration in Broker Manager")
    print("="*70)
    
    try:
        # Read broker_manager source to verify integration
        broker_manager_path = os.path.join(os.path.dirname(__file__), 'bot', 'broker_manager.py')
        
        with open(broker_manager_path, 'r') as f:
            content = f.read()
        
        # Check for on_master_trade import and call
        has_import = 'from kraken_copy_trading import on_master_trade' in content
        has_call = 'on_master_trade(' in content
        has_hook_comment = 'on_master_trade hook' in content.lower()
        
        print(f"Has import statement: {has_import}")
        print(f"Has function call: {has_call}")
        print(f"Has hook documentation: {has_hook_comment}")
        
        if has_import and has_call:
            print("✅ PASS: on_master_trade properly integrated")
            return True
        else:
            print("❌ FAIL: on_master_trade not properly integrated")
            return False
            
    except Exception as e:
        print(f"❌ FAIL: Error testing broker_manager integration: {e}")
        return False


def test_kraken_copy_only_mode():
    """Test that Kraken users skip independent trading when master is active."""
    print("\n" + "="*70)
    print("TEST 4: Kraken Copy-Only Mode")
    print("="*70)
    
    try:
        # Read independent_broker_trader to verify copy-only logic
        trader_path = os.path.join(os.path.dirname(__file__), 'bot', 'independent_broker_trader.py')
        
        with open(trader_path, 'r') as f:
            content = f.read()
        
        # Check for Kraken copy trading logic
        has_kraken_check = 'broker_type == BrokerType.KRAKEN' in content
        has_master_check = 'kraken_master_connected' in content
        has_skip_logic = 'copy trading active' in content.lower()
        
        print(f"Has Kraken broker check: {has_kraken_check}")
        print(f"Has master connection check: {has_master_check}")
        print(f"Has skip logic for copy trading: {has_skip_logic}")
        
        if has_kraken_check and has_master_check and has_skip_logic:
            print("✅ PASS: Kraken copy-only mode properly implemented")
            return True
        else:
            print("❌ FAIL: Kraken copy-only mode not properly implemented")
            return False
            
    except Exception as e:
        print(f"❌ FAIL: Error testing copy-only mode: {e}")
        return False


def test_copy_trading_exports():
    """Test that kraken_copy_trading exports all necessary functions."""
    print("\n" + "="*70)
    print("TEST 5: Copy Trading Module Exports")
    print("="*70)
    
    try:
        import kraken_copy_trading
        
        required_exports = [
            'on_master_trade',
            'copy_trade_to_kraken_users',
            'initialize_copy_trading_system',
            'KRAKEN_MASTER',
            'KRAKEN_USERS'
        ]
        
        missing = []
        for export in required_exports:
            if hasattr(kraken_copy_trading, export):
                print(f"✅ {export}: Available")
            else:
                print(f"❌ {export}: Missing")
                missing.append(export)
        
        if not missing:
            print("✅ PASS: All required exports available")
            return True
        else:
            print(f"❌ FAIL: Missing exports: {missing}")
            return False
            
    except Exception as e:
        print(f"❌ FAIL: Error testing exports: {e}")
        return False


def run_all_tests():
    """Run all copy trading implementation tests."""
    print("\n" + "="*70)
    print("COPY TRADING IMPLEMENTATION TEST SUITE")
    print("="*70)
    print("Testing the new copy trading architecture...")
    
    results = []
    
    # Run all tests
    results.append(("XRP Blacklist", test_xrp_blacklist()))
    results.append(("on_master_trade Hook", test_on_master_trade_hook_exists()))
    results.append(("Broker Manager Integration", test_hook_integration_in_broker_manager()))
    results.append(("Kraken Copy-Only Mode", test_kraken_copy_only_mode()))
    results.append(("Module Exports", test_copy_trading_exports()))
    
    # Print summary
    print("\n" + "="*70)
    print("TEST SUMMARY")
    print("="*70)
    
    passed = sum(1 for _, result in results if result)
    total = len(results)
    
    for name, result in results:
        status = "✅ PASS" if result else "❌ FAIL"
        print(f"{status}: {name}")
    
    print("="*70)
    print(f"Results: {passed}/{total} tests passed")
    print("="*70)
    
    return passed == total


if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)
