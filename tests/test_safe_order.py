"""
Tests for safe_order module
"""

import unittest
import os
import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch
from datetime import datetime

# Mock config before importing safe_order
with patch.dict(os.environ, {
    'MODE': 'DRY_RUN',
    'MAX_ORDER_USD': '100.0',
    'MAX_ORDERS_PER_MINUTE': '5',
    'MANUAL_APPROVAL_COUNT': '0',
    'LOG_PATH': '/tmp/test_trade_audit.log'
}):
    import safe_order


class TestSafeOrder(unittest.TestCase):
    
    def setUp(self):
        """Set up test fixtures."""
        # Create temporary log file
        self.temp_dir = tempfile.mkdtemp()
        self.log_path = os.path.join(self.temp_dir, 'trade_audit.log')
        
        # Patch config values
        safe_order.LOG_PATH = self.log_path
        safe_order.MODE = 'DRY_RUN'
        safe_order.MAX_ORDER_USD = 100.0
        safe_order.MAX_ORDERS_PER_MINUTE = 5
        safe_order.MANUAL_APPROVAL_COUNT = 0
        safe_order.COINBASE_ACCOUNT_ID = 'test-account-id'
        safe_order.CONFIRM_LIVE = False
        
        # Reset rate limiting state
        safe_order._order_timestamps = []
        safe_order._order_count = 0
        
    def tearDown(self):
        """Clean up test fixtures."""
        # Clean up temp files
        if os.path.exists(self.log_path):
            os.remove(self.log_path)
        if os.path.exists(self.temp_dir):
            os.rmdir(self.temp_dir)
    
    def test_validate_mode_dry_run(self):
        """Test mode validation for DRY_RUN mode."""
        safe_order.MODE = 'DRY_RUN'
        # Should not raise
        safe_order.validate_mode_and_account()
    
    def test_validate_mode_sandbox(self):
        """Test mode validation for SANDBOX mode."""
        safe_order.MODE = 'SANDBOX'
        # Should not raise
        safe_order.validate_mode_and_account()
    
    def test_validate_mode_live_missing_account(self):
        """Test mode validation fails when LIVE mode missing account ID."""
        safe_order.MODE = 'LIVE'
        safe_order.COINBASE_ACCOUNT_ID = ''
        
        with self.assertRaises(RuntimeError) as ctx:
            safe_order.validate_mode_and_account()
        
        self.assertIn('COINBASE_ACCOUNT_ID', str(ctx.exception))
    
    def test_validate_mode_live_missing_confirm(self):
        """Test mode validation fails when LIVE mode missing CONFIRM_LIVE."""
        safe_order.MODE = 'LIVE'
        safe_order.COINBASE_ACCOUNT_ID = 'test-account'
        safe_order.CONFIRM_LIVE = False
        
        with self.assertRaises(RuntimeError) as ctx:
            safe_order.validate_mode_and_account()
        
        self.assertIn('CONFIRM_LIVE', str(ctx.exception))
    
    def test_validate_mode_invalid(self):
        """Test mode validation fails for invalid mode."""
        safe_order.MODE = 'INVALID'
        
        with self.assertRaises(RuntimeError) as ctx:
            safe_order.validate_mode_and_account()
        
        self.assertIn('Invalid MODE', str(ctx.exception))
    
    def test_submit_order_dry_run(self):
        """Test order submission in DRY_RUN mode."""
        safe_order.MODE = 'DRY_RUN'
        
        mock_client = MagicMock()
        
        result = safe_order.submit_order(
            mock_client,
            symbol='BTC-USD',
            side='buy',
            size_usd=50.0
        )
        
        self.assertEqual(result['status'], 'dry_run')
        self.assertIn('message', result)
        
        # Client should not be called in dry run
        mock_client.place_order.assert_not_called()
    
    def test_submit_order_exceeds_max_usd(self):
        """Test order rejection when size exceeds MAX_ORDER_USD."""
        safe_order.MODE = 'DRY_RUN'
        safe_order.MAX_ORDER_USD = 100.0
        
        mock_client = MagicMock()
        
        with self.assertRaises(RuntimeError) as ctx:
            safe_order.submit_order(
                mock_client,
                symbol='BTC-USD',
                side='buy',
                size_usd=150.0
            )
        
        self.assertIn('MAX_ORDER_USD', str(ctx.exception))
    
    def test_rate_limiting(self):
        """Test rate limiting functionality."""
        safe_order.MODE = 'DRY_RUN'
        safe_order.MAX_ORDERS_PER_MINUTE = 3
        
        mock_client = MagicMock()
        
        # Submit 3 orders (at limit)
        for i in range(3):
            result = safe_order.submit_order(
                mock_client,
                symbol='BTC-USD',
                side='buy',
                size_usd=10.0
            )
            self.assertEqual(result['status'], 'dry_run')
        
        # 4th order should fail due to rate limit
        with self.assertRaises(RuntimeError) as ctx:
            safe_order.submit_order(
                mock_client,
                symbol='BTC-USD',
                side='buy',
                size_usd=10.0
            )
        
        self.assertIn('Rate limit', str(ctx.exception))
    
    def test_manual_approval_required(self):
        """Test manual approval for first N orders."""
        safe_order.MODE = 'DRY_RUN'
        safe_order.MANUAL_APPROVAL_COUNT = 2
        safe_order._order_count = 0
        
        mock_client = MagicMock()
        
        # First order should require approval
        result = safe_order.submit_order(
            mock_client,
            symbol='BTC-USD',
            side='buy',
            size_usd=10.0
        )
        
        self.assertEqual(result['status'], 'pending_approval')
        self.assertIn('order', result)
    
    def test_audit_logging(self):
        """Test that audit logs are written."""
        safe_order.MODE = 'DRY_RUN'
        
        mock_client = MagicMock()
        
        safe_order.submit_order(
            mock_client,
            symbol='BTC-USD',
            side='buy',
            size_usd=50.0
        )
        
        # Check that log file was created and has content
        self.assertTrue(os.path.exists(self.log_path))
        
        with open(self.log_path, 'r') as f:
            content = f.read()
            self.assertIn('ORDER_REQUEST', content)
            self.assertIn('BTC-USD', content)


