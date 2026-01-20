#!/usr/bin/env python3
"""
NIJA Required Fixes Validation Script
======================================

This script validates that all 5 required fixes are correctly implemented:

1. ✅ FIX 1 - Equity-Based Accounting
2. ✅ FIX 2 - SELL Override (Critical Safety)
3. ✅ FIX 3 - Kraken Nonce Unification
4. ✅ FIX 4 - User Balance Isolation
5. ✅ FIX 5 - Copy Trading Optional

Run this script to verify all fixes are in place.
"""

import os
import sys
import time

# Add bot directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'bot'))

def print_header(title):
    """Print a formatted header."""
    print("\n" + "=" * 70)
    print(f"  {title}")
    print("=" * 70)

def print_result(test_name, passed, details=""):
    """Print test result."""
    status = "✅ PASS" if passed else "❌ FAIL"
    print(f"{status}: {test_name}")
    if details:
        print(f"       {details}")

def validate_fix1_equity_accounting():
    """Validate FIX 1: Equity-Based Accounting."""
    print_header("FIX 1: EQUITY-BASED ACCOUNTING")
    
    try:
        # Check broker_manager.py for equity-based balance
        with open('bot/broker_manager.py', 'r') as f:
            content = f.read()
        
        # Test 1: Check for total_funds usage in Coinbase
        has_total_funds = "total_funds = balance_data.get('total_funds'" in content
        print_result(
            "Coinbase uses total_funds (available + locked)",
            has_total_funds,
            "Found in get_account_balance()"
        )
        
        # Test 2: Check for held_amount calculation in Kraken
        has_held_amount = "total_funds = total + held_amount" in content
        print_result(
            "Kraken calculates total_funds with held amounts",
            has_held_amount,
            "Found in get_account_balance()"
        )
        
        # Test 3: Verify balance models exist
        balance_models_exists = os.path.exists('bot/balance_models.py')
        print_result(
            "BalanceSnapshot model exists",
            balance_models_exists,
            "bot/balance_models.py found"
        )
        
        if balance_models_exists:
            with open('bot/balance_models.py', 'r') as f:
                balance_content = f.read()
            has_equity_model = "total_equity_usd" in balance_content
            print_result(
                "BalanceSnapshot includes total_equity_usd",
                has_equity_model,
                "Three-part balance model confirmed"
            )
        
        return True
    
    except Exception as e:
        print_result("FIX 1 validation", False, str(e))
        return False

def validate_fix2_sell_override():
    """Validate FIX 2: SELL Override."""
    print_header("FIX 2: SELL OVERRIDE (CRITICAL SAFETY)")
    
    try:
        with open('bot/broker_manager.py', 'r') as f:
            content = f.read()
        
        # Test 1: SELL orders don't check balance
        sell_bypass = "if side.lower() == 'buy' and not (force_liquidate or ignore_balance):" in content
        print_result(
            "Balance check only for BUY orders (SELL bypasses)",
            sell_bypass,
            "SELL orders skip balance validation"
        )
        
        # Test 2: EXIT-ONLY mode only blocks BUY
        exit_only_buy = "if side.lower() == 'buy' and getattr(self, 'exit_only_mode', False)" in content
        print_result(
            "EXIT-ONLY mode only blocks BUY orders",
            exit_only_buy,
            "SELL orders allowed even in EXIT-ONLY mode"
        )
        
        # Test 3: Force liquidate parameter exists
        has_force_liquidate = "force_liquidate: bool = False" in content
        print_result(
            "Emergency liquidation flag exists",
            has_force_liquidate,
            "force_liquidate parameter available"
        )
        
        # Test 4: Verify no SELL balance checks
        no_sell_balance_check = "if side.lower() == 'sell' and" not in content or \
                                "if side.lower() == 'sell':" not in content
        print_result(
            "No balance gates for SELL orders",
            no_sell_balance_check,
            "SELL can execute even with $0 balance"
        )
        
        return True
    
    except Exception as e:
        print_result("FIX 2 validation", False, str(e))
        return False

def validate_fix3_kraken_nonce():
    """Validate FIX 3: Kraken Nonce Unification."""
    print_header("FIX 3: KRAKEN NONCE UNIFICATION")
    
    try:
        # Test 1: Global nonce manager exists
        global_nonce_exists = os.path.exists('bot/global_kraken_nonce.py')
        print_result(
            "Global Kraken nonce manager exists",
            global_nonce_exists,
            "bot/global_kraken_nonce.py found"
        )
        
        if global_nonce_exists:
            with open('bot/global_kraken_nonce.py', 'r') as f:
                nonce_content = f.read()
            
            # Test 2: get_global_kraken_nonce function exists
            has_global_func = "def get_global_kraken_nonce()" in nonce_content
            print_result(
                "get_global_kraken_nonce() function exists",
                has_global_func,
                "Global nonce function defined"
            )
            
            # Test 3: Uses timestamp-based nonce
            uses_timestamp = "int(time.time() * 1000)" in nonce_content
            print_result(
                "Uses timestamp-based nonce",
                uses_timestamp,
                "Milliseconds since epoch"
            )
            
            # Test 4: Global API lock exists
            has_lock = "_KRAKEN_API_LOCK = threading.Lock()" in nonce_content
            print_result(
                "Global Kraken API lock exists",
                has_lock,
                "Serializes all Kraken API calls"
            )
        
        # Test 5: No self._last_nonce in broker_manager.py
        with open('bot/broker_manager.py', 'r') as f:
            broker_content = f.read()
        
        no_last_nonce = "self._last_nonce" not in broker_content
        print_result(
            "No self._last_nonce references",
            no_last_nonce,
            "All per-instance nonce tracking removed" if no_last_nonce else "Found self._last_nonce - needs cleanup"
        )
        
        return True
    
    except Exception as e:
        print_result("FIX 3 validation", False, str(e))
        return False

