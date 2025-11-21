"""
Tests for safe trading stack functionality

Tests cover:
- Config module environment variable parsing
- Safety checks in nija_client
- Safe order module rate limiting and validation
- TradingView webhook signature verification
"""

import os
import sys
import json
import hmac
import hashlib
import tempfile
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_config_mode_parsing():
    """Test that MODE is parsed correctly from environment"""
    # Save original
    original_mode = os.environ.get('MODE')
    
    try:
        # Test default
        if 'MODE' in os.environ:
            del os.environ['MODE']
        
        import importlib
        import config
        importlib.reload(config)
        
        assert config.MODE == 'DRY_RUN', f"Default MODE should be DRY_RUN, got {config.MODE}"
        print("✅ Config MODE defaults to DRY_RUN")
        
        # Test explicit values
        for mode in ['SANDBOX', 'DRY_RUN', 'LIVE']:
            os.environ['MODE'] = mode.lower()
            importlib.reload(config)
            assert config.MODE == mode, f"MODE should be {mode}, got {config.MODE}"
            print(f"✅ Config MODE={mode} parsed correctly")
        
    finally:
        # Restore
        if original_mode:
            os.environ['MODE'] = original_mode
        elif 'MODE' in os.environ:
            del os.environ['MODE']


def test_config_numeric_parsing():
    """Test that numeric config values are parsed correctly"""
    import config
    
    assert isinstance(config.MAX_ORDER_USD, float), "MAX_ORDER_USD should be float"
    assert isinstance(config.MAX_ORDERS_PER_MINUTE, int), "MAX_ORDERS_PER_MINUTE should be int"
    assert isinstance(config.MANUAL_APPROVAL_COUNT, int), "MANUAL_APPROVAL_COUNT should be int"
    
    print("✅ Config numeric values parsed correctly")


def test_safety_checks_dry_run():
    """Test safety checks pass in DRY_RUN mode"""
    original_mode = os.environ.get('MODE')
    
    try:
        os.environ['MODE'] = 'DRY_RUN'
        
        import importlib
        import config
        import nija_client
        importlib.reload(config)
        importlib.reload(nija_client)
        
        # Should not raise
        nija_client.check_live_safety()
        print("✅ Safety checks pass in DRY_RUN mode")
        
    finally:
        if original_mode:
            os.environ['MODE'] = original_mode
        elif 'MODE' in os.environ:
            del os.environ['MODE']


def test_safety_checks_live_mode_rejects_missing_account():
    """Test that LIVE mode requires COINBASE_ACCOUNT_ID"""
    original_mode = os.environ.get('MODE')
    original_account = os.environ.get('COINBASE_ACCOUNT_ID')
    original_confirm = os.environ.get('CONFIRM_LIVE')
    
    try:
        os.environ['MODE'] = 'LIVE'
        os.environ['COINBASE_ACCOUNT_ID'] = ''
        os.environ['CONFIRM_LIVE'] = 'false'
        
        import importlib
        import config
        import nija_client
        importlib.reload(config)
        importlib.reload(nija_client)
        
        # Should raise RuntimeError
        try:
            nija_client.check_live_safety()
            assert False, "Should have raised RuntimeError for missing COINBASE_ACCOUNT_ID"
        except RuntimeError as e:
            assert 'COINBASE_ACCOUNT_ID' in str(e)
            print("✅ Safety checks reject LIVE mode without COINBASE_ACCOUNT_ID")
        
    finally:
        if original_mode:
            os.environ['MODE'] = original_mode
        elif 'MODE' in os.environ:
            del os.environ['MODE']
        if original_account:
            os.environ['COINBASE_ACCOUNT_ID'] = original_account
        elif 'COINBASE_ACCOUNT_ID' in os.environ:
            del os.environ['COINBASE_ACCOUNT_ID']
        if original_confirm:
            os.environ['CONFIRM_LIVE'] = original_confirm
        elif 'CONFIRM_LIVE' in os.environ:
            del os.environ['CONFIRM_LIVE']


