#!/usr/bin/env python3
"""
Integration test for user balance visibility and observe mode.

This script validates:
1. User configuration files are properly set with enabled=true
2. audit_user_accounts() method exists and works
3. Copy engine observe mode is properly implemented
4. Global functions support observe_only parameter
"""

import sys
import os
import json
import logging

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)s | %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)

logger = logging.getLogger("test")


def test_user_configs():
    """Verify user configuration files have users marked as enabled."""
    logger.info("=" * 70)
    logger.info("TEST: User Configuration Files")
    logger.info("=" * 70)
    
    config_dir = os.path.join(os.path.dirname(__file__), 'config', 'users')
    
    if not os.path.exists(config_dir):
        logger.error(f"❌ Config directory not found: {config_dir}")
        return False
    
    config_files = [
        'retail_kraken.json',
        'investor_kraken.json',
        'retail_alpaca.json',
        'investor_alpaca.json',
        'retail_coinbase.json',
        'investor_coinbase.json'
    ]
    
    total_users = 0
    enabled_users = 0
    
    for filename in config_files:
        filepath = os.path.join(config_dir, filename)
        
        if not os.path.exists(filepath):
            logger.info(f"⚪ {filename}: Not found (optional)")
            continue
        
        try:
            with open(filepath, 'r') as f:
                users = json.load(f)
            
            if not users:
                logger.info(f"⚪ {filename}: Empty")
                continue
            
            logger.info(f"\n📋 {filename}:")
            for user in users:
                user_id = user.get('user_id', 'unknown')
                name = user.get('name', 'Unknown')
                enabled = user.get('enabled', False)
                
                total_users += 1
                if enabled:
                    enabled_users += 1
                    logger.info(f"   ✅ {name} ({user_id}) - ENABLED")
                else:
                    logger.info(f"   ⚪ {name} ({user_id}) - DISABLED")
                    
        except Exception as e:
            logger.error(f"❌ Error reading {filename}: {e}")
            return False
    
    logger.info("")
    logger.info(f"📊 Total users: {total_users}")
    logger.info(f"📊 Enabled users: {enabled_users}")
    
    if total_users == 0:
        logger.warning("⚠️  No users configured in any files")
        return True  # Not an error, just no users
    
    if enabled_users == 0:
        logger.error("❌ Users exist but none are enabled!")
        return False
    
    logger.info("✅ User configurations validated")
    return True


