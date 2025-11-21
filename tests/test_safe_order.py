"""
Tests for safe_order module
"""
import os
import sys
import time
import json
import tempfile
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_validate_mode_and_account_dry_run():
    """Test MODE validation in DRY_RUN mode"""
    # Set environment and import fresh
    os.environ['MODE'] = 'DRY_RUN'
    
    # Force reload of config and safe_order
    if 'config' in sys.modules:
        del sys.modules['config']
    if 'safe_order' in sys.modules:
        del sys.modules['safe_order']
    
    import safe_order
    
    # Should not raise
    safe_order.validate_mode_and_account()
    print("✅ DRY_RUN mode validation passed")


def test_validate_mode_and_account_live_no_account():
    """Test MODE validation in LIVE mode without account"""
    os.environ['MODE'] = 'LIVE'
    os.environ.pop('COINBASE_ACCOUNT_ID', None)
    
    # Force reload
    if 'config' in sys.modules:
        del sys.modules['config']
    if 'safe_order' in sys.modules:
        del sys.modules['safe_order']
    
    import safe_order
    
    try:
        safe_order.validate_mode_and_account()
        print("❌ Should have raised RuntimeError")
        assert False
    except RuntimeError as e:
        assert "COINBASE_ACCOUNT_ID" in str(e)
        print(f"✅ Correctly rejected LIVE mode without account: {e}")


def test_validate_mode_and_account_live_no_confirm():
    """Test MODE validation in LIVE mode without CONFIRM_LIVE"""
    os.environ['MODE'] = 'LIVE'
    os.environ['COINBASE_ACCOUNT_ID'] = 'test-account'
    os.environ['CONFIRM_LIVE'] = 'false'
    
    # Force reload
    if 'config' in sys.modules:
        del sys.modules['config']
    if 'safe_order' in sys.modules:
        del sys.modules['safe_order']
    
    import safe_order
    
    try:
        safe_order.validate_mode_and_account()
        print("❌ Should have raised RuntimeError")
        assert False
    except RuntimeError as e:
        assert "CONFIRM_LIVE" in str(e)
        print(f"✅ Correctly rejected LIVE mode without CONFIRM_LIVE: {e}")


def test_enforce_max_order_usd():
    """Test MAX_ORDER_USD enforcement"""
    os.environ['MODE'] = 'DRY_RUN'
    os.environ['MAX_ORDER_USD'] = '100.0'
    
    # Force reload
    if 'config' in sys.modules:
        del sys.modules['config']
    if 'safe_order' in sys.modules:
        del sys.modules['safe_order']
    
    import safe_order
    
    # Should not raise for order within limit
    safe_order.enforce_max_order_usd(50.0)
    print("✅ Order within limit accepted")
    
    # Should raise for order exceeding limit
    try:
        safe_order.enforce_max_order_usd(150.0)
        print("❌ Should have raised RuntimeError")
        assert False
    except RuntimeError as e:
        assert "MAX_ORDER_USD" in str(e)
        print(f"✅ Correctly rejected order exceeding limit: {e}")


def test_rate_limit():
    """Test rate limiting"""
    os.environ['MODE'] = 'DRY_RUN'
    os.environ['MAX_ORDERS_PER_MINUTE'] = '3'
    
    # Force reload
    if 'config' in sys.modules:
        del sys.modules['config']
    if 'safe_order' in sys.modules:
        del sys.modules['safe_order']
    
    import safe_order
    
    # Reset order timestamps
    safe_order.order_timestamps = []
    
    # Should allow first 3 orders
    for i in range(3):
        safe_order.check_rate_limit()
        print(f"✅ Order {i+1}/3 accepted")
    
    # Should reject 4th order
    try:
        safe_order.check_rate_limit()
        print("❌ Should have raised RuntimeError")
        assert False
    except RuntimeError as e:
        assert "Rate limit exceeded" in str(e)
        print(f"✅ Correctly rejected order due to rate limit: {e}")


def test_manual_approval():
    """Test manual approval requirement"""
    os.environ['MODE'] = 'DRY_RUN'
    os.environ['MANUAL_APPROVAL_COUNT'] = '2'
    
    # Force reload
    if 'config' in sys.modules:
        del sys.modules['config']
    if 'safe_order' in sys.modules:
        del sys.modules['safe_order']
    
    import safe_order
    
    # Reset counter
    safe_order.total_orders_submitted = 0
    
    # First order should require approval
    assert safe_order.requires_manual_approval() == True
    print("✅ First order requires manual approval")
    
    # After submitting one order
    safe_order.total_orders_submitted = 1
    assert safe_order.requires_manual_approval() == True
    print("✅ Second order requires manual approval")
    
    # After submitting two orders
    safe_order.total_orders_submitted = 2
    assert safe_order.requires_manual_approval() == False
    print("✅ Third order does not require manual approval")


def test_audit_log():
    """Test audit logging"""
    log_file = tempfile.mktemp(suffix='_audit_test.log')
    os.environ['MODE'] = 'DRY_RUN'
    os.environ['LOG_PATH'] = log_file
    
    # Force reload
    if 'config' in sys.modules:
        del sys.modules['config']
    if 'safe_order' in sys.modules:
        del sys.modules['safe_order']
    
    import safe_order
    
    order_request = {
        "symbol": "BTC-USD",
        "side": "buy",
        "size_usd": 50.0
    }
    coinbase_response = {
        "status": "success",
        "order_id": "test-123"
    }
    
    safe_order.audit_log(order_request, coinbase_response)
    
    # Check log file exists and contains data
    log_path = Path(log_file)
    assert log_path.exists()
    
    with open(log_file, 'r') as f:
        log_content = f.read()
        log_entry = json.loads(log_content)
        assert log_entry['order_request']['symbol'] == "BTC-USD"
        assert log_entry['coinbase_response']['status'] == "success"
    
    print(f"✅ Audit log created successfully: {log_file}")
    
    # Cleanup
    log_path.unlink()


if __name__ == "__main__":
    print("Running safe_order tests...\n")
    
    test_validate_mode_and_account_dry_run()
    test_validate_mode_and_account_live_no_account()
    test_validate_mode_and_account_live_no_confirm()
    test_enforce_max_order_usd()
    test_rate_limit()
    test_manual_approval()
    test_audit_log()
    
    print("\n✅ All tests passed!")
