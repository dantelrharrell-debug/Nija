"""
safe_order.py - Centralized order submission with safety checks and audit logging.

This module enforces:
- MODE and account requirements validation
- Rate limiting (MAX_ORDERS_PER_MINUTE)
- Order size limits (MAX_ORDER_USD)
- Manual approval for first N trades (MANUAL_APPROVAL_COUNT)
- Comprehensive audit logging to LOG_PATH
"""

import os
import time
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Optional

from config import (
    MODE,
    COINBASE_ACCOUNT_ID,
    CONFIRM_LIVE,
    MAX_ORDER_USD,
    MAX_ORDERS_PER_MINUTE,
    MANUAL_APPROVAL_COUNT,
    LOG_PATH
)

logger = logging.getLogger("SafeOrder")


class RateLimiter:
    """Simple rate limiter for order submission."""
    
    def __init__(self, max_per_minute: int):
        self.max_per_minute = max_per_minute
        self.timestamps = []
    
    def can_submit(self) -> bool:
        """Check if we can submit another order within rate limit."""
        now = time.time()
        # Remove timestamps older than 1 minute
        self.timestamps = [ts for ts in self.timestamps if now - ts < 60]
        return len(self.timestamps) < self.max_per_minute
    
    def record_submission(self):
        """Record a new order submission."""
        self.timestamps.append(time.time())
    
    def wait_time(self) -> float:
        """Return seconds to wait before next submission is allowed."""
        if self.can_submit():
            return 0.0
        now = time.time()
        oldest = min(self.timestamps)
        return max(0.0, 60 - (now - oldest))


