"""
Tests for webhook_handler module
"""
import os
import sys
import hmac
import hashlib
import json

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_verify_signature_valid():
    """Test HMAC signature verification with valid signature"""
    secret = 'test_secret_key'
    payload = b'{"action": "buy", "symbol": "BTC-USD"}'
    
    # Generate valid signature
    signature = hmac.new(
        secret.encode('utf-8'),
        payload,
        hashlib.sha256
    ).hexdigest()
    
    os.environ['TRADINGVIEW_WEBHOOK_SECRET'] = secret
    
    # Force reload
    if 'config' in sys.modules:
        del sys.modules['config']
    if 'webhook_handler' in sys.modules:
        del sys.modules['webhook_handler']
    
    import webhook_handler
    
    assert webhook_handler.verify_signature(payload, signature) == True
    print("✅ Valid signature verified successfully")


def test_verify_signature_invalid():
    """Test HMAC signature verification with invalid signature"""
    secret = 'test_secret_key'
    payload = b'{"action": "buy", "symbol": "BTC-USD"}'
    invalid_signature = "invalid_signature_hash"
    
    os.environ['TRADINGVIEW_WEBHOOK_SECRET'] = secret
    
    # Force reload
    if 'config' in sys.modules:
        del sys.modules['config']
    if 'webhook_handler' in sys.modules:
        del sys.modules['webhook_handler']
    
    import webhook_handler
    
    assert webhook_handler.verify_signature(payload, invalid_signature) == False
    print("✅ Invalid signature correctly rejected")


def test_verify_signature_no_secret():
    """Test signature verification when no secret is configured"""
    os.environ['TRADINGVIEW_WEBHOOK_SECRET'] = ''
    
    # Force reload
    if 'config' in sys.modules:
        del sys.modules['config']
    if 'webhook_handler' in sys.modules:
        del sys.modules['webhook_handler']
    
    import webhook_handler
    
    payload = b'{"action": "buy"}'
    signature = "any_signature"
    
    # Should return True when no secret is configured (for testing)
    assert webhook_handler.verify_signature(payload, signature) == True
    print("✅ Signature check bypassed when no secret configured")


def test_webhook_blueprint():
    """Test that webhook blueprint is properly created"""
    from flask import Flask
    
    os.environ['TRADINGVIEW_WEBHOOK_SECRET'] = 'test_secret'
    
    # Force reload
    if 'config' in sys.modules:
        del sys.modules['config']
    if 'webhook_handler' in sys.modules:
        del sys.modules['webhook_handler']
    
    import webhook_handler
    
    app = Flask(__name__)
    app.register_blueprint(webhook_handler.webhook_bp)
    
    # Check that routes are registered
    rules = [rule.rule for rule in app.url_map.iter_rules()]
    
    assert '/tradingview/webhook' in rules
    assert '/tradingview/health' in rules
    
    print("✅ Webhook blueprint routes registered successfully")
    print(f"   Available routes: {[r for r in rules if 'tradingview' in r]}")


def test_webhook_endpoint_with_flask_client():
    """Test webhook endpoint using Flask test client"""
    from flask import Flask
    
    secret = 'test_webhook_secret'
    os.environ['TRADINGVIEW_WEBHOOK_SECRET'] = secret
    
    # Force reload
    if 'config' in sys.modules:
        del sys.modules['config']
    if 'webhook_handler' in sys.modules:
        del sys.modules['webhook_handler']
    
    import webhook_handler
    
    app = Flask(__name__)
    app.register_blueprint(webhook_handler.webhook_bp)
    
    client = app.test_client()
    
    # Test health endpoint
    response = client.get('/tradingview/health')
    assert response.status_code == 200
    data = json.loads(response.data)
    assert data['status'] == 'healthy'
    print("✅ Health endpoint working")
    
    # Test webhook endpoint with valid signature
    payload = {"action": "buy", "symbol": "BTC-USD", "price": 50000}
    payload_bytes = json.dumps(payload).encode('utf-8')
    
    signature = hmac.new(
        secret.encode('utf-8'),
        payload_bytes,
        hashlib.sha256
    ).hexdigest()
    
    response = client.post(
        '/tradingview/webhook',
        data=payload_bytes,
        headers={
            'X-Tv-Signature': signature,
            'Content-Type': 'application/json'
        }
    )
    
    assert response.status_code == 200
    data = json.loads(response.data)
    assert data['status'] == 'success'
    print("✅ Webhook endpoint accepts valid requests")
    
    # Test webhook endpoint with invalid signature
    response = client.post(
        '/tradingview/webhook',
        data=payload_bytes,
        headers={
            'X-Tv-Signature': 'invalid_signature',
            'Content-Type': 'application/json'
        }
    )
    
    assert response.status_code == 401
    data = json.loads(response.data)
    assert data['status'] == 'error'
    print("✅ Webhook endpoint rejects invalid signatures")


if __name__ == "__main__":
    print("Running webhook_handler tests...\n")
    
    test_verify_signature_valid()
    test_verify_signature_invalid()
    test_verify_signature_no_secret()
    test_webhook_blueprint()
    test_webhook_endpoint_with_flask_client()
    
    print("\n✅ All webhook tests passed!")
