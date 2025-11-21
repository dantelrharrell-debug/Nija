#!/usr/bin/env python3
"""
Integration test for safe trading stack

This test validates the complete integration of:
- safe_order.py with rate limiting and mode validation
- tv_webhook.py with HMAC signature verification
- nija_client.py with safety checks
"""

import os
import sys
import json
import hmac
import hashlib
import tempfile
from datetime import datetime

def setup_test_env():
    """Set up test environment variables"""
    os.environ['MODE'] = 'DRY_RUN'
    os.environ['COINBASE_ACCOUNT_ID'] = ''
    os.environ['CONFIRM_LIVE'] = 'false'
    os.environ['MAX_ORDER_USD'] = '50.0'
    os.environ['MAX_ORDERS_PER_MINUTE'] = '5'
    os.environ['MANUAL_APPROVAL_COUNT'] = '0'
    os.environ['LOG_PATH'] = '/tmp/test_nija_orders.log'
    os.environ['TRADINGVIEW_WEBHOOK_SECRET'] = 'test_secret_key_123'

def test_safe_order_dry_run():
    """Test safe_order in DRY_RUN mode"""
    print("Testing safe_order in DRY_RUN mode...")
    
    setup_test_env()
    
    # Re-import modules to pick up env changes
    if 'config' in sys.modules:
        del sys.modules['config']
    if 'safe_order' in sys.modules:
        del sys.modules['safe_order']
    
    import safe_order
    
    # Mock client
    class MockClient:
        def place_order(self, symbol, side, size_usd):
            return {'status': 'filled', 'order_id': '12345'}
    
    client = MockClient()
    
    # Test order submission
    result = safe_order.submit_order(client, 'BTC-USD', 'buy', 25.0)
    
    assert result['status'] == 'dry_run', f"Expected dry_run status, got {result['status']}"
    print(f"✅ DRY_RUN order result: {result['message']}")
    
    return True

def test_safe_order_rate_limit():
    """Test rate limiting in safe_order"""
    print("Testing rate limiting...")
    
    setup_test_env()
    os.environ['MAX_ORDERS_PER_MINUTE'] = '3'
    
    # Re-import modules
    if 'config' in sys.modules:
        del sys.modules['config']
    if 'safe_order' in sys.modules:
        del sys.modules['safe_order']
    
    import safe_order
    
    class MockClient:
        def place_order(self, symbol, side, size_usd):
            return {'status': 'filled'}
    
    client = MockClient()
    
    # Submit 3 orders (should succeed)
    for i in range(3):
        result = safe_order.submit_order(client, 'BTC-USD', 'buy', 10.0)
        assert result['status'] == 'dry_run'
    
    # 4th order should fail due to rate limit
    try:
        safe_order.submit_order(client, 'BTC-USD', 'buy', 10.0)
        print("❌ Rate limit not enforced")
        return False
    except RuntimeError as e:
        if 'Rate limit exceeded' in str(e):
            print(f"✅ Rate limit enforced: {e}")
            return True
        else:
            print(f"❌ Unexpected error: {e}")
            return False

def test_safe_order_max_usd():
    """Test MAX_ORDER_USD limit"""
    print("Testing MAX_ORDER_USD limit...")
    
    setup_test_env()
    os.environ['MAX_ORDER_USD'] = '100.0'
    
    # Re-import modules
    if 'config' in sys.modules:
        del sys.modules['config']
    if 'safe_order' in sys.modules:
        del sys.modules['safe_order']
    
    import safe_order
    
    class MockClient:
        def place_order(self, symbol, side, size_usd):
            return {'status': 'filled'}
    
    client = MockClient()
    
    # Try to place order exceeding limit
    try:
        safe_order.submit_order(client, 'BTC-USD', 'buy', 150.0)
        print("❌ MAX_ORDER_USD not enforced")
        return False
    except ValueError as e:
        if 'exceeds MAX_ORDER_USD' in str(e):
            print(f"✅ MAX_ORDER_USD enforced: {e}")
            return True
        else:
            print(f"❌ Unexpected error: {e}")
            return False

def test_webhook_signature_verification():
    """Test TradingView webhook signature verification"""
    print("Testing webhook signature verification...")
    
    setup_test_env()
    
    # Re-import modules
    if 'config' in sys.modules:
        del sys.modules['config']
    if 'tv_webhook' in sys.modules:
        del sys.modules['tv_webhook']
    
    from tv_webhook import verify_signature
    
    secret = 'test_secret_key_123'
    payload = b'{"symbol": "BTC-USD", "action": "buy"}'
    
    # Generate valid signature
    valid_signature = hmac.new(
        secret.encode('utf-8'),
        payload,
        hashlib.sha256
    ).hexdigest()
    
    # Test valid signature
    assert verify_signature(payload, valid_signature), "Valid signature rejected"
    print("✅ Valid signature accepted")
    
    # Test invalid signature
    invalid_signature = 'invalid_signature_12345'
    assert not verify_signature(payload, invalid_signature), "Invalid signature accepted"
    print("✅ Invalid signature rejected")
    
    return True

