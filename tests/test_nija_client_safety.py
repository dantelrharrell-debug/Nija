"""
Tests for nija_client safety checks
"""

import unittest
from unittest.mock import patch, MagicMock
import sys
import os


class TestNijaClientSafety(unittest.TestCase):
    
    @patch('nija_client.MODE', 'DRY_RUN')
    @patch('nija_client.COINBASE_ACCOUNT_ID', '')
    @patch('nija_client.CONFIRM_LIVE', False)
    def test_check_live_safety_dry_run(self):
        """Test safety check passes in DRY_RUN mode."""
        from nija_client import check_live_safety
        
        # Should not raise
        check_live_safety()
    
    @patch('nija_client.MODE', 'SANDBOX')
    @patch('nija_client.COINBASE_ACCOUNT_ID', '')
    @patch('nija_client.CONFIRM_LIVE', False)
    def test_check_live_safety_sandbox(self):
        """Test safety check passes in SANDBOX mode."""
        from nija_client import check_live_safety
        
        # Should not raise
        check_live_safety()
    
    @patch('nija_client.MODE', 'LIVE')
    @patch('nija_client.COINBASE_ACCOUNT_ID', '')
    @patch('nija_client.CONFIRM_LIVE', False)
    def test_check_live_safety_live_missing_account(self):
        """Test safety check fails when LIVE mode missing account ID."""
        from nija_client import check_live_safety
        
        with self.assertRaises(RuntimeError) as ctx:
            check_live_safety()
        
        self.assertIn('COINBASE_ACCOUNT_ID', str(ctx.exception))
    
    @patch('nija_client.MODE', 'LIVE')
    @patch('nija_client.COINBASE_ACCOUNT_ID', 'test-account-123')
    @patch('nija_client.CONFIRM_LIVE', False)
    def test_check_live_safety_live_missing_confirm(self):
        """Test safety check fails when LIVE mode missing CONFIRM_LIVE."""
        from nija_client import check_live_safety
        
        with self.assertRaises(RuntimeError) as ctx:
            check_live_safety()
        
        self.assertIn('CONFIRM_LIVE', str(ctx.exception))
    
    @patch('nija_client.MODE', 'LIVE')
    @patch('nija_client.COINBASE_ACCOUNT_ID', 'test-account-123')
    @patch('nija_client.CONFIRM_LIVE', True)
    def test_check_live_safety_live_all_set(self):
        """Test safety check passes when LIVE mode properly configured."""
        from nija_client import check_live_safety
        
        # Should not raise
        check_live_safety()
    
    @patch('nija_client.MODE', 'INVALID_MODE')
    def test_check_live_safety_invalid_mode(self):
        """Test safety check fails with invalid MODE."""
        from nija_client import check_live_safety
        
        with self.assertRaises(RuntimeError) as ctx:
            check_live_safety()
        
        self.assertIn('Invalid MODE', str(ctx.exception))
    
    def test_check_api_key_permissions(self):
        """Test API key permissions check."""
        from nija_client import check_api_key_permissions
        
        mock_client = MagicMock()
        
        # Currently this just logs a warning, so should not raise
        # In future when API supports it, this should check for withdraw permission
        check_api_key_permissions(mock_client)


if __name__ == '__main__':
    unittest.main()
