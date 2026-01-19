#!/usr/bin/env python3
"""
Test Railway-Safe Fixes (Jan 19, 2026)
=====================================

Tests the three critical fixes:
1. Kraken balance caching
2. BUSD pair filtering
3. Stop-loss priority over time-based exits
"""

import sys
import os
import time
import subprocess
from unittest.mock import Mock, MagicMock

# Get repository root directory dynamically
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = SCRIPT_DIR
BOT_DIR = os.path.join(REPO_ROOT, 'bot')
TRADING_STRATEGY_PATH = os.path.join(BOT_DIR, 'trading_strategy.py')
KRAKEN_COPY_TRADING_PATH = os.path.join(BOT_DIR, 'kraken_copy_trading.py')
PROCFILE_PATH = os.path.join(REPO_ROOT, 'Procfile')

# Test 1: Balance caching
def test_balance_caching():
    """Test that Kraken balance calls are cached per cycle"""
    print("\n" + "="*70)
    print("TEST 1: Kraken Balance Caching")
    print("="*70)
    
    try:
        from bot.multi_account_broker_manager import MultiAccountBrokerManager
        from bot.broker_manager import BrokerType
        
        manager = MultiAccountBrokerManager()
        
        # Verify cache attributes exist
        assert hasattr(manager, '_balance_cache'), "Missing _balance_cache attribute"
        assert hasattr(manager, '_last_kraken_balance_call'), "Missing _last_kraken_balance_call attribute"
        assert hasattr(manager, 'BALANCE_CACHE_TTL'), "Missing BALANCE_CACHE_TTL constant"
        assert hasattr(manager, 'KRAKEN_BALANCE_CALL_DELAY'), "Missing KRAKEN_BALANCE_CALL_DELAY constant"
        
        # Verify cache methods exist
        assert hasattr(manager, '_get_cached_balance'), "Missing _get_cached_balance method"
        assert hasattr(manager, 'clear_balance_cache'), "Missing clear_balance_cache method"
        
        # Verify cache constants
        assert manager.BALANCE_CACHE_TTL == 120.0, f"Wrong cache TTL: {manager.BALANCE_CACHE_TTL}"
        assert manager.KRAKEN_BALANCE_CALL_DELAY == 1.1, f"Wrong delay: {manager.KRAKEN_BALANCE_CALL_DELAY}"
        
        print("✅ Balance cache structure verified")
        print(f"   - Cache TTL: {manager.BALANCE_CACHE_TTL}s")
        print(f"   - Kraken delay: {manager.KRAKEN_BALANCE_CALL_DELAY}s")
        
        # Test cache clearing
        manager._balance_cache[('test', 'test', BrokerType.KRAKEN)] = (100.0, time.time())
        assert len(manager._balance_cache) == 1, "Cache not populated"
        manager.clear_balance_cache()
        assert len(manager._balance_cache) == 0, "Cache not cleared"
        
        print("✅ Balance cache clearing works")
        
        return True
        
    except Exception as e:
        print(f"❌ FAILED: {e}")
        import traceback
        traceback.print_exc()
        return False


# Test 2: BUSD pair filtering
def test_busd_filtering():
    """Test that BUSD pairs are filtered for Kraken"""
    print("\n" + "="*70)
    print("TEST 2: BUSD Pair Filtering for Kraken")
    print("="*70)
    
    try:
        from bot.broker_manager import KrakenBroker, AccountType
        
        # Create a mock Kraken broker (won't connect, just test logic)
        broker = KrakenBroker(account_type=AccountType.MASTER)
        broker.connected = False  # Prevent actual connection
        
        # Test supports_symbol method
        assert hasattr(broker, 'supports_symbol'), "Missing supports_symbol method"
        
        # Test BUSD rejection
        busd_pairs = ['ETH-BUSD', 'ETH/BUSD', 'BTC-BUSD', 'ETHBUSD', 'BTC.BUSD']
        for symbol in busd_pairs:
            result = broker.supports_symbol(symbol)
            assert result == False, f"BUSD pair should be rejected: {symbol}"
            print(f"✅ Correctly rejects: {symbol}")
        
        # Test valid pairs
        valid_pairs = ['ETH-USD', 'ETH/USD', 'BTC-USDT', 'ETH-USDC']
        for symbol in valid_pairs:
            result = broker.supports_symbol(symbol)
            assert result == True, f"Valid pair should be accepted: {symbol}"
            print(f"✅ Correctly accepts: {symbol}")
        
        print("\n✅ BUSD filtering works correctly")
        return True
        
    except Exception as e:
        print(f"❌ FAILED: {e}")
        import traceback
        traceback.print_exc()
        return False