class SafeOrderManager:
    """Manages safe order submission with all safety checks."""
    
    def __init__(self):
        self.rate_limiter = RateLimiter(MAX_ORDERS_PER_MINUTE)
        self.log_path = Path(LOG_PATH)
        self.approval_path = self.log_path.parent / "pending_approvals.json"
        self.order_count = self._get_order_count()
        
        # Ensure log directory exists
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        
        logger.info(f"SafeOrderManager initialized - MODE={MODE}, Orders submitted: {self.order_count}")
    
    def _get_order_count(self) -> int:
        """Get count of orders submitted so far from log file."""
        if not self.log_path.exists():
            return 0
        
        count = 0
        try:
            with open(self.log_path, 'r') as f:
                for line in f:
                    try:
                        entry = json.loads(line.strip())
                        # Only count orders that actually went through or would go through
                        if entry.get("status") in ["ready_to_submit", "submitted", "completed"]:
                            count += 1
                    except json.JSONDecodeError:
                        continue
        except Exception as e:
            logger.warning(f"Could not count orders from log: {e}")
        
        return count
    
    def _load_pending_approvals(self) -> Dict[str, Any]:
        """Load pending approvals from file."""
        if not self.approval_path.exists():
            return {"pending": [], "approved": []}
        
        try:
            with open(self.approval_path, 'r') as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Failed to load pending approvals: {e}")
            return {"pending": [], "approved": []}
    
    def _save_pending_approvals(self, data: Dict[str, Any]):
        """Save pending approvals to file."""
        try:
            with open(self.approval_path, 'w') as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            logger.error(f"Failed to save pending approvals: {e}")
    
    def _log_order(self, order_request: Dict[str, Any], response: Dict[str, Any], status: str):
        """Log order request and response to audit log."""
        log_entry = {
            "timestamp": datetime.now().astimezone().isoformat(),
            "mode": MODE,
            "status": status,
            "order_request": order_request,
            "response": response
        }
        
        try:
            with open(self.log_path, 'a') as f:
                f.write(json.dumps(log_entry) + '\n')
            logger.info(f"Order logged: {status}")
        except Exception as e:
            logger.error(f"Failed to log order: {e}")
    
    def _validate_live_mode(self):
        """Validate requirements for LIVE mode."""
        if MODE == "LIVE":
            if not COINBASE_ACCOUNT_ID:
                raise RuntimeError(
                    "MODE=LIVE requires COINBASE_ACCOUNT_ID to be set"
                )
            if not CONFIRM_LIVE:
                raise RuntimeError(
                    "MODE=LIVE requires CONFIRM_LIVE=true to prevent accidental trading"
                )
    
    def _check_manual_approval(self, order_id: str) -> bool:
        """
        Check if order needs manual approval.
        Returns True if order can proceed, False if it needs approval.
        """
        if MANUAL_APPROVAL_COUNT <= 0:
            return True
        
        if self.order_count >= MANUAL_APPROVAL_COUNT:
            return True
        
        # Check if this order has been approved
        approvals = self._load_pending_approvals()
        if order_id in approvals.get("approved", []):
            return True
        
        # Add to pending if not already there
        if order_id not in approvals.get("pending", []):
            approvals.setdefault("pending", []).append(order_id)
            self._save_pending_approvals(approvals)
            logger.warning(
                f"Order {order_id} requires manual approval "
                f"({self.order_count + 1}/{MANUAL_APPROVAL_COUNT}). "
                f"Add to 'approved' list in {self.approval_path}"
            )
        
        return False
    
    def submit_order(
        self,
        symbol: str,
        side: str,
        size_usd: float,
        client_order_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Submit an order with all safety checks.
        
        Args:
            symbol: Trading pair (e.g., "BTC-USD")
            side: "buy" or "sell"
            size_usd: Order size in USD
            client_order_id: Optional client order ID for tracking
        
        Returns:
            Dict with order response and status
        """
        # Generate order ID if not provided
        if not client_order_id:
            client_order_id = f"order_{int(time.time() * 1000)}"
        
        order_request = {
            "client_order_id": client_order_id,
            "symbol": symbol,
            "side": side,
            "size_usd": size_usd
        }
        
        # Validate LIVE mode requirements
        try:
            self._validate_live_mode()
        except RuntimeError as e:
            logger.error(f"Live mode validation failed: {e}")
            response = {"error": str(e), "status": "rejected"}
            self._log_order(order_request, response, "rejected")
            return response
        
        # Check order size limit
        if size_usd > MAX_ORDER_USD:
            error_msg = f"Order size ${size_usd} exceeds MAX_ORDER_USD=${MAX_ORDER_USD}"
            logger.error(error_msg)
            response = {"error": error_msg, "status": "rejected"}
            self._log_order(order_request, response, "rejected")
            return response
        
        # Check rate limit
        if not self.rate_limiter.can_submit():
            wait_time = self.rate_limiter.wait_time()
            error_msg = f"Rate limit exceeded. Wait {wait_time:.1f}s before next order"
            logger.warning(error_msg)
            response = {"error": error_msg, "status": "rate_limited"}
            self._log_order(order_request, response, "rate_limited")
            return response
        
        # Check manual approval if needed
        if not self._check_manual_approval(client_order_id):
            response = {
                "status": "pending_approval",
                "message": f"Order requires manual approval. Check {self.approval_path}"
            }
            self._log_order(order_request, response, "pending_approval")
            return response
        
        # Record rate limit before submission (applies to all modes)
        self.rate_limiter.record_submission()
        
        # DRY_RUN mode - don't submit real orders
        if MODE == "DRY_RUN":
            response = {
                "status": "dry_run",
                "message": f"DRY_RUN: {side.upper()} ${size_usd} {symbol}"
            }
            logger.info(f"DRY_RUN: {side.upper()} ${size_usd} {symbol}")
            self._log_order(order_request, response, "dry_run")
            return response
        
        # SANDBOX or LIVE mode - prepare to submit
        # Here we would call the actual Coinbase client
        # For now, return a mock response indicating where real submission would happen
        response = {
            "status": "ready_to_submit",
            "mode": MODE,
            "message": "Order passed all safety checks, ready for actual submission to Coinbase"
        }
        
        self._log_order(order_request, response, "ready_to_submit")
        self.order_count += 1
        
        return response
    
    def approve_order(self, order_id: str):
        """Manually approve a pending order."""
        approvals = self._load_pending_approvals()
        
        if order_id in approvals.get("pending", []):
            approvals["pending"].remove(order_id)
            approvals.setdefault("approved", []).append(order_id)
            self._save_pending_approvals(approvals)
            logger.info(f"Order {order_id} approved")
            return True
        else:
            logger.warning(f"Order {order_id} not found in pending approvals")
            return False
    
    def get_pending_approvals(self) -> list:
        """Get list of orders pending approval."""
        approvals = self._load_pending_approvals()
        return approvals.get("pending", [])


# Global instance for easy access
_manager = None

def get_order_manager() -> SafeOrderManager:
    """Get or create the global SafeOrderManager instance."""
    global _manager
    if _manager is None:
        _manager = SafeOrderManager()
    return _manager


def submit_safe_order(
    symbol: str,
    side: str,
    size_usd: float,
    client_order_id: Optional[str] = None
) -> Dict[str, Any]:
    """
    Convenience function to submit an order through the safe order manager.
    
    Args:
        symbol: Trading pair (e.g., "BTC-USD")
        side: "buy" or "sell"
        size_usd: Order size in USD
        client_order_id: Optional client order ID for tracking
    
    Returns:
        Dict with order response and status
    """
    manager = get_order_manager()
    return manager.submit_order(symbol, side, size_usd, client_order_id)


if __name__ == "__main__":
    # Example usage
    logging.basicConfig(level=logging.INFO)
    
    print(f"MODE: {MODE}")
    print(f"MAX_ORDER_USD: ${MAX_ORDER_USD}")
    print(f"MAX_ORDERS_PER_MINUTE: {MAX_ORDERS_PER_MINUTE}")
    print(f"MANUAL_APPROVAL_COUNT: {MANUAL_APPROVAL_COUNT}")
    print(f"LOG_PATH: {LOG_PATH}")
    print()
    
    # Test order submission
    result = submit_safe_order("BTC-USD", "buy", 50.0)
    print(f"Order result: {result}")
