"""
test_safe_trading.py - Comprehensive tests for safe trading stack

Tests the MODE-based trading system, safety checks, rate limiting,
order validation, manual approval, and webhook integration.
"""

import os
import sys
import json
import hmac
import hashlib
import tempfile
import unittest
from unittest.mock import Mock, patch, MagicMock

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestConfig(unittest.TestCase):
    """Test configuration module."""
    
    def setUp(self):
        """Set up test environment."""
        # Save original env vars
        self.original_env = os.environ.copy()
    
    def tearDown(self):
        """Restore original environment."""
        os.environ.clear()
        os.environ.update(self.original_env)
    
    def test_default_mode(self):
        """Test default MODE is DRY_RUN."""
        os.environ.pop('MODE', None)
        import importlib
        import config
        importlib.reload(config)
        self.assertEqual(config.MODE, 'DRY_RUN')
    
    def test_mode_uppercase(self):
        """Test MODE is converted to uppercase."""
        os.environ['MODE'] = 'live'
        import importlib
        import config
        importlib.reload(config)
        self.assertEqual(config.MODE, 'LIVE')
    
    def test_max_order_usd_default(self):
        """Test default MAX_ORDER_USD."""
        os.environ.pop('MAX_ORDER_USD', None)
        import importlib
        import config
        importlib.reload(config)
        self.assertEqual(config.MAX_ORDER_USD, 100.0)
    
    def test_max_orders_per_minute_default(self):
        """Test default MAX_ORDERS_PER_MINUTE."""
        os.environ.pop('MAX_ORDERS_PER_MINUTE', None)
        import importlib
        import config
        importlib.reload(config)
        self.assertEqual(config.MAX_ORDERS_PER_MINUTE, 5)


class TestSafetyChecks(unittest.TestCase):
    """Test safety checks in nija_client."""
    
    def setUp(self):
        """Set up test environment."""
        self.original_env = os.environ.copy()
    
    def tearDown(self):
        """Restore original environment."""
        os.environ.clear()
        os.environ.update(self.original_env)
    
    def test_dry_run_mode(self):
        """Test DRY_RUN mode passes safety checks."""
        os.environ['MODE'] = 'DRY_RUN'
        
        # Need to reload both config and nija_client
        import importlib
        import config
        import nija_client
        importlib.reload(config)
        importlib.reload(nija_client)
        
        from nija_client import check_live_safety
        # Should not raise any exception
        check_live_safety()
    
    def test_sandbox_mode(self):
        """Test SANDBOX mode passes safety checks."""
        os.environ['MODE'] = 'SANDBOX'
        
        # Need to reload both config and nija_client
        import importlib
        import config
        import nija_client
        importlib.reload(config)
        importlib.reload(nija_client)
        
        from nija_client import check_live_safety
        # Should not raise any exception
        check_live_safety()
    
    def test_live_mode_without_account_id(self):
        """Test LIVE mode fails without COINBASE_ACCOUNT_ID."""
        os.environ['MODE'] = 'LIVE'
        os.environ.pop('COINBASE_ACCOUNT_ID', None)
        os.environ['CONFIRM_LIVE'] = 'true'
        
        # Need to reload both config and nija_client
        import importlib
        import config
        import nija_client
        importlib.reload(config)
        importlib.reload(nija_client)
        
        from nija_client import check_live_safety
        with self.assertRaises(RuntimeError) as cm:
            check_live_safety()
        self.assertIn('COINBASE_ACCOUNT_ID', str(cm.exception))
    
    def test_live_mode_without_confirm(self):
        """Test LIVE mode fails without CONFIRM_LIVE."""
        os.environ['MODE'] = 'LIVE'
        os.environ['COINBASE_ACCOUNT_ID'] = 'test-account'
        os.environ['CONFIRM_LIVE'] = 'false'
        
        # Need to reload both config and nija_client
        import importlib
        import config
        import nija_client
        importlib.reload(config)
        importlib.reload(nija_client)
        
        from nija_client import check_live_safety
        with self.assertRaises(RuntimeError) as cm:
            check_live_safety()
        self.assertIn('CONFIRM_LIVE=true', str(cm.exception))
    
    def test_live_mode_valid(self):
        """Test LIVE mode passes with proper settings."""
        os.environ['MODE'] = 'LIVE'
        os.environ['COINBASE_ACCOUNT_ID'] = 'test-account'
        os.environ['CONFIRM_LIVE'] = 'true'
        
        # Need to reload both config and nija_client
        import importlib
        import config
        import nija_client
        importlib.reload(config)
        importlib.reload(nija_client)
        
        from nija_client import check_live_safety
        # Should not raise any exception
        check_live_safety()
    
    def test_invalid_mode(self):
        """Test invalid MODE raises error."""
        os.environ['MODE'] = 'INVALID'
        
        # Need to reload both config and nija_client
        import importlib
        import config
        import nija_client
        importlib.reload(config)
        importlib.reload(nija_client)
        
        from nija_client import check_live_safety
        with self.assertRaises(RuntimeError) as cm:
            check_live_safety()
        self.assertIn('Invalid MODE', str(cm.exception))


