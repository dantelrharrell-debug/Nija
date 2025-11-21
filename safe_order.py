"""
safe_order.py - Centralized order submission wrapper with safety mechanisms.

Responsibilities:
- Validate mode and account requirements
- Rate limit by MAX_ORDERS_PER_MINUTE
- Enforce MAX_ORDER_USD
- Manual approval for first N trades
- Audit logging of all order requests and responses
"""

import os
import time
import json
import logging
from datetime import datetime, timezone
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

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("SafeOrder")

# Rate limiting tracking
_order_timestamps = []
_order_count = 0
_pending_approvals_file = None


def _get_pending_approvals_file():
    """Get the path to the pending approvals file."""
    global _pending_approvals_file
    if _pending_approvals_file is None:
        log_dir = os.path.dirname(LOG_PATH) or "."
        _pending_approvals_file = os.path.join(log_dir, "pending-approvals.json")
    return _pending_approvals_file


def _load_pending_approvals():
    """Load pending approvals from file."""
    approvals_file = _get_pending_approvals_file()
    if os.path.exists(approvals_file):
        try:
            with open(approvals_file, 'r') as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Failed to load pending approvals: {e}")
    return {"approved_count": 0, "pending_orders": []}


def _save_pending_approvals(data):
    """Save pending approvals to file."""
    approvals_file = _get_pending_approvals_file()
    try:
        with open(approvals_file, 'w') as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        logger.error(f"Failed to save pending approvals: {e}")


def _audit_log(event_type: str, data: Dict[str, Any]):
    """Log an event to the audit log file."""
    log_entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "event_type": event_type,
        "mode": MODE,
        "data": data
    }
    
    try:
        # Ensure log directory exists
        log_dir = os.path.dirname(LOG_PATH)
        if log_dir:
            os.makedirs(log_dir, exist_ok=True)
        
        with open(LOG_PATH, 'a') as f:
            f.write(json.dumps(log_entry) + '\n')
    except Exception as e:
        logger.error(f"Failed to write audit log: {e}")


def _check_rate_limit():
    """Check if we're within rate limits."""
    global _order_timestamps
    
    now = time.time()
    # Remove timestamps older than 1 minute
    _order_timestamps = [ts for ts in _order_timestamps if now - ts < 60]
    
    if len(_order_timestamps) >= MAX_ORDERS_PER_MINUTE:
        raise RuntimeError(
            f"Rate limit exceeded: {len(_order_timestamps)} orders in the last minute. "
            f"Maximum allowed: {MAX_ORDERS_PER_MINUTE}"
        )
    
    # Add current timestamp
    _order_timestamps.append(now)


def _check_order_size(size_usd: float):
    """Validate order size is within limits."""
    if size_usd > MAX_ORDER_USD:
        raise ValueError(
            f"Order size ${size_usd:.2f} exceeds maximum allowed ${MAX_ORDER_USD:.2f}"
        )


def _check_manual_approval():
    """Check if manual approval is required."""
    global _order_count
    
    if MANUAL_APPROVAL_COUNT > 0:
        approvals = _load_pending_approvals()
        approved_count = approvals.get("approved_count", 0)
        
        if approved_count < MANUAL_APPROVAL_COUNT:
            return True, approvals
    
    return False, None


def submit_order(
    client,
    symbol: str,
    side: str,
    size_usd: float,
    order_type: str = "market",
    metadata: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    Submit an order through the safe order wrapper.
    
    Args:
        client: The Coinbase client instance
        symbol: Trading pair (e.g., "BTC-USD")
        side: "buy" or "sell"
        size_usd: Order size in USD
        order_type: Order type (default: "market")
        metadata: Optional metadata to include in audit log
    
    Returns:
        Dict containing order result
    """
    # Build order request
    order_request = {
        "symbol": symbol,
        "side": side,
        "size_usd": size_usd,
        "order_type": order_type,
        "metadata": metadata or {}
    }
    
    try:
        # Validate mode requirements
        if MODE == "LIVE":
            if not COINBASE_ACCOUNT_ID:
                raise RuntimeError("LIVE mode requires COINBASE_ACCOUNT_ID to be set")
            if not CONFIRM_LIVE:
                raise RuntimeError("LIVE mode requires CONFIRM_LIVE=true to be set")
        
        # Check order size
        _check_order_size(size_usd)
        
        # Check rate limit
        _check_rate_limit()
        
        # Check manual approval requirement
        needs_approval, approvals_data = _check_manual_approval()
        
        if needs_approval:
            # Add to pending approvals
            pending_order = {
                "id": f"pending_{int(time.time())}_{len(approvals_data['pending_orders'])}",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "request": order_request,
                "status": "pending_approval"
            }
            approvals_data["pending_orders"].append(pending_order)
            _save_pending_approvals(approvals_data)
            
            _audit_log("order_pending_approval", order_request)
            
            logger.warning(
                f"⏸️  Order requires manual approval. "
                f"Approved: {approvals_data['approved_count']}/{MANUAL_APPROVAL_COUNT}. "
                f"Update {_get_pending_approvals_file()} to approve."
            )
            
            return {
                "status": "pending_approval",
                "order_id": pending_order["id"],
                "message": "Order pending manual approval"
            }
        
        # Execute order based on mode
        if MODE == "LIVE":
            logger.warning(f"🚨 LIVE ORDER: {side.upper()} ${size_usd:.2f} {symbol}")
            # Call the actual client method
            response = client.place_order(symbol, side, size_usd)
            _audit_log("order_placed_live", {
                "request": order_request,
                "response": response
            })
            return response
        
        elif MODE == "SANDBOX":
            logger.info(f"🏖️  SANDBOX ORDER: {side.upper()} ${size_usd:.2f} {symbol}")
            _audit_log("order_placed_sandbox", order_request)
            return {
                "status": "sandbox",
                "message": "Order executed in sandbox mode",
                "order": order_request
            }
        
        else:  # DRY_RUN
            logger.info(f"🔍 DRY_RUN ORDER: {side.upper()} ${size_usd:.2f} {symbol}")
            _audit_log("order_dry_run", order_request)
            return {
                "status": "dry_run",
                "message": "Order simulated in dry run mode",
                "order": order_request
            }
    
    except Exception as e:
        _audit_log("order_failed", {
            "request": order_request,
            "error": str(e)
        })
        logger.error(f"Order submission failed: {e}")
        raise


def approve_pending_orders(count: int = 1):
    """
    Approve pending orders manually.
    
    Args:
        count: Number of orders to approve
    """
    approvals = _load_pending_approvals()
    approvals["approved_count"] = approvals.get("approved_count", 0) + count
    _save_pending_approvals(approvals)
    logger.info(f"✅ Approved {count} orders. Total approved: {approvals['approved_count']}")


def get_pending_orders():
    """Get list of pending orders."""
    approvals = _load_pending_approvals()
    return approvals.get("pending_orders", [])


def clear_pending_orders():
    """Clear all pending orders."""
    _save_pending_approvals({"approved_count": 0, "pending_orders": []})
    logger.info("Cleared all pending orders")
