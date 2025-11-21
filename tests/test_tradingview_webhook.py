"""
test_tradingview_webhook.py - Tests for TradingView webhook endpoint.
"""

import os
import json
import hmac
import hashlib

# Set test environment variables
os.environ["TRADINGVIEW_WEBHOOK_SECRET"] = "test_secret_key_123"
os.environ["MODE"] = "DRY_RUN"
os.environ["LOG_PATH"] = "/tmp/test_webhook_orders.log"

from flask import Flask
from tradingview_webhook import tradingview_bp, verify_signature, generate_test_signature


class TestSignatureVerification:
    """Test HMAC signature verification."""
    
    def test_verify_valid_signature(self):
        """Test that valid signatures are accepted."""
        payload = {"symbol": "BTC-USD", "side": "buy", "size_usd": 50.0}
        payload_bytes = json.dumps(payload, separators=(',', ':')).encode('utf-8')
        
        signature = hmac.new(
            b"test_secret_key_123",
            payload_bytes,
            hashlib.sha256
        ).hexdigest()
        
        assert verify_signature(payload_bytes, signature) is True
    
    def test_verify_invalid_signature(self):
        """Test that invalid signatures are rejected."""
        payload = {"symbol": "BTC-USD", "side": "buy", "size_usd": 50.0}
        payload_bytes = json.dumps(payload, separators=(',', ':')).encode('utf-8')
        
        invalid_signature = "invalid_signature_here"
        
        assert verify_signature(payload_bytes, invalid_signature) is False
    
    def test_verify_wrong_secret(self):
        """Test that signatures with wrong secret are rejected."""
        payload = {"symbol": "BTC-USD", "side": "buy", "size_usd": 50.0}
        payload_bytes = json.dumps(payload, separators=(',', ':')).encode('utf-8')
        
        # Generate signature with wrong secret
        signature = hmac.new(
            b"wrong_secret",
            payload_bytes,
            hashlib.sha256
        ).hexdigest()
        
        assert verify_signature(payload_bytes, signature) is False


class TestWebhookEndpoint:
    """Test webhook endpoint functionality."""
    
    def setup_method(self):
        """Setup test Flask app."""
        self.app = Flask(__name__)
        self.app.register_blueprint(tradingview_bp)
        self.client = self.app.test_client()
    
    def _make_signed_request(self, payload):
        """Helper to make a signed webhook request."""
        payload_json = json.dumps(payload, separators=(',', ':'))
        signature = generate_test_signature(payload)
        
        return self.client.post(
            '/tradingview/webhook',
            data=payload_json,
            headers={
                'Content-Type': 'application/json',
                'X-Tv-Signature': signature
            }
        )
    
    def test_webhook_valid_request(self):
        """Test webhook with valid signature and payload."""
        payload = {
            "symbol": "BTC-USD",
            "side": "buy",
            "size_usd": 50.0
        }
        
        response = self._make_signed_request(payload)
        
        assert response.status_code == 200
        data = json.loads(response.data)
        assert data["status"] == "success"
    
    def test_webhook_missing_signature(self):
        """Test webhook rejects request without signature."""
        payload = {"symbol": "BTC-USD", "side": "buy", "size_usd": 50.0}
        
        response = self.client.post(
            '/tradingview/webhook',
            data=json.dumps(payload),
            headers={'Content-Type': 'application/json'}
        )
        
        assert response.status_code == 401
        data = json.loads(response.data)
        assert "Missing X-Tv-Signature" in data["error"]
    
    def test_webhook_invalid_signature(self):
        """Test webhook rejects request with invalid signature."""
        payload = {"symbol": "BTC-USD", "side": "buy", "size_usd": 50.0}
        
        response = self.client.post(
            '/tradingview/webhook',
            data=json.dumps(payload),
            headers={
                'Content-Type': 'application/json',
                'X-Tv-Signature': 'invalid_signature'
            }
        )
        
        assert response.status_code == 401
        data = json.loads(response.data)
        assert "Invalid signature" in data["error"]
    
    def test_webhook_missing_fields(self):
        """Test webhook rejects payload with missing required fields."""
        # Missing size_usd
        payload = {"symbol": "BTC-USD", "side": "buy"}
        
        response = self._make_signed_request(payload)
        
        assert response.status_code == 400
        data = json.loads(response.data)
        assert "Missing required fields" in data["error"]
    
    def test_webhook_invalid_side(self):
        """Test webhook rejects invalid side value."""
        payload = {
            "symbol": "BTC-USD",
            "side": "invalid",
            "size_usd": 50.0
        }
        
        response = self._make_signed_request(payload)
        
        assert response.status_code == 400
        data = json.loads(response.data)
        assert "side must be 'buy' or 'sell'" in data["error"]
    
    def test_webhook_invalid_size(self):
        """Test webhook rejects invalid size_usd value."""
        payload = {
            "symbol": "BTC-USD",
            "side": "buy",
            "size_usd": -10.0
        }
        
        response = self._make_signed_request(payload)
        
        assert response.status_code == 400
        data = json.loads(response.data)
        assert "Invalid size_usd" in data["error"]
    
    def test_webhook_health_check(self):
        """Test health check endpoint."""
        response = self.client.get('/tradingview/health')
        
        assert response.status_code == 200
        data = json.loads(response.data)
        assert data["status"] == "healthy"


if __name__ == "__main__":
    # Run tests
    try:
        import pytest
        pytest.main([__file__, "-v"])
    except ImportError:
        print("pytest not available, running basic tests...")
        
        # Run basic signature tests
        sig_test = TestSignatureVerification()
        sig_test.test_verify_valid_signature()
        sig_test.test_verify_invalid_signature()
        sig_test.test_verify_wrong_secret()
        print("✓ Signature verification tests passed")
        
        # Run basic webhook tests
        webhook_test = TestWebhookEndpoint()
        webhook_test.setup_method()
        webhook_test.test_webhook_valid_request()
        webhook_test.test_webhook_missing_signature()
        webhook_test.test_webhook_invalid_signature()
        webhook_test.test_webhook_missing_fields()
        print("✓ Webhook endpoint tests passed")
        
        print("\nAll tests passed!")
