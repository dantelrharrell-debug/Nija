"""
Tests for TradingView webhook
"""

import unittest
import hmac
import hashlib
import json
from unittest.mock import patch

from flask import Flask

# Mock config before importing
with patch.dict('os.environ', {
    'TRADINGVIEW_WEBHOOK_SECRET': 'test_secret_key_12345'
}):
    from tradingview_webhook import tradingview_bp, verify_signature


class TestTradingViewWebhook(unittest.TestCase):
    
    def setUp(self):
        """Set up test fixtures."""
        # Create test Flask app
        self.app = Flask(__name__)
        self.app.register_blueprint(tradingview_bp)
        self.client = self.app.test_client()
        self.secret = 'test_secret_key_12345'
    
    def _generate_signature(self, payload_body: bytes, secret: str) -> str:
        """Generate HMAC SHA256 signature for testing."""
        return hmac.new(
            secret.encode('utf-8'),
            payload_body,
            hashlib.sha256
        ).hexdigest()
    
    def test_verify_signature_valid(self):
        """Test signature verification with valid signature."""
        payload = b'{"signal": "buy", "symbol": "BTC-USD"}'
        signature = self._generate_signature(payload, self.secret)
        
        result = verify_signature(payload, signature, self.secret)
        self.assertTrue(result)
    
    def test_verify_signature_invalid(self):
        """Test signature verification with invalid signature."""
        payload = b'{"signal": "buy", "symbol": "BTC-USD"}'
        
        result = verify_signature(payload, 'invalid_signature', self.secret)
        self.assertFalse(result)
    
    def test_verify_signature_wrong_secret(self):
        """Test signature verification with wrong secret."""
        payload = b'{"signal": "buy", "symbol": "BTC-USD"}'
        signature = self._generate_signature(payload, 'wrong_secret')
        
        result = verify_signature(payload, signature, self.secret)
        self.assertFalse(result)
    
    def test_webhook_missing_signature(self):
        """Test webhook rejects request without signature header."""
        payload = {"signal": "buy", "symbol": "BTC-USD"}
        
        response = self.client.post(
            '/webhook',
            data=json.dumps(payload),
            content_type='application/json'
        )
        
        self.assertEqual(response.status_code, 401)
        data = json.loads(response.data)
        self.assertIn('Missing X-Tv-Signature', data['message'])
    
    def test_webhook_invalid_signature(self):
        """Test webhook rejects request with invalid signature."""
        payload = {"signal": "buy", "symbol": "BTC-USD"}
        
        response = self.client.post(
            '/webhook',
            data=json.dumps(payload),
            content_type='application/json',
            headers={'X-Tv-Signature': 'invalid_signature'}
        )
        
        self.assertEqual(response.status_code, 401)
        data = json.loads(response.data)
        self.assertIn('Invalid signature', data['message'])
    
    def test_webhook_valid_request(self):
        """Test webhook accepts valid request with correct signature."""
        payload = {"signal": "buy", "symbol": "BTC-USD"}
        payload_bytes = json.dumps(payload).encode('utf-8')
        signature = self._generate_signature(payload_bytes, self.secret)
        
        response = self.client.post(
            '/webhook',
            data=payload_bytes,
            content_type='application/json',
            headers={'X-Tv-Signature': signature}
        )
        
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.data)
        self.assertEqual(data['status'], 'success')
    
    def test_webhook_invalid_json(self):
        """Test webhook rejects invalid JSON payload."""
        payload_bytes = b'not valid json'
        signature = self._generate_signature(payload_bytes, self.secret)
        
        response = self.client.post(
            '/webhook',
            data=payload_bytes,
            content_type='application/json',
            headers={'X-Tv-Signature': signature}
        )
        
        self.assertEqual(response.status_code, 400)
        data = json.loads(response.data)
        self.assertIn('Invalid JSON', data['message'])
    
    def test_webhook_with_signal_and_symbol(self):
        """Test webhook processes payload with signal and symbol."""
        payload = {
            "signal": "sell",
            "symbol": "ETH-USD",
            "price": 3500.0
        }
        payload_bytes = json.dumps(payload).encode('utf-8')
        signature = self._generate_signature(payload_bytes, self.secret)
        
        response = self.client.post(
            '/webhook',
            data=payload_bytes,
            content_type='application/json',
            headers={'X-Tv-Signature': signature}
        )
        
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.data)
        self.assertEqual(data['status'], 'success')


if __name__ == '__main__':
    unittest.main()