def test_manual_approval():
    """Test manual approval mechanism"""
    print("Testing manual approval mechanism...")
    
    setup_test_env()
    os.environ['MANUAL_APPROVAL_COUNT'] = '2'
    
    # Use a unique log path for this test
    log_path = '/tmp/test_approval_orders.log'
    os.environ['LOG_PATH'] = log_path
    
    # Clean up old files
    approval_file = log_path.replace('.log', '_pending_approvals.json')
    for f in [log_path, approval_file]:
        if os.path.exists(f):
            os.remove(f)
    
    # Re-import modules
    if 'config' in sys.modules:
        del sys.modules['config']
    if 'safe_order' in sys.modules:
        del sys.modules['safe_order']
    
    import safe_order
    
    class MockClient:
        def place_order(self, symbol, side, size_usd):
            return {'status': 'filled'}
    
    client = MockClient()
    
    # First order should be pending approval
    result = safe_order.submit_order(client, 'BTC-USD', 'buy', 10.0)
    assert result['status'] == 'pending_approval', f"Expected pending_approval, got {result['status']}"
    print(f"✅ First order pending approval: {result['message']}")
    
    # Check approval file was created
    assert os.path.exists(approval_file), "Approval file not created"
    
    # Load and approve the order
    with open(approval_file, 'r') as f:
        data = json.load(f)
    
    data['orders'][0]['approved'] = True
    
    with open(approval_file, 'w') as f:
        json.dump(data, f)
    
    # Submit another order - should still be pending (need 2 approvals)
    result2 = safe_order.submit_order(client, 'ETH-USD', 'buy', 10.0)
    assert result2['status'] == 'pending_approval'
    print("✅ Second order also pending")
    
    # Approve second order
    with open(approval_file, 'r') as f:
        data = json.load(f)
    
    data['orders'][1]['approved'] = True
    
    with open(approval_file, 'w') as f:
        json.dump(data, f)
    
    # Now next order should go through (in DRY_RUN mode)
    result3 = safe_order.submit_order(client, 'SOL-USD', 'buy', 10.0)
    assert result3['status'] == 'dry_run', f"Expected dry_run after approvals, got {result3['status']}"
    print("✅ Third order processed after approvals")
    
    # Clean up
    for f in [log_path, approval_file]:
        if os.path.exists(f):
            os.remove(f)
    
    return True

def test_audit_logging():
    """Test that orders are logged to audit file"""
    print("Testing audit logging...")
    
    log_path = '/tmp/test_audit_orders.log'
    
    # Clean up old log
    if os.path.exists(log_path):
        os.remove(log_path)
    
    setup_test_env()
    os.environ['LOG_PATH'] = log_path
    os.environ['MANUAL_APPROVAL_COUNT'] = '0'
    
    # Re-import modules
    if 'config' in sys.modules:
        del sys.modules['config']
    if 'safe_order' in sys.modules:
        del sys.modules['safe_order']
    
    import safe_order
    
    class MockClient:
        def place_order(self, symbol, side, size_usd):
            return {'status': 'filled'}
    
    client = MockClient()
    
    # Submit an order
    safe_order.submit_order(client, 'BTC-USD', 'buy', 25.0)
    
    # Check log file was created and has content
    assert os.path.exists(log_path), "Log file not created"
    
    with open(log_path, 'r') as f:
        log_entries = [json.loads(line) for line in f]
    
    assert len(log_entries) >= 1, "No log entries found"
    
    entry = log_entries[0]
    assert 'timestamp' in entry
    assert 'mode' in entry
    assert entry['mode'] == 'DRY_RUN'
    assert 'request' in entry
    assert entry['request']['symbol'] == 'BTC-USD'
    
    print(f"✅ Audit log created with {len(log_entries)} entries")
    
    # Clean up
    os.remove(log_path)
    
    return True

def main():
    """Run all integration tests"""
    print("=" * 60)
    print("Safe Trading Stack Integration Tests")
    print("=" * 60)
    
    tests = [
        test_safe_order_dry_run,
        test_safe_order_rate_limit,
        test_safe_order_max_usd,
        test_webhook_signature_verification,
        test_manual_approval,
        test_audit_logging,
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