# Test 3: Stop-loss priority
def test_stop_loss_priority():
    """Test that stop-loss logic executes before time-based exits"""
    print("\n" + "="*70)
    print("TEST 3: Stop-Loss Priority Over Time-Based Exits")
    print("="*70)
    
    try:
        # Read the trading_strategy.py file
        with open(TRADING_STRATEGY_PATH, 'r') as f:
            content = f.read()
        
        # Find the position management section
        # The P&L calculation should come BEFORE time-based exits
        pnl_calc_pos = content.find('pnl_data = active_broker.position_tracker.calculate_pnl(symbol, current_price)')
        time_exit_pos = content.find('EMERGENCY TIME-BASED EXIT: Force exit ALL positions after 12 hours')
        stop_loss_pos = content.find('HARD STOP-LOSS OVERRIDE - ABSOLUTE TOP PRIORITY')
        
        assert pnl_calc_pos > 0, "Could not find P&L calculation"
        assert time_exit_pos > 0, "Could not find time-based exit"
        assert stop_loss_pos > 0, "Could not find stop-loss check"
        
        # Verify order: P&L calc -> Stop-loss -> Time-based exit
        assert pnl_calc_pos < stop_loss_pos, "P&L calculation should come before stop-loss"
        assert stop_loss_pos < time_exit_pos, "Stop-loss should come before time-based exit"
        
        print("✅ Code structure verified:")
        print(f"   1. P&L calculation at position {pnl_calc_pos}")
        print(f"   2. Stop-loss check at position {stop_loss_pos}")
        print(f"   3. Time-based exit at position {time_exit_pos}")
        print("\n✅ Stop-loss priority CORRECT (Railway Golden Rule #5)")
        
        # Verify Railway comment exists
        railway_comment = content.find('Railway Golden Rule #5: Stop-loss > time exit')
        assert railway_comment > 0, "Missing Railway Golden Rule #5 comment"
        print("✅ Railway Golden Rule #5 comment present")
        
        return True
        
    except Exception as e:
        print(f"❌ FAILED: {e}")
        import traceback
        traceback.print_exc()
        return False


# Test 4: Railway-safe practices validation
def test_railway_safe_practices():
    """Validate Railway-safe coding practices"""
    print("\n" + "="*70)
    print("TEST 4: Railway-Safe Practices Validation")
    print("="*70)
    
    try:
        # Check 1: No Docker usage inside app
        result = subprocess.run(
            ['grep', '-r', 'docker', BOT_DIR, '--include=*.py'],
            capture_output=True,
            text=True
        )
        docker_lines = [line for line in result.stdout.split('\n') if line and not line.strip().startswith('#')]
        assert len(docker_lines) == 0, f"Found Docker usage: {docker_lines}"
        print("✅ No Docker usage inside app")
        
        # Check 2: Single process (Procfile)
        with open(PROCFILE_PATH, 'r') as f:
            procfile = f.read()
        assert 'bash start.sh' in procfile, "Procfile doesn't use start.sh"
        assert procfile.count('web:') == 1, "Multiple web processes defined"
        print("✅ Single process configuration")
        
        # Check 3: Position re-sync on startup
        with open(TRADING_STRATEGY_PATH, 'r') as f:
            strategy_content = f.read()
        assert 'sync_with_broker' in strategy_content, "Missing position sync"
        print("✅ Position re-sync on startup present")
        
        # Check 4: Copy trading is in-memory
        with open(KRAKEN_COPY_TRADING_PATH, 'r') as f:
            copy_content = f.read()
        assert 'container' not in copy_content.lower(), "Copy trading uses containers"
        print("✅ Copy trading uses in-memory mirror")
        
        print("\n✅ ALL Railway-safe practices validated")
        return True
        
    except Exception as e:
        print(f"❌ FAILED: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == '__main__':
    print("\n" + "="*70)
    print("RAILWAY-SAFE FIXES VALIDATION (Jan 19, 2026)")
    print("="*70)
    
    results = []
    
    # Run all tests
    results.append(("Balance Caching", test_balance_caching()))
    results.append(("BUSD Filtering", test_busd_filtering()))
    results.append(("Stop-Loss Priority", test_stop_loss_priority()))
    results.append(("Railway Practices", test_railway_safe_practices()))
    
    # Summary
    print("\n" + "="*70)
    print("TEST SUMMARY")
    print("="*70)
    
    passed = sum(1 for _, result in results if result)
    total = len(results)
    
    for name, result in results:
        status = "✅ PASS" if result else "❌ FAIL"
        print(f"{status}: {name}")
    
    print(f"\nTotal: {passed}/{total} tests passed")
    
    if passed == total:
        print("\n🎉 ALL TESTS PASSED - Railway-safe fixes validated!")
        sys.exit(0)
    else:
        print("\n❌ SOME TESTS FAILED - Review failures above")
        sys.exit(1)