class TestSafeOrder(unittest.TestCase):
    """Test safe_order module."""
    
    def setUp(self):
        """Set up test environment."""
        self.original_env = os.environ.copy()
        self.temp_log = tempfile.NamedTemporaryFile(delete=False)
        os.environ['MODE'] = 'DRY_RUN'
        os.environ['MAX_ORDER_USD'] = '100'
        os.environ['MAX_ORDERS_PER_MINUTE'] = '3'
        os.environ['MANUAL_APPROVAL_COUNT'] = '0'
        os.environ['LOG_PATH'] = self.temp_log.name
        
        # Reload modules to pick up new env vars
        import importlib
        import config
        importlib.reload(config)
        import safe_order
        importlib.reload(safe_order)
        
        # Clear rate limit tracking
        safe_order._order_timestamps = []
    
    def tearDown(self):
        """Clean up test environment."""
        os.environ.clear()
        os.environ.update(self.original_env)
        os.unlink(self.temp_log.name)
        
        # Clean up pending approvals file
        try:
            os.unlink('/tmp/pending-approvals.json')
        except:
            pass
    
    def test_order_size_validation(self):
        """Test order size is validated."""
        from safe_order import submit_order
        
        mock_client = Mock()
        
        with self.assertRaises(ValueError) as cm:
            submit_order(mock_client, 'BTC-USD', 'buy', 150.0)
        
        self.assertIn('exceeds maximum', str(cm.exception))
    
    def test_rate_limiting(self):
        """Test rate limiting works."""
        from safe_order import submit_order
        
        mock_client = Mock()
        
        # Should allow 3 orders
        for _ in range(3):
            submit_order(mock_client, 'BTC-USD', 'buy', 10.0)
        
        # 4th order should fail
        with self.assertRaises(RuntimeError) as cm:
            submit_order(mock_client, 'BTC-USD', 'buy', 10.0)
        
        self.assertIn('Rate limit exceeded', str(cm.exception))
    
    def test_dry_run_mode(self):
        """Test DRY_RUN mode doesn't call client."""
        from safe_order import submit_order
        
        mock_client = Mock()
        result = submit_order(mock_client, 'BTC-USD', 'buy', 50.0)
        
        # Should not call client.place_order
        mock_client.place_order.assert_not_called()
        self.assertEqual(result['status'], 'dry_run')
    
    def test_manual_approval(self):
        """Test manual approval mechanism."""
        os.environ['MANUAL_APPROVAL_COUNT'] = '2'
        
        import importlib
        import config
        importlib.reload(config)
        import safe_order
        importlib.reload(safe_order)
        
        # Clear tracking
        safe_order._order_timestamps = []
        safe_order.clear_pending_orders()
        
        from safe_order import submit_order, approve_pending_orders, get_pending_orders
        
        mock_client = Mock()
        
        # First 2 orders should be pending
        result1 = submit_order(mock_client, 'BTC-USD', 'buy', 10.0)
        self.assertEqual(result1['status'], 'pending_approval')
        
        result2 = submit_order(mock_client, 'ETH-USD', 'buy', 20.0)
        self.assertEqual(result2['status'], 'pending_approval')
        
        # Check pending orders
        pending = get_pending_orders()
        self.assertEqual(len(pending), 2)
        
        # Approve orders
        approve_pending_orders(count=2)
        
        # Next order should go through
        result3 = submit_order(mock_client, 'SOL-USD', 'buy', 30.0)
        self.assertEqual(result3['status'], 'dry_run')
    
    def test_audit_logging(self):
        """Test audit logging creates log entries."""
        from safe_order import submit_order
        
        mock_client = Mock()
        submit_order(mock_client, 'BTC-USD', 'buy', 50.0)
        
        # Check log file was created and has content
        with open(self.temp_log.name, 'r') as f:
            logs = f.readlines()
        
        self.assertGreater(len(logs), 0)
        
        # Parse last log entry
        log_entry = json.loads(logs[-1])
        self.assertEqual(log_entry['event_type'], 'order_dry_run')
        self.assertEqual(log_entry['mode'], 'DRY_RUN')


class TestWebhook(unittest.TestCase):
    """Test TradingView webhook."""
    
    def setUp(self):
        """Set up test environment."""
        self.original_env = os.environ.copy()
        os.environ['TRADINGVIEW_WEBHOOK_SECRET'] = 'test_secret'
        
        import importlib
        import config
        importlib.reload(config)
    
    def tearDown(self):
        """Restore environment."""
        os.environ.clear()
        os.environ.update(self.original_env)
    
    def test_signature_verification_valid(self):
        """Test valid signature is accepted."""
        from tradingview_webhook import verify_signature
        
        payload = b'{"symbol": "BTC-USD", "action": "buy"}'
        signature = hmac.new(
            b'test_secret',
            payload,
            hashlib.sha256
        ).hexdigest()
        
        self.assertTrue(verify_signature(payload, signature))
    
    def test_signature_verification_invalid(self):
        """Test invalid signature is rejected."""
        from tradingview_webhook import verify_signature
        
        payload = b'{"symbol": "BTC-USD", "action": "buy"}'
        signature = 'invalid_signature'
        
        self.assertFalse(verify_signature(payload, signature))
    
    def test_signature_verification_empty(self):
        """Test empty signature is rejected."""
        from tradingview_webhook import verify_signature
        
        payload = b'{"symbol": "BTC-USD", "action": "buy"}'
        
        self.assertFalse(verify_signature(payload, ''))
        self.assertFalse(verify_signature(payload, None))


if __name__ == '__main__':
    unittest.main()
