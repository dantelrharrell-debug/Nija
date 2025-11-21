"""
Test script for safe trading stack functionality.
"""

import os
import sys
import tempfile
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

def test_mode_validation():
    """Test MODE validation in config and safety checks."""
    print("\n=== Testing MODE Validation ===")
    
    # Test 1: Default mode should be DRY_RUN
    os.environ.pop('MODE', None)
    os.environ.pop('COINBASE_ACCOUNT_ID', None)
    os.environ.pop('CONFIRM_LIVE', None)
    
    import importlib
    import config
    importlib.reload(config)
    
    print(f"✓ Default MODE: {config.MODE}")
    assert config.MODE == "DRY_RUN", "Default mode should be DRY_RUN"
    
    # Test 2: LIVE mode without COINBASE_ACCOUNT_ID should fail
    os.environ['MODE'] = 'LIVE'
    os.environ.pop('COINBASE_ACCOUNT_ID', None)
    os.environ['CONFIRM_LIVE'] = 'true'
    
    importlib.reload(config)
    from nija_client import check_live_safety
    
    try:
        check_live_safety()
        print("✗ LIVE mode without COINBASE_ACCOUNT_ID should have failed")
        assert False
    except RuntimeError as e:
        print(f"✓ LIVE mode without COINBASE_ACCOUNT_ID correctly rejected: {e}")
    
    # Test 3: LIVE mode without CONFIRM_LIVE should fail
    os.environ['MODE'] = 'LIVE'
    os.environ['COINBASE_ACCOUNT_ID'] = 'test-account-id'
    os.environ.pop('CONFIRM_LIVE', None)
    
    importlib.reload(config)
    importlib.reload(sys.modules['nija_client'])
    from nija_client import check_live_safety
    
    try:
        check_live_safety()
        print("✗ LIVE mode without CONFIRM_LIVE should have failed")
        assert False
    except RuntimeError as e:
        print(f"✓ LIVE mode without CONFIRM_LIVE correctly rejected: {e}")
    
    # Test 4: LIVE mode with all requirements should pass
    os.environ['MODE'] = 'LIVE'
    os.environ['COINBASE_ACCOUNT_ID'] = 'test-account-id'
    os.environ['CONFIRM_LIVE'] = 'true'
    
    importlib.reload(config)
    importlib.reload(sys.modules['nija_client'])
    from nija_client import check_live_safety
    
    try:
        check_live_safety()
        print("✓ LIVE mode with all requirements passed")
    except RuntimeError as e:
        print(f"✗ LIVE mode with requirements failed: {e}")
        assert False
    
    # Test 5: DRY_RUN mode should always pass
    os.environ['MODE'] = 'DRY_RUN'
    os.environ.pop('COINBASE_ACCOUNT_ID', None)
    os.environ.pop('CONFIRM_LIVE', None)
    
    importlib.reload(config)
    importlib.reload(sys.modules['nija_client'])
    from nija_client import check_live_safety
    
    try:
        check_live_safety()
        print("✓ DRY_RUN mode passed without account requirements")
    except RuntimeError as e:
        print(f"✗ DRY_RUN mode failed: {e}")
        assert False
    
    print("\n✅ All MODE validation tests passed!")


def test_safe_order_module():
    """Test safe_order module functionality."""
    print("\n=== Testing Safe Order Module ===")
    
    # Set up test environment
    os.environ['MODE'] = 'DRY_RUN'
    os.environ['MAX_ORDER_USD'] = '50'
    os.environ['MAX_ORDERS_PER_MINUTE'] = '3'
    os.environ['MANUAL_APPROVAL_COUNT'] = '0'
    
    # Use temp directory for logs
    with tempfile.TemporaryDirectory() as tmpdir:
        os.environ['LOG_PATH'] = os.path.join(tmpdir, 'test_trading.log')
        
        import importlib
        import config
        import safe_order
        importlib.reload(config)
        importlib.reload(safe_order)
        
        # Test 1: Order size validation
        print("\nTest 1: Order size validation")
        try:
            safe_order._check_order_size(100)  # Exceeds MAX_ORDER_USD
            print("✗ Should have rejected order size > MAX_ORDER_USD")
            assert False
        except ValueError as e:
            print(f"✓ Order size validation works: {e}")
        
        # Test 2: Order size within limit
        try:
            safe_order._check_order_size(25)  # Within limit
            print("✓ Order size within limit accepted")
        except ValueError as e:
            print(f"✗ Should have accepted order size: {e}")
            assert False
        
        # Test 3: Rate limiting
        print("\nTest 2: Rate limiting")
        for i in range(3):
            try:
                safe_order._check_rate_limit()
                print(f"  ✓ Order {i+1}/3 passed rate limit")
            except RuntimeError as e:
                print(f"  ✗ Order {i+1} failed: {e}")
                assert False
        
        # Fourth order should fail
        try:
            safe_order._check_rate_limit()
            print("✗ Should have rejected 4th order (rate limit)")
            assert False
        except RuntimeError as e:
            print(f"✓ Rate limiting works: {e}")
        
        # Test 4: Audit logging
        print("\nTest 3: Audit logging")
        safe_order._audit_log("test_event", {"test": "data"})
        
        log_path = Path(os.environ['LOG_PATH'])
        assert log_path.exists(), "Log file should be created"
        
        with open(log_path, 'r') as f:
            log_content = f.read()
            assert "test_event" in log_content, "Log should contain event type"
            assert "test" in log_content, "Log should contain event data"
            print(f"✓ Audit logging works, log created at {log_path}")
        
        print("\n✅ All safe order tests passed!")


def test_webhook_signature():
    """Test TradingView webhook signature verification."""
    print("\n=== Testing Webhook Signature Verification ===")
    
    import hmac
    import hashlib
    
    # Set up test environment
    os.environ['TRADINGVIEW_WEBHOOK_SECRET'] = 'test_secret_123'
    
    import importlib
    import config
    import tv_webhook
    importlib.reload(config)
    importlib.reload(tv_webhook)
    
    # Test 1: Valid signature
    payload = b'{"test": "data"}'
    secret = 'test_secret_123'
    signature = hmac.new(secret.encode('utf-8'), payload, hashlib.sha256).hexdigest()
    
    is_valid = tv_webhook.verify_signature(payload, signature)
    assert is_valid, "Valid signature should pass verification"
    print(f"✓ Valid signature verified successfully")
    
    # Test 2: Invalid signature
    invalid_signature = 'invalid_signature_hash'
    is_valid = tv_webhook.verify_signature(payload, invalid_signature)
    assert not is_valid, "Invalid signature should fail verification"
    print(f"✓ Invalid signature correctly rejected")
    
    # Test 3: Missing signature
    is_valid = tv_webhook.verify_signature(payload, '')
    assert not is_valid, "Missing signature should fail verification"
    print(f"✓ Missing signature correctly rejected")
    
    print("\n✅ All webhook signature tests passed!")


if __name__ == '__main__':
    try:
        test_mode_validation()
        test_safe_order_module()
        test_webhook_signature()
        
        print("\n" + "="*50)
        print("🎉 ALL TESTS PASSED!")
        print("="*50 + "\n")
        
    except Exception as e:
        print(f"\n❌ Test failed with error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