def test_safety_checks_live_mode_rejects_missing_confirm():
    """Test that LIVE mode requires CONFIRM_LIVE=true"""
    original_mode = os.environ.get('MODE')
    original_account = os.environ.get('COINBASE_ACCOUNT_ID')
    original_confirm = os.environ.get('CONFIRM_LIVE')
    
    try:
        os.environ['MODE'] = 'LIVE'
        os.environ['COINBASE_ACCOUNT_ID'] = 'test-account-id'
        os.environ['CONFIRM_LIVE'] = 'false'
        
        import importlib
        import config
        import nija_client
        importlib.reload(config)
        importlib.reload(nija_client)
        
        # Should raise RuntimeError
        try:
            nija_client.check_live_safety()
            assert False, "Should have raised RuntimeError for CONFIRM_LIVE=false"
        except RuntimeError as e:
            assert 'CONFIRM_LIVE' in str(e)
            print("✅ Safety checks reject LIVE mode without CONFIRM_LIVE=true")
        
    finally:
        if original_mode:
            os.environ['MODE'] = original_mode
        elif 'MODE' in os.environ:
            del os.environ['MODE']
        if original_account:
            os.environ['COINBASE_ACCOUNT_ID'] = original_account
        elif 'COINBASE_ACCOUNT_ID' in os.environ:
            del os.environ['COINBASE_ACCOUNT_ID']
        if original_confirm:
            os.environ['CONFIRM_LIVE'] = original_confirm
        elif 'CONFIRM_LIVE' in os.environ:
            del os.environ['CONFIRM_LIVE']


def test_rate_limiter():
    """Test rate limiter functionality"""
    from safe_order import RateLimiter
    
    limiter = RateLimiter(max_per_minute=3)
    
    # Should allow first 3 orders
    assert limiter.can_place_order(), "Should allow first order"
    limiter.record_order()
    
    assert limiter.can_place_order(), "Should allow second order"
    limiter.record_order()
    
    assert limiter.can_place_order(), "Should allow third order"
    limiter.record_order()
    
    # Should reject 4th order
    assert not limiter.can_place_order(), "Should reject 4th order within rate limit"
    
    print("✅ Rate limiter enforces MAX_ORDERS_PER_MINUTE")


def test_safe_order_validates_size():
    """Test that safe order module validates order size"""
    # Set a low MAX_ORDER_USD for testing
    original_max = os.environ.get('MAX_ORDER_USD')
    original_mode = os.environ.get('MODE')
    original_account = os.environ.get('COINBASE_ACCOUNT_ID')
    
    os.environ['MAX_ORDER_USD'] = '50.0'
    os.environ['MODE'] = 'DRY_RUN'
    os.environ['COINBASE_ACCOUNT_ID'] = 'test-account'
    
    try:
        import importlib
        import config
        importlib.reload(config)
        from safe_order import SafeOrderManager
        
        manager = SafeOrderManager()
        
        # Valid order
        is_valid, error = manager.validate_order("BTC-USD", "buy", 40.0)
        assert is_valid, f"Order under limit should be valid, error: {error}"
        
        # Invalid order (too large)
        is_valid, error = manager.validate_order("BTC-USD", "buy", 60.0)
        assert not is_valid, "Order over limit should be invalid"
        assert "MAX_ORDER_USD" in error
        
        print("✅ Safe order validates MAX_ORDER_USD")
        
    finally:
        if original_max:
            os.environ['MAX_ORDER_USD'] = original_max
        elif 'MAX_ORDER_USD' in os.environ:
            del os.environ['MAX_ORDER_USD']
        if original_mode:
            os.environ['MODE'] = original_mode
        elif 'MODE' in os.environ:
            del os.environ['MODE']
        if original_account:
            os.environ['COINBASE_ACCOUNT_ID'] = original_account
        elif 'COINBASE_ACCOUNT_ID' in os.environ:
            del os.environ['COINBASE_ACCOUNT_ID']