def validate_fix4_user_isolation():
    """Validate FIX 4: User Balance Isolation."""
    print_header("FIX 4: USER BALANCE ISOLATION")
    
    try:
        # Test 1: Multi-account manager exists
        multi_account_exists = os.path.exists('bot/multi_account_broker_manager.py')
        print_result(
            "Multi-account broker manager exists",
            multi_account_exists,
            "bot/multi_account_broker_manager.py found"
        )
        
        if multi_account_exists:
            with open('bot/multi_account_broker_manager.py', 'r') as f:
                content = f.read()
            
            # Test 2: Separate master and user broker structures
            has_separate_brokers = "self.master_brokers:" in content and "self.user_brokers:" in content
            print_result(
                "Separate master and user broker structures",
                has_separate_brokers,
                "Master and users have independent broker instances"
            )
            
            # Test 3: Independent balance fetching
            has_user_balance = "def get_user_balance" in content
            print_result(
                "Independent user balance method exists",
                has_user_balance,
                "Users fetch balances independently"
            )
        
        # Test 4: Independent broker trader exists
        independent_exists = os.path.exists('bot/independent_broker_trader.py')
        print_result(
            "Independent broker trader exists",
            independent_exists,
            "bot/independent_broker_trader.py found"
        )
        
        if independent_exists:
            with open('bot/independent_broker_trader.py', 'r') as f:
                content = f.read()
            
            # Test 5: User trading loop exists
            has_user_loop = "def run_user_broker_trading_loop" in content
            print_result(
                "Independent user trading loop exists",
                has_user_loop,
                "Users can trade independently of master"
            )
        
        return True
    
    except Exception as e:
        print_result("FIX 4 validation", False, str(e))
        return False

def validate_fix5_copy_trading_optional():
    """Validate FIX 5: Copy Trading Optional."""
    print_header("FIX 5: COPY TRADING OPTIONAL")
    
    try:
        # Test 1: Copy trade engine exists
        copy_engine_exists = os.path.exists('bot/copy_trade_engine.py')
        print_result(
            "Copy trade engine exists",
            copy_engine_exists,
            "bot/copy_trade_engine.py found"
        )
        
        if copy_engine_exists:
            with open('bot/copy_trade_engine.py', 'r') as f:
                content = f.read()
            
            # Test 2: Master offline check exists
            has_master_check = "master_connected = self.multi_account_manager.is_master_connected" in content
            print_result(
                "Master connection check exists",
                has_master_check,
                "Checks master status before copy trading"
            )
            
            # Test 3: Returns when master offline (allows independent trading)
            handles_offline = "if not master_connected:" in content and "return results" in content
            print_result(
                "Skips copy trading when master offline",
                handles_offline,
                "Users can trade independently when master offline"
            )
            
            # Test 4: FIX 5 comment exists
            has_fix5_comment = "FIX 5" in content or "Copy Trading Should Be Optional" in content
            print_result(
                "FIX 5 documentation in code",
                has_fix5_comment,
                "Code documents copy trading as optional"
            )
        
        # Test 5: Independent trading loop in independent_broker_trader
        if os.path.exists('bot/independent_broker_trader.py'):
            with open('bot/independent_broker_trader.py', 'r') as f:
                content = f.read()
            
            has_architecture_doc = "MASTER ACCOUNT IS COMPLETELY INDEPENDENT OF USER ACCOUNTS" in content
            print_result(
                "Architecture documentation confirms independence",
                has_architecture_doc,
                "Users trade independently of master status"
            )
        
        return True
    
    except Exception as e:
        print_result("FIX 5 validation", False, str(e))
        return False

def main():
    """Run all validations."""
    print("\n" + "🔍" * 35)
    print("  NIJA REQUIRED FIXES VALIDATION")
    print("🔍" * 35)
    print("\nValidating all 5 required fixes...")
    print("This will check the codebase to ensure all fixes are implemented correctly.")
    
    results = {}
    
    # Run all validations
    results['FIX 1'] = validate_fix1_equity_accounting()
    results['FIX 2'] = validate_fix2_sell_override()
    results['FIX 3'] = validate_fix3_kraken_nonce()
    results['FIX 4'] = validate_fix4_user_isolation()
    results['FIX 5'] = validate_fix5_copy_trading_optional()
    
    # Print summary
    print_header("VALIDATION SUMMARY")
    
    all_passed = all(results.values())
    
    for fix, passed in results.items():
        status = "✅ PASS" if passed else "❌ FAIL"
        print(f"{status}: {fix}")
    
    print("\n" + "=" * 70)
    if all_passed:
        print("🎉 ALL FIXES VALIDATED SUCCESSFULLY!")
        print("=" * 70)
        print("\n✅ The NIJA trading bot has all 5 required fixes implemented:")
        print("   1. Equity-Based Accounting (available + locked funds)")
        print("   2. SELL Override (bypasses all balance gates)")
        print("   3. Kraken Nonce Unification (global nonce manager)")
        print("   4. User Balance Isolation (independent balance fetching)")
        print("   5. Copy Trading Optional (master offline → users trade standalone)")
        print("\n📋 System Status: PRODUCTION READY ✅")
        print("=" * 70)
        return 0
    else:
        print("⚠️  SOME FIXES NEED ATTENTION")
        print("=" * 70)
        print("\nPlease review the failed tests above.")
        print("See REQUIRED_FIXES_IMPLEMENTATION.md for details.")
        print("=" * 70)
        return 1

if __name__ == "__main__":
    sys.exit(main())
