"""
Integration test for TradingView webhook endpoint with Flask.
"""

import os
import sys
import json
import hmac
import hashlib

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Set up test environment before importing
os.environ['MODE'] = 'DRY_RUN'
os.environ['TRADINGVIEW_WEBHOOK_SECRET'] = 'test_secret_for_integration'
os.environ['LOG_PATH'] = '/tmp/test_webhook_integration.log'

def test_webhook_integration():
    """Test the TradingView webhook with Flask test client."""
    print("\n=== Testing TradingView Webhook Integration ===\n")
    
    from flask import Flask
    from tv_webhook import tv_webhook
    
    # Create test Flask app
    app = Flask(__name__)
    app.register_blueprint(tv_webhook)
    
    # Create test client
    client = app.test_client()
    
    # Test 1: Health check endpoint
    print("Test 1: Health check endpoint")
    response = client.get('/tradingview/health')
    assert response.status_code == 200, f"Expected 200, got {response.status_code}"
    data = json.loads(response.data)
    assert data['status'] == 'healthy', "Health check should return healthy"
    print(f"✓ Health check passed: {data}")
    
    # Test 2: Valid webhook with signature
    print("\nTest 2: Valid webhook with signature")
    payload = {"alert": "BUY", "symbol": "BTC-USD", "price": 50000}
    payload_bytes = json.dumps(payload).encode('utf-8')
    
    secret = 'test_secret_for_integration'
    signature = hmac.new(secret.encode('utf-8'), payload_bytes, hashlib.sha256).hexdigest()
    
    response = client.post(
        '/tradingview/webhook',
        data=payload_bytes,
        headers={
            'Content-Type': 'application/json',
            'X-Tv-Signature': signature
        }
    )
    assert response.status_code == 200, f"Expected 200, got {response.status_code}"
    data = json.loads(response.data)
    assert data['status'] == 'success', "Valid webhook should succeed"
    print(f"✓ Valid webhook accepted: {data}")
    
    # Test 3: Invalid signature
    print("\nTest 3: Invalid signature")
    response = client.post(
        '/tradingview/webhook',
        data=payload_bytes,
        headers={
            'Content-Type': 'application/json',
            'X-Tv-Signature': 'invalid_signature'
        }
    )
    assert response.status_code == 401, f"Expected 401, got {response.status_code}"
    data = json.loads(response.data)
    assert data['status'] == 'error', "Invalid signature should fail"
    print(f"✓ Invalid signature rejected: {data}")
    
    # Test 4: Missing signature
    print("\nTest 4: Missing signature")
    response = client.post(
        '/tradingview/webhook',
        data=payload_bytes,
        headers={'Content-Type': 'application/json'}
    )
    assert response.status_code == 401, f"Expected 401, got {response.status_code}"
    data = json.loads(response.data)
    assert data['status'] == 'error', "Missing signature should fail"
    print(f"✓ Missing signature rejected: {data}")
    
    # Test 5: Invalid JSON
    print("\nTest 5: Invalid JSON")
    invalid_payload = b"not valid json"
    signature = hmac.new(secret.encode('utf-8'), invalid_payload, hashlib.sha256).hexdigest()
    
    response = client.post(
        '/tradingview/webhook',
        data=invalid_payload,
        headers={
            'Content-Type': 'application/json',
            'X-Tv-Signature': signature
        }
    )
    assert response.status_code == 400, f"Expected 400, got {response.status_code}"
    data = json.loads(response.data)
    assert data['status'] == 'error', "Invalid JSON should fail"
    print(f"✓ Invalid JSON rejected: {data}")
    
    print("\n✅ All webhook integration tests passed!\n")


if __name__ == '__main__':
    try:
        test_webhook_integration()
        print("="*50)
        print("🎉 INTEGRATION TEST PASSED!")
        print("="*50 + "\n")
    except Exception as e:
        print(f"\n❌ Integration test failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