def test_webhook_signature_verification():
    """Test TradingView webhook HMAC signature verification"""
    from tradingview_webhook import verify_signature
    
    secret = "test_secret_123"
    
    # Save original and set test secret
    original_secret = os.environ.get('TRADINGVIEW_WEBHOOK_SECRET')
    os.environ['TRADINGVIEW_WEBHOOK_SECRET'] = secret
    
    try:
        import importlib
        import config
        import tradingview_webhook
        importlib.reload(config)
        importlib.reload(tradingview_webhook)
        
        # Test valid signature
        payload = b'{"symbol":"BTC-USD","side":"buy","size_usd":100}'
        expected_sig = hmac.new(secret.encode('utf-8'), payload, hashlib.sha256).hexdigest()
        
        assert verify_signature(payload, expected_sig), "Valid signature should be accepted"
        print("✅ Webhook accepts valid HMAC signature")
        
        # Test invalid signature
        invalid_sig = "invalid_signature_123"
        assert not verify_signature(payload, invalid_sig), "Invalid signature should be rejected"
        print("✅ Webhook rejects invalid HMAC signature")
        
        # Test missing signature
        assert not verify_signature(payload, ""), "Empty signature should be rejected"
        print("✅ Webhook rejects empty signature")
        
    finally:
        if original_secret:
            os.environ['TRADINGVIEW_WEBHOOK_SECRET'] = original_secret
        elif 'TRADINGVIEW_WEBHOOK_SECRET' in os.environ:
            del os.environ['TRADINGVIEW_WEBHOOK_SECRET']


def test_audit_logging():
    """Test that safe order module creates audit logs"""
    import tempfile
    import importlib
    
    # Create temporary log file
    with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.log') as f:
        log_path = f.name
    
    original_log = os.environ.get('LOG_PATH')
    original_mode = os.environ.get('MODE')
    original_account = os.environ.get('COINBASE_ACCOUNT_ID')
    
    os.environ['LOG_PATH'] = log_path
    os.environ['MODE'] = 'DRY_RUN'
    os.environ['COINBASE_ACCOUNT_ID'] = 'test-account'
    
    try:
        import config
        importlib.reload(config)
        from safe_order import SafeOrderManager
        
        manager = SafeOrderManager()
        
        # Create a mock client
        class MockClient:
            def place_order(self, symbol, side, size_usd):
                return {"status": "mock_success"}
        
        # Place an order
        result = manager.place_order(
            MockClient(),
            "BTC-USD",
            "buy",
            50.0,
            metadata={"test": "data"}
        )
        
        # Check log file was created and contains entry
        assert os.path.exists(log_path), "Log file should be created"
        
        with open(log_path, 'r') as f:
            log_content = f.read()
            assert len(log_content) > 0, "Log file should not be empty"
            
            # Parse first log entry
            log_entry = json.loads(log_content.strip().split('\n')[0])
            assert 'timestamp' in log_entry
            assert log_entry['action'] == 'order_placed'
            assert 'result' in log_entry
            
        print("✅ Safe order creates audit logs")
        
    finally:
        if original_log:
            os.environ['LOG_PATH'] = original_log
        elif 'LOG_PATH' in os.environ:
            del os.environ['LOG_PATH']
        if original_mode:
            os.environ['MODE'] = original_mode
        elif 'MODE' in os.environ:
            del os.environ['MODE']
        if original_account:
            os.environ['COINBASE_ACCOUNT_ID'] = original_account
        elif 'COINBASE_ACCOUNT_ID' in os.environ:
            del os.environ['COINBASE_ACCOUNT_ID']
        
        # Clean up log file
        if os.path.exists(log_path):
            os.unlink(log_path)


