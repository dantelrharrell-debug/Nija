"""
Safe Order Module - Centralized order submission with safety controls

This module provides a safe wrapper around order placement with:
- Mode validation (SANDBOX/DRY_RUN/LIVE)
- Rate limiting
- Order size limits
- Manual approval workflow
- Audit logging
"""

import os
import json
import time
import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Optional

import config

# Setup logging
logger = logging.getLogger("SafeOrder")


class RateLimiter:
    """Simple rate limiter to track orders per minute"""
    
    def __init__(self, max_per_minute: int):
        self.max_per_minute = max_per_minute
        self.order_times = []
    
    def can_place_order(self) -> bool:
        """Check if we can place an order within rate limit"""
        now = time.time()
        # Remove orders older than 1 minute
        self.order_times = [t for t in self.order_times if now - t < 60]
        
        if len(self.order_times) >= self.max_per_minute:
            return False
        
        return True
    
    def record_order(self):
        """Record an order placement"""
        self.order_times.append(time.time())


class SafeOrderManager:
    """Manages safe order placement with all safety controls"""
    
    def __init__(self):
        self.rate_limiter = RateLimiter(config.MAX_ORDERS_PER_MINUTE)
        self.order_count = 0
        self.pending_approvals = []
        
        # Ensure log directory exists
        log_path = Path(config.LOG_PATH)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Pending approvals file
        self.pending_approvals_file = log_path.parent / "pending_approvals.json"
        self._load_pending_approvals()
    
    def _load_pending_approvals(self):
        """Load pending approvals from file"""
        if self.pending_approvals_file.exists():
            try:
                with open(self.pending_approvals_file, 'r') as f:
                    self.pending_approvals = json.load(f)
                logger.info(f"Loaded {len(self.pending_approvals)} pending approvals")
            except Exception as e:
                logger.error(f"Failed to load pending approvals: {e}")
                self.pending_approvals = []
    
    def _save_pending_approvals(self):
        """Save pending approvals to file"""
        try:
            with open(self.pending_approvals_file, 'w') as f:
                json.dump(self.pending_approvals, f, indent=2)
        except Exception as e:
            logger.error(f"Failed to save pending approvals: {e}")
    
    def _audit_log(self, entry: Dict[str, Any]):
        """Write audit log entry"""
        try:
            with open(config.LOG_PATH, 'a') as f:
                timestamp = datetime.utcnow().isoformat()
                log_entry = {
                    "timestamp": timestamp,
                    **entry
                }
                f.write(json.dumps(log_entry) + "\n")
        except Exception as e:
            logger.error(f"Failed to write audit log: {e}")
    
    def validate_order(self, symbol: str, side: str, size_usd: float) -> tuple[bool, str]:
        """
        Validate order against all safety rules
        
        Returns:
            (is_valid, error_message)
        """
        # Check MODE requirements
        if config.MODE == "LIVE":
            if not config.COINBASE_ACCOUNT_ID:
                return False, "LIVE mode requires COINBASE_ACCOUNT_ID"
            if not config.CONFIRM_LIVE:
                return False, "LIVE mode requires CONFIRM_LIVE=true"
        
        # Check order size limit
        if size_usd > config.MAX_ORDER_USD:
            return False, f"Order size ${size_usd:.2f} exceeds MAX_ORDER_USD ${config.MAX_ORDER_USD:.2f}"
        
        # Check rate limit
        if not self.rate_limiter.can_place_order():
            return False, f"Rate limit exceeded: max {config.MAX_ORDERS_PER_MINUTE} orders per minute"
        
        return True, ""
    
    def place_order(
        self,
        client,
        symbol: str,
        side: str,
        size_usd: float,
        metadata: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Place an order with all safety controls
        
        Args:
            client: CoinbaseClient instance
            symbol: Trading pair (e.g., "BTC-USD")
            side: "buy" or "sell"
            size_usd: Order size in USD
            metadata: Optional metadata to include in audit log
        
        Returns:
            Order result dictionary
        """
        # Validate order
        is_valid, error = self.validate_order(symbol, side, size_usd)
        if not is_valid:
            result = {
                "status": "rejected",
                "error": error,
                "symbol": symbol,
                "side": side,
                "size_usd": size_usd
            }
            self._audit_log({
                "action": "order_rejected",
                "result": result,
                "metadata": metadata
            })
            logger.error(f"Order rejected: {error}")
            return result
        
        # Check manual approval requirement
        if config.MANUAL_APPROVAL_COUNT > 0 and self.order_count < config.MANUAL_APPROVAL_COUNT:
            order_id = f"pending_{int(time.time() * 1000)}"
            pending_order = {
                "order_id": order_id,
                "symbol": symbol,
                "side": side,
                "size_usd": size_usd,
                "timestamp": datetime.utcnow().isoformat(),
                "status": "pending_approval",
                "metadata": metadata
            }
            self.pending_approvals.append(pending_order)
            self._save_pending_approvals()
            
            result = {
                "status": "pending_approval",
                "order_id": order_id,
                "message": f"Order requires manual approval ({self.order_count + 1}/{config.MANUAL_APPROVAL_COUNT})",
                "symbol": symbol,
                "side": side,
                "size_usd": size_usd
            }
            
            self._audit_log({
                "action": "order_pending_approval",
                "result": result,
                "metadata": metadata
            })
            
            # Increment order count for pending approvals
            self.order_count += 1
            
            logger.info(f"Order pending approval: {order_id}")
            return result
        
        # Place order based on MODE
        if config.MODE == "SANDBOX" or config.MODE == "DRY_RUN":
            # Simulate order in sandbox/dry-run mode
            result = {
                "status": f"{config.MODE.lower()}_simulated",
                "order_id": f"sim_{int(time.time() * 1000)}",
                "symbol": symbol,
                "side": side,
                "size_usd": size_usd,
                "mode": config.MODE
            }
            logger.info(f"{config.MODE} mode: Simulated {side} ${size_usd:.2f} {symbol}")
        else:
            # LIVE mode - place actual order
            try:
                response = client.place_order(symbol, side, size_usd)
                result = {
                    "status": "live_order_placed",
                    "response": response,
                    "symbol": symbol,
                    "side": side,
                    "size_usd": size_usd,
                    "mode": config.MODE
                }
                logger.info(f"LIVE order placed: {side} ${size_usd:.2f} {symbol}")
            except Exception as e:
                result = {
                    "status": "error",
                    "error": str(e),
                    "symbol": symbol,
                    "side": side,
                    "size_usd": size_usd,
                    "mode": config.MODE
                }
                logger.error(f"Failed to place live order: {e}")
        
        # Record order and update counters
        self.rate_limiter.record_order()
        self.order_count += 1
        
        # Audit log
        self._audit_log({
            "action": "order_placed",
            "result": result,
            "metadata": metadata
        })
        
        return result
    
    def approve_pending_order(self, order_id: str) -> Dict[str, Any]:
        """
        Approve a pending order and place it
        
        Args:
            order_id: ID of the pending order to approve
        
        Returns:
            Result dictionary
        """
        # Find pending order
        pending_order = None
        for i, order in enumerate(self.pending_approvals):
            if order.get("order_id") == order_id:
                pending_order = self.pending_approvals.pop(i)
                break
        
        if not pending_order:
            return {"status": "error", "error": f"Pending order {order_id} not found"}
        
        self._save_pending_approvals()
        
        # Log approval
        self._audit_log({
            "action": "order_approved",
            "order_id": order_id,
            "order": pending_order
        })
        
        logger.info(f"Order {order_id} approved and will be placed on next submission")
        
        return {
            "status": "approved",
            "order_id": order_id,
            "message": "Order approved. Submit again to place."
        }
    
    def get_pending_approvals(self) -> list:
        """Get list of pending approvals"""
        return self.pending_approvals.copy()


# Global instance
_safe_order_manager = None


def get_safe_order_manager() -> SafeOrderManager:
    """Get or create the global SafeOrderManager instance"""
    global _safe_order_manager
    if _safe_order_manager is None:
        _safe_order_manager = SafeOrderManager()
    return _safe_order_manager


def safe_place_order(
    client,
    symbol: str,
    side: str,
    size_usd: float,
    metadata: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    Convenience function to place an order through the safe order manager
    
    Args:
        client: CoinbaseClient instance
        symbol: Trading pair (e.g., "BTC-USD")
        side: "buy" or "sell"
        size_usd: Order size in USD
        metadata: Optional metadata to include in audit log
    
    Returns:
        Order result dictionary
    """
    manager = get_safe_order_manager()
    return manager.place_order(client, symbol, side, size_usd, metadata)
