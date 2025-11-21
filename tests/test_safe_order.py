"""
test_safe_order.py - Tests for safe order submission module.
"""

import os
import json
import tempfile
from pathlib import Path

# Set test environment variables before importing
os.environ["MODE"] = "DRY_RUN"
os.environ["MAX_ORDER_USD"] = "100"
os.environ["MAX_ORDERS_PER_MINUTE"] = "5"
os.environ["MANUAL_APPROVAL_COUNT"] = "0"

from safe_order import SafeOrderManager, submit_safe_order, RateLimiter


class TestRateLimiter:
    """Test rate limiter functionality."""
    
    def test_rate_limiter_allows_within_limit(self):
        """Test that rate limiter allows orders within limit."""
        limiter = RateLimiter(max_per_minute=3)
        
        assert limiter.can_submit() is True
        limiter.record_submission()
        
        assert limiter.can_submit() is True
        limiter.record_submission()
        
        assert limiter.can_submit() is True
        limiter.record_submission()
    
    def test_rate_limiter_blocks_over_limit(self):
        """Test that rate limiter blocks orders over limit."""
        limiter = RateLimiter(max_per_minute=2)
        
        limiter.record_submission()
        limiter.record_submission()
        
        # Third submission should be blocked
        assert limiter.can_submit() is False
        assert limiter.wait_time() > 0


class TestSafeOrderManager:
    """Test safe order manager functionality."""
    
    def setup_method(self):
        """Setup test environment before each test."""
        # Create temporary log file
        self.temp_dir = tempfile.mkdtemp()
        self.log_path = Path(self.temp_dir) / "test_orders.log"
        os.environ["LOG_PATH"] = str(self.log_path)
        
        # Reset to DRY_RUN mode for tests
        os.environ["MODE"] = "DRY_RUN"
        os.environ["MAX_ORDER_USD"] = "100"
        os.environ["MAX_ORDERS_PER_MINUTE"] = "5"
        os.environ["MANUAL_APPROVAL_COUNT"] = "0"
    
    def teardown_method(self):
        """Cleanup after each test."""
        import shutil
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir)
    
    def test_dry_run_mode(self):
        """Test that DRY_RUN mode doesn't submit real orders."""
        # Force reimport to pick up new env vars
        import importlib
        import safe_order
        importlib.reload(safe_order)
        
        result = safe_order.submit_safe_order("BTC-USD", "buy", 50.0)
        
        assert result["status"] == "dry_run"
        assert "DRY_RUN" in result["message"]
    
    def test_order_size_limit(self):
        """Test that orders exceeding MAX_ORDER_USD are rejected."""
        import importlib
        import safe_order
        importlib.reload(safe_order)
        
        result = safe_order.submit_safe_order("BTC-USD", "buy", 150.0)
        
        assert result["status"] == "rejected"
        assert "MAX_ORDER_USD" in result["error"]
    
    def test_rate_limiting(self):
        """Test that rate limiting works correctly."""
        import importlib
        import safe_order
        importlib.reload(safe_order)
        
        # Submit 5 orders (at the limit)
        for i in range(5):
            result = safe_order.submit_safe_order("BTC-USD", "buy", 10.0, f"order_{i}")
            assert result["status"] == "dry_run"
        
        # 6th order should be rate limited
        result = safe_order.submit_safe_order("BTC-USD", "buy", 10.0, "order_6")
        assert result["status"] == "rate_limited"
        assert "Rate limit exceeded" in result["error"]
    
    def test_manual_approval(self):
        """Test manual approval for first N trades."""
        os.environ["MANUAL_APPROVAL_COUNT"] = "2"
        
        import importlib
        import safe_order
        importlib.reload(safe_order)
        
        # First order should require approval
        result = safe_order.submit_safe_order("BTC-USD", "buy", 10.0, "order_1")
        assert result["status"] == "pending_approval"
        
        # Approve the order
        manager = safe_order.get_order_manager()
        manager.approve_order("order_1")
        
        # Now it should go through
        result = safe_order.submit_safe_order("BTC-USD", "buy", 10.0, "order_1")
        assert result["status"] == "dry_run"
    
    def test_audit_logging(self):
        """Test that all orders are logged to audit file."""
        import importlib
        import safe_order
        importlib.reload(safe_order)
        
        # Submit an order
        safe_order.submit_safe_order("BTC-USD", "buy", 50.0, "test_order")
        
        # Check log file exists and contains entry
        assert self.log_path.exists()
        
        with open(self.log_path, 'r') as f:
            log_entry = json.loads(f.readline())
        
        assert log_entry["mode"] == "DRY_RUN"
        assert log_entry["status"] == "dry_run"
        assert log_entry["order_request"]["client_order_id"] == "test_order"
        assert log_entry["order_request"]["symbol"] == "BTC-USD"


class TestLiveModeValidation:
    """Test LIVE mode validation."""
    
    def test_live_mode_requires_account_id(self):
        """Test that LIVE mode requires COINBASE_ACCOUNT_ID."""
        os.environ["MODE"] = "LIVE"
        os.environ["COINBASE_ACCOUNT_ID"] = ""
        os.environ["CONFIRM_LIVE"] = "true"
        
        import importlib
        import safe_order
        importlib.reload(safe_order)
        
        result = safe_order.submit_safe_order("BTC-USD", "buy", 10.0)
        assert result["status"] == "rejected"
        assert "COINBASE_ACCOUNT_ID" in result["error"]
    
    def test_live_mode_requires_confirm(self):
        """Test that LIVE mode requires CONFIRM_LIVE=true."""
        os.environ["MODE"] = "LIVE"
        os.environ["COINBASE_ACCOUNT_ID"] = "test-account"
        os.environ["CONFIRM_LIVE"] = "false"
        
        import importlib
        import safe_order
        importlib.reload(safe_order)
        
        result = safe_order.submit_safe_order("BTC-USD", "buy", 10.0)
        assert result["status"] == "rejected"
        assert "CONFIRM_LIVE" in result["error"]


if __name__ == "__main__":
    # Run tests if pytest is available
    try:
        import pytest
        pytest.main([__file__, "-v"])
    except ImportError:
        print("pytest not available, running basic tests...")
        
        # Run basic tests manually
        test_limiter = TestRateLimiter()
        test_limiter.test_rate_limiter_allows_within_limit()
        test_limiter.test_rate_limiter_blocks_over_limit()
        print("✓ Rate limiter tests passed")
        
        test_manager = TestSafeOrderManager()
        test_manager.setup_method()
        test_manager.test_dry_run_mode()
        test_manager.test_order_size_limit()
        test_manager.teardown_method()
        print("✓ Safe order manager tests passed")