def test_audit_function():
    """Test that audit_user_accounts function exists and is callable."""
    logger.info("\n" + "=" * 70)
    logger.info("TEST: audit_user_accounts() Function")
    logger.info("=" * 70)
    
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'bot'))
    
    try:
        from multi_account_broker_manager import MultiAccountBrokerManager
        
        manager = MultiAccountBrokerManager()
        
        # Check method exists
        if not hasattr(manager, 'audit_user_accounts'):
            logger.error("❌ audit_user_accounts method not found")
            return False
        
        # Check it's callable
        if not callable(manager.audit_user_accounts):
            logger.error("❌ audit_user_accounts is not callable")
            return False
        
        logger.info("✅ audit_user_accounts method exists and is callable")
        
        # Try calling it (should work even with no users)
        logger.info("\nTesting audit with no users:")
        manager.audit_user_accounts()
        
        logger.info("✅ audit_user_accounts executed successfully")
        return True
        
    except Exception as e:
        logger.error(f"❌ Test failed: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return False


def test_observe_mode_implementation():
    """Test CopyTradeEngine observe mode implementation."""
    logger.info("\n" + "=" * 70)
    logger.info("TEST: CopyTradeEngine Observe Mode")
    logger.info("=" * 70)
    
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'bot'))
    
    try:
        from copy_trade_engine import CopyTradeEngine
        
        # Test 1: Create engine in observe mode
        logger.info("\n1. Creating engine with observe_only=True...")
        engine_observe = CopyTradeEngine(observe_only=True)
        
        if not hasattr(engine_observe, 'observe_only'):
            logger.error("❌ Engine missing observe_only attribute")
            return False
        
        if engine_observe.observe_only != True:
            logger.error(f"❌ observe_only should be True, got {engine_observe.observe_only}")
            return False
        
        logger.info("✅ Engine created with observe_only=True")
        
        # Test 2: Check stats include observe mode
        stats = engine_observe.get_stats()
        
        if 'observe_only' not in stats:
            logger.error("❌ Stats missing observe_only field")
            return False
        
        if stats['observe_only'] != True:
            logger.error(f"❌ Stats observe_only should be True, got {stats['observe_only']}")
            return False
        
        logger.info("✅ Stats correctly report observe_only=True")
        
        # Test 3: Create engine in normal mode
        logger.info("\n2. Creating engine with observe_only=False...")
        engine_normal = CopyTradeEngine(observe_only=False)
        
        if engine_normal.observe_only != False:
            logger.error(f"❌ observe_only should be False, got {engine_normal.observe_only}")
            return False
        
        logger.info("✅ Engine created with observe_only=False")
        
        # Test 4: Check normal mode stats
        stats_normal = engine_normal.get_stats()
        
        if stats_normal['observe_only'] != False:
            logger.error(f"❌ Stats observe_only should be False, got {stats_normal['observe_only']}")
            return False
        
        logger.info("✅ Stats correctly report observe_only=False")
        
        # Test 5: Verify observe mode has signals counter
        if 'total_signals_observed' not in stats:
            logger.error("❌ Observe mode stats missing total_signals_observed")
            return False
        
        logger.info("✅ Observe mode stats include total_signals_observed")
        
        # Test 6: Verify normal mode has trade counters
        if 'total_trades_copied' not in stats_normal:
            logger.error("❌ Normal mode stats missing total_trades_copied")
            return False
        
        logger.info("✅ Normal mode stats include total_trades_copied")
        
        return True
        
    except Exception as e:
        logger.error(f"❌ Test failed: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return False


def test_global_functions():
    """Test global copy engine functions support observe_only."""
    logger.info("\n" + "=" * 70)
    logger.info("TEST: Global Function Parameters")
    logger.info("=" * 70)
    
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'bot'))
    
    try:
        import inspect
        from copy_trade_engine import start_copy_engine, get_copy_engine
        
        # Test start_copy_engine signature
        logger.info("\n1. Checking start_copy_engine signature...")
        sig = inspect.signature(start_copy_engine)
        params = sig.parameters
        
        if 'observe_only' not in params:
            logger.error("❌ start_copy_engine missing observe_only parameter")
            return False
        
        logger.info("✅ start_copy_engine has observe_only parameter")
        
        # Check default value
        default = params['observe_only'].default
        if default != False:
            logger.error(f"❌ observe_only default should be False, got {default}")
            return False
        
        logger.info("✅ observe_only defaults to False (backward compatible)")
        
        # Test get_copy_engine signature
        logger.info("\n2. Checking get_copy_engine signature...")
        sig2 = inspect.signature(get_copy_engine)
        params2 = sig2.parameters
        
        if 'observe_only' not in params2:
            logger.error("❌ get_copy_engine missing observe_only parameter")
            return False
        
        logger.info("✅ get_copy_engine has observe_only parameter")
        
        return True
        
    except Exception as e:
        logger.error(f"❌ Test failed: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return False


def main():
    """Run all validation tests."""
    logger.info("=" * 70)
    logger.info("🧪 USER BALANCE VISIBILITY & OBSERVE MODE VALIDATION")
    logger.info("=" * 70)
    
    tests = [
        ("User Configuration Files", test_user_configs),
        ("audit_user_accounts() Function", test_audit_function),
        ("CopyTradeEngine Observe Mode", test_observe_mode_implementation),
        ("Global Function Parameters", test_global_functions),
    ]
    
    results = []
    for test_name, test_func in tests:
        try:
            result = test_func()
            results.append((test_name, result))
        except Exception as e:
            logger.error(f"❌ Test '{test_name}' crashed: {e}")
            import traceback
            logger.error(traceback.format_exc())
            results.append((test_name, False))
    
    # Summary
    logger.info("\n" + "=" * 70)
    logger.info("📊 VALIDATION SUMMARY")
    logger.info("=" * 70)
    
    passed = sum(1 for _, result in results if result)
    total = len(results)
    
    for test_name, result in results:
        status = "✅ PASS" if result else "❌ FAIL"
        logger.info(f"{status}: {test_name}")
    
    logger.info("")
    logger.info(f"Results: {passed}/{total} tests passed")
    logger.info("=" * 70)
    
    if passed == total:
        logger.info("")
        logger.info("🎉 ALL VALIDATIONS PASSED!")
        logger.info("")
        logger.info("Summary of changes:")
        logger.info("  ✅ User balance audit function implemented")
        logger.info("  ✅ Copy engine observe mode implemented")
        logger.info("  ✅ Users marked as enabled in config files")
        logger.info("  ✅ Global functions support observe_only parameter")
        logger.info("")
        logger.info("Next steps:")
        logger.info("  1. Deploy to production")
        logger.info("  2. Verify user balances appear in logs")
        logger.info("  3. Confirm observe mode logs signals without trading")
        logger.info("  4. When ready, change observe_only=False to enable trading")
        logger.info("=" * 70)
        return 0
    else:
        logger.error(f"\n❌ {total - passed} validation(s) failed")
        return 1


if __name__ == "__main__":
    sys.exit(main())
