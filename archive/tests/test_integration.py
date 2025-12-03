"""
test_integration.py - Integration test for safe trading stack

Tests the complete flow from webhook to order submission.
"""

import os
import sys
import json
import hmac
import hashlib
import tempfile
import unittest
from unittest.mock import Mock, patch

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestIntegration(unittest.TestCase):
    """Integration tests for the complete safe trading stack."""
    
    def setUp(self):
        """Set up test environment."""
        self.original_env = os.environ.copy()
        self.temp_log = tempfile.NamedTemporaryFile(delete=False)
        
        # Set up test environment
        os.environ['MODE'] = 'DRY_RUN'
        os.environ['MAX_ORDER_USD'] = '100'
        os.environ['MAX_ORDERS_PER_MINUTE'] = '10'
        os.environ['MANUAL_APPROVAL_COUNT'] = '0'
        os.environ['LOG_PATH'] = self.temp_log.name
        os.environ['TRADINGVIEW_WEBHOOK_SECRET'] = 'test_secret'
        
        # Reload modules to pick up new env vars
        import importlib
        import config
        import safe_order
        import tradingview_webhook
        importlib.reload(config)
        importlib.reload(safe_order)
        importlib.reload(tradingview_webhook)
        
        # Clear rate limit tracking
        safe_order._order_timestamps = []
    
    def tearDown(self):
        """Clean up test environment."""
        os.environ.clear()
        os.environ.update(self.original_env)
        try:
            os.unlink(self.temp_log.name)
        except:
            pass
    
    def test_complete_webhook_to_order_flow(self):
        """Test complete flow from webhook to order submission."""
        from safe_order import submit_order
        
        # Create mock client
        mock_client = Mock()
        mock_client.place_order.return_value = {'status': 'success', 'order_id': '12345'}
        
        # Simulate webhook payload
        webhook_payload = {
            'symbol': 'BTC-USD',
            'action': 'buy',
            'size_usd': 50.0,
            'strategy': 'TestStrategy'
        }
        
        # Submit order via safe_order
        result = submit_order(
            client=mock_client,
            symbol=webhook_payload['symbol'],
            side=webhook_payload['action'],
            size_usd=webhook_payload['size_usd'],
            metadata={'source': 'tradingview', 'strategy': webhook_payload['strategy']}
        )
        
        # Verify result
        self.assertEqual(result['status'], 'dry_run')
        
        # Verify audit log was created
        with open(self.temp_log.name, 'r') as f:
            logs = f.readlines()
        
        self.assertGreater(len(logs), 0)
        
        # Parse log entry
        log_entry = json.loads(logs[-1])
        self.assertEqual(log_entry['event_type'], 'order_dry_run')
        self.assertEqual(log_entry['data']['symbol'], 'BTC-USD')
        self.assertEqual(log_entry['data']['side'], 'buy')
        self.assertEqual(log_entry['data']['size_usd'], 50.0)
    
    def test_webhook_signature_and_order_validation(self):
        """Test webhook signature validation and order size limits."""
        from tradingview_webhook import verify_signature
        from safe_order import submit_order
        
        # Test signature verification
        payload = json.dumps({
            'symbol': 'BTC-USD',
            'action': 'buy',
            'size_usd': 150.0  # Exceeds limit
        }).encode('utf-8')
        
        signature = hmac.new(
            b'test_secret',
            payload,
            hashlib.sha256
        ).hexdigest()
        
        # Signature should be valid
        self.assertTrue(verify_signature(payload, signature))
        
        # But order should fail due to size limit
        mock_client = Mock()
        with self.assertRaises(ValueError) as cm:
            submit_order(mock_client, 'BTC-USD', 'buy', 150.0)
        
        self.assertIn('exceeds maximum', str(cm.exception))
    
    def test_rate_limiting_across_multiple_webhooks(self):
        """Test rate limiting works across multiple webhook requests."""
        from safe_order import submit_order
        
        # Lower the rate limit for this test
        os.environ['MAX_ORDERS_PER_MINUTE'] = '2'
        import importlib
        import config
        import safe_order
        importlib.reload(config)
        importlib.reload(safe_order)
        
        # Clear rate limit
        safe_order._order_timestamps = []
        
        mock_client = Mock()
        
        # First 2 orders should succeed
        submit_order(mock_client, 'BTC-USD', 'buy', 10.0)
        submit_order(mock_client, 'ETH-USD', 'buy', 10.0)
        
        # Third order should fail
        with self.assertRaises(RuntimeError) as cm:
            submit_order(mock_client, 'SOL-USD', 'buy', 10.0)
        
        self.assertIn('Rate limit exceeded', str(cm.exception))


if __name__ == '__main__':
    unittest.main()
