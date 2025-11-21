#!/usr/bin/env python3
"""
Test safe trading stack implementation

This test validates:
- config.py has all required variables
- safe_order.py module loads correctly
- tv_webhook.py blueprint can be imported
- nija_client.py safety checks work
"""

import os
import sys

def test_config_module():
    """Test that config module has all required variables"""
    print("Testing config module...")
    from config import (
        MODE, 
        COINBASE_ACCOUNT_ID, 
        CONFIRM_LIVE,
        MAX_ORDER_USD,
        MAX_ORDERS_PER_MINUTE,
        MANUAL_APPROVAL_COUNT,
        LOG_PATH,
        TRADINGVIEW_WEBHOOK_SECRET,
        COINBASE_API_BASE,
        MIN_TRADE_PERCENT,
        MAX_TRADE_PERCENT
    )
    
    assert MODE in ['SANDBOX', 'DRY_RUN', 'LIVE'], f"Invalid MODE: {MODE}"
    assert isinstance(MAX_ORDER_USD, float), "MAX_ORDER_USD should be float"
    assert isinstance(MAX_ORDERS_PER_MINUTE, int), "MAX_ORDERS_PER_MINUTE should be int"
    assert isinstance(MANUAL_APPROVAL_COUNT, int), "MANUAL_APPROVAL_COUNT should be int"
    
    print(f"✅ Config module OK - MODE={MODE}, MAX_ORDER_USD=${MAX_ORDER_USD}")
    return True

def test_safe_order_module():
    """Test that safe_order module loads"""
    print("Testing safe_order module...")
    
    import safe_order
    
    # Check that key functions exist
    assert hasattr(safe_order, 'submit_order'), "submit_order function missing"
    assert callable(safe_order.submit_order), "submit_order is not callable"
    
    print("✅ safe_order module OK")
    return True

def test_tv_webhook_module():
    """Test that tv_webhook module loads"""
    print("Testing tv_webhook module...")
    
    from tv_webhook import tv_webhook_bp, verify_signature
    
    assert tv_webhook_bp is not None, "tv_webhook_bp is None"
    assert callable(verify_signature), "verify_signature is not callable"
    
    print("✅ tv_webhook module OK")
    return True

def test_nija_client_safety():
    """Test that nija_client has safety checks"""
    print("Testing nija_client safety checks...")
    
    # Set safe env vars for testing
    os.environ['MODE'] = 'DRY_RUN'
    
    # Re-import to pick up env changes
    if 'config' in sys.modules:
        del sys.modules['config']
    if 'nija_client' in sys.modules:
        del sys.modules['nija_client']
    
    import nija_client
    
    # Check that check_live_safety exists
    assert hasattr(nija_client, 'check_live_safety'), "check_live_safety function missing"
    assert callable(nija_client.check_live_safety), "check_live_safety is not callable"
    
    # Test that it works in DRY_RUN mode
    try:
        nija_client.check_live_safety()
        print("✅ nija_client safety checks OK")
        return True
    except Exception as e:
        print(f"❌ Safety check failed: {e}")
        return False

def test_live_mode_safety():
    """Test that LIVE mode requires proper configuration"""
    print("Testing LIVE mode safety...")
    
    # Set LIVE mode without proper config
    os.environ['MODE'] = 'LIVE'
    os.environ['COINBASE_ACCOUNT_ID'] = ''
    os.environ['CONFIRM_LIVE'] = 'false'
    
    # Re-import to pick up env changes
    if 'config' in sys.modules:
        del sys.modules['config']
    if 'nija_client' in sys.modules:
        del sys.modules['nija_client']
    
    import nija_client
    
    # Should raise RuntimeError
    try:
        nija_client.check_live_safety()
        print("❌ LIVE mode safety check failed - should have raised error")
        return False
    except RuntimeError as e:
        if 'COINBASE_ACCOUNT_ID' in str(e):
            print("✅ LIVE mode safety check OK - correctly requires COINBASE_ACCOUNT_ID")
            return True
        else:
            print(f"❌ Wrong error: {e}")
            return False

def main():
    """Run all tests"""
    print("=" * 60)
    print("Safe Trading Stack Tests")
    print("=" * 60)
    
    tests = [
        test_config_module,
        test_safe_order_module,
        test_tv_webhook_module,
        test_nija_client_safety,
        test_live_mode_safety,
    ]
    
    passed = 0
    failed = 0
    
    for test in tests:
        try:
            if test():
                passed += 1
            else:
                failed += 1
        except Exception as e:
            print(f"❌ {test.__name__} raised exception: {e}")
            import traceback
            traceback.print_exc()
            failed += 1
        print()
    
    print("=" * 60)
    print(f"Results: {passed} passed, {failed} failed")
    print("=" * 60)
    
    return failed == 0

if __name__ == '__main__':
    success = main()
    sys.exit(0 if success else 1)