def test_manual_approval_workflow():
    """Test manual approval workflow for first N orders"""
    import tempfile
    import importlib
    
    # Create temporary log file
    with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.log') as f:
        log_path = f.name
    
    original_log = os.environ.get('LOG_PATH')
    original_approval = os.environ.get('MANUAL_APPROVAL_COUNT')
    original_mode = os.environ.get('MODE')
    original_account = os.environ.get('COINBASE_ACCOUNT_ID')
    
    os.environ['LOG_PATH'] = log_path
    os.environ['MANUAL_APPROVAL_COUNT'] = '2'
    os.environ['MODE'] = 'DRY_RUN'
    os.environ['COINBASE_ACCOUNT_ID'] = 'test-account'
    
    try:
        import config
        importlib.reload(config)
        from safe_order import SafeOrderManager
        
        manager = SafeOrderManager()
        
        # Create a mock client
        class MockClient:
            def place_order(self, symbol, side, size_usd):
                return {"status": "mock_success"}
        
        # First order should require approval
        result1 = manager.place_order(MockClient(), "BTC-USD", "buy", 50.0)
        assert result1['status'] == 'pending_approval', f"First order should be pending approval, got {result1['status']}"
        
        # Second order should also require approval
        result2 = manager.place_order(MockClient(), "ETH-USD", "buy", 30.0)
        assert result2['status'] == 'pending_approval', f"Second order should be pending approval, got {result2['status']}"
        
        # Check pending approvals
        pending = manager.get_pending_approvals()
        assert len(pending) == 2, f"Should have 2 pending approvals, got {len(pending)}"
        
        print("✅ Manual approval workflow creates pending orders")
        
        # Third order should go through (after approval count)
        result3 = manager.place_order(MockClient(), "SOL-USD", "buy", 20.0)
        assert result3['status'] == 'dry_run_simulated', f"Third order should be simulated, got {result3['status']}"
        
        print("✅ Manual approval workflow processes orders after approval count")
        
    finally:
        if original_log:
            os.environ['LOG_PATH'] = original_log
        elif 'LOG_PATH' in os.environ:
            del os.environ['LOG_PATH']
        if original_approval:
            os.environ['MANUAL_APPROVAL_COUNT'] = original_approval
        elif 'MANUAL_APPROVAL_COUNT' in os.environ:
            del os.environ['MANUAL_APPROVAL_COUNT']
        if original_mode:
            os.environ['MODE'] = original_mode
        elif 'MODE' in os.environ:
            del os.environ['MODE']
        if original_account:
            os.environ['COINBASE_ACCOUNT_ID'] = original_account
        elif 'COINBASE_ACCOUNT_ID' in os.environ:
            del os.environ['COINBASE_ACCOUNT_ID']
        
        # Clean up files
        if os.path.exists(log_path):
            os.unlink(log_path)
        
        pending_file = Path(log_path).parent / "pending_approvals.json"
        if pending_file.exists():
            pending_file.unlink()


def run_all_tests():
    """Run all tests"""
    tests = [
        test_config_mode_parsing,
        test_config_numeric_parsing,
        test_safety_checks_dry_run,
        test_safety_checks_live_mode_rejects_missing_account,
        test_safety_checks_live_mode_rejects_missing_confirm,
        test_rate_limiter,
        test_safe_order_validates_size,
        test_webhook_signature_verification,
        test_audit_logging,
        test_manual_approval_workflow,
    ]
    
    print("\n" + "="*60)
    print("Running Safe Trading Stack Tests")
    print("="*60 + "\n")
    
    passed = 0
    failed = 0
    
    for test in tests:
        try:
            print(f"\nRunning {test.__name__}...")
            test()
            passed += 1
        except Exception as e:
            print(f"❌ {test.__name__} failed: {e}")
            import traceback
            traceback.print_exc()
            failed += 1
    
    print("\n" + "="*60)
    print(f"Test Results: {passed} passed, {failed} failed")
    print("="*60 + "\n")
    
    return failed == 0


if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)