class TestPendingApprovals(unittest.TestCase):
    
    def setUp(self):
        """Set up test fixtures."""
        self.temp_dir = tempfile.mkdtemp()
        self.log_path = os.path.join(self.temp_dir, 'trade_audit.log')
        
        safe_order.LOG_PATH = self.log_path
        safe_order._pending_approvals_path = None
        safe_order._order_count = 0
    
    def tearDown(self):
        """Clean up test fixtures."""
        # Clean up temp files
        approvals_path = safe_order._get_pending_approvals_path()
        if approvals_path and approvals_path.exists():
            approvals_path.unlink()
        if os.path.exists(self.log_path):
            os.remove(self.log_path)
    
    def test_approve_pending_order(self):
        """Test approving a pending order."""
        # Create a pending order
        approvals = {
            "pending": [
                {"order_id": "test_123", "symbol": "BTC-USD", "side": "buy"}
            ],
            "approved": [],
            "rejected": []
        }
        safe_order._save_pending_approvals(approvals)
        
        # Approve it
        result = safe_order.approve_pending_order("test_123")
        self.assertTrue(result)
        
        # Check it's now in approved list
        updated = safe_order._load_pending_approvals()
        self.assertEqual(len(updated["pending"]), 0)
        self.assertEqual(len(updated["approved"]), 1)
        self.assertEqual(updated["approved"][0]["order_id"], "test_123")
    
    def test_reject_pending_order(self):
        """Test rejecting a pending order."""
        # Create a pending order
        approvals = {
            "pending": [
                {"order_id": "test_456", "symbol": "ETH-USD", "side": "sell"}
            ],
            "approved": [],
            "rejected": []
        }
        safe_order._save_pending_approvals(approvals)
        
        # Reject it
        result = safe_order.reject_pending_order("test_456", "Test rejection")
        self.assertTrue(result)
        
        # Check it's now in rejected list
        updated = safe_order._load_pending_approvals()
        self.assertEqual(len(updated["pending"]), 0)
        self.assertEqual(len(updated["rejected"]), 1)
        self.assertEqual(updated["rejected"][0]["order_id"], "test_456")
        self.assertEqual(updated["rejected"][0]["rejection_reason"], "Test rejection")


if __name__ == '__main__':
    unittest.main()
