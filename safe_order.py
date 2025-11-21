"""
Safe Order Module - Centralized order submission wrapper with safety checks.

This module enforces:
- MODE validation (SANDBOX/DRY_RUN/LIVE)
- Account ID requirements for LIVE mode
- Rate limiting (MAX_ORDERS_PER_MINUTE)
- Order size limits (MAX_ORDER_USD)
- Manual approval system for first N trades
- Audit logging of all order requests and responses
"""

import os
import json
import time
import logging
from datetime import datetime, timedelta
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

# Rate limiting state
_order_timestamps = []

# Manual approval tracking
_pending_approvals_path = None
_order_count = 0


def _get_pending_approvals_path():
    """Get path to pending approvals file."""
    global _pending_approvals_path
    if _pending_approvals_path is None:
        log_path = Path(LOG_PATH)
        _pending_approvals_path = log_path.parent / "pending_approvals.json"
    return _pending_approvals_path


def _load_pending_approvals():
    """Load pending approvals from file."""
    approvals_path = _get_pending_approvals_path()
    if approvals_path.exists():
        try:
            with open(approvals_path, 'r') as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Failed to load pending approvals: {e}")
            return {"pending": [], "approved": [], "rejected": []}
    return {"pending": [], "approved": [], "rejected": []}


def _save_pending_approvals(approvals_data):
    """Save pending approvals to file."""
    approvals_path = _get_pending_approvals_path()
    try:
        approvals_path.parent.mkdir(parents=True, exist_ok=True)
        with open(approvals_path, 'w') as f:
            json.dump(approvals_data, f, indent=2)
    except Exception as e:
        logger.error(f"Failed to save pending approvals: {e}")


def _audit_log(message: str, data: Optional[Dict[str, Any]] = None):
    """
    Write audit log entry to LOG_PATH.
    
    Args:
        message: Log message
        data: Optional data to log as JSON
    """
    try:
        log_path = Path(LOG_PATH)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        
        timestamp = datetime.utcnow().isoformat()
        log_entry = {
            "timestamp": timestamp,
            "message": message,
            "data": data or {}
        }
        
        with open(log_path, 'a') as f:
            f.write(json.dumps(log_entry) + "\n")
            
    except Exception as e:
        logger.error(f"Failed to write audit log: {e}")


def _check_rate_limit():
    """
    Check if order rate limit is exceeded.
    
    Returns:
        True if within rate limit, False otherwise
    """
    global _order_timestamps
    
    now = datetime.utcnow()
    one_minute_ago = now - timedelta(minutes=1)
    
    # Remove timestamps older than 1 minute
    _order_timestamps = [ts for ts in _order_timestamps if ts > one_minute_ago]
    
    if len(_order_timestamps) >= MAX_ORDERS_PER_MINUTE:
        logger.warning(
            f"Rate limit exceeded: {len(_order_timestamps)} orders in last minute "
            f"(limit: {MAX_ORDERS_PER_MINUTE})"
        )
        return False
    
    return True


def _check_manual_approval_required():
    """
    Check if manual approval is required for this order.
    
    Returns:
        True if manual approval is required, False otherwise
    """
    global _order_count
    
    if MANUAL_APPROVAL_COUNT <= 0:
        return False
    
    _order_count += 1
    return _order_count <= MANUAL_APPROVAL_COUNT


def validate_mode_and_account():
    """
    Validate MODE and account requirements.
    
    Raises:
        RuntimeError if validation fails
    """
    if MODE == "LIVE":
        if not COINBASE_ACCOUNT_ID:
            raise RuntimeError(
                "LIVE mode requires COINBASE_ACCOUNT_ID to be set"
            )
        if not CONFIRM_LIVE:
            raise RuntimeError(
                "LIVE mode requires CONFIRM_LIVE=true to be set"
            )
    elif MODE not in ("SANDBOX", "DRY_RUN"):
        raise RuntimeError(
            f"Invalid MODE: {MODE}. Must be one of: SANDBOX, DRY_RUN, LIVE"
        )


def submit_order(
    client,
    symbol: str,
    side: str,
    size_usd: float,
    order_type: str = "market",
    **kwargs
) -> Dict[str, Any]:
    """
    Submit an order through the safe order wrapper.
    
    This function enforces all safety checks:
    - MODE validation
    - Rate limiting
    - Order size limits
    - Manual approval (if configured)
    - Audit logging
    
    Args:
        client: Coinbase client instance
        symbol: Trading pair symbol (e.g., "BTC-USD")
        side: Order side ("buy" or "sell")
        size_usd: Order size in USD
        order_type: Order type (default: "market")
        **kwargs: Additional order parameters
        
    Returns:
        Order response dict with status and details
        
    Raises:
        RuntimeError if safety checks fail
    """
    # Validate mode and account
    validate_mode_and_account()
    
    # Check order size limit
    if size_usd > MAX_ORDER_USD:
        error_msg = (
            f"Order size ${size_usd:.2f} exceeds MAX_ORDER_USD limit of ${MAX_ORDER_USD:.2f}"
        )
        logger.error(error_msg)
        _audit_log("ORDER_REJECTED", {
            "reason": "size_limit_exceeded",
            "symbol": symbol,
            "side": side,
            "size_usd": size_usd,
            "limit": MAX_ORDER_USD
        })
        raise RuntimeError(error_msg)
    
    # Check rate limit
    if not _check_rate_limit():
        error_msg = f"Rate limit exceeded: {MAX_ORDERS_PER_MINUTE} orders per minute"
        logger.error(error_msg)
        _audit_log("ORDER_REJECTED", {
            "reason": "rate_limit_exceeded",
            "symbol": symbol,
            "side": side,
            "size_usd": size_usd
        })
        raise RuntimeError(error_msg)
    
    # Build order request
    order_request = {
        "symbol": symbol,
        "side": side,
        "size_usd": size_usd,
        "type": order_type,
        "timestamp": datetime.utcnow().isoformat(),
        **kwargs
    }
    
    # Check if manual approval required
    if _check_manual_approval_required():
        logger.info(
            f"Manual approval required for order {_order_count}/{MANUAL_APPROVAL_COUNT}"
        )
        
        # Add to pending approvals
        approvals = _load_pending_approvals()
        order_request["order_id"] = f"pending_{int(time.time())}_{_order_count}"
        order_request["status"] = "pending_approval"
        approvals["pending"].append(order_request)
        _save_pending_approvals(approvals)
        
        _audit_log("ORDER_PENDING_APPROVAL", order_request)
        
        return {
            "status": "pending_approval",
            "message": f"Order requires manual approval ({_order_count}/{MANUAL_APPROVAL_COUNT})",
            "order": order_request
        }
    
    # Log order request
    _audit_log("ORDER_REQUEST", order_request)
    
    # Execute order based on MODE
    if MODE == "DRY_RUN":
        logger.info(
            f"DRY_RUN: {side.upper()} ${size_usd:.2f} {symbol}"
        )
        response = {
            "status": "dry_run",
            "message": "Order not executed (DRY_RUN mode)",
            "order": order_request
        }
        _audit_log("ORDER_DRY_RUN", response)
        
    elif MODE == "SANDBOX":
        logger.info(
            f"SANDBOX: {side.upper()} ${size_usd:.2f} {symbol}"
        )
        response = {
            "status": "sandbox",
            "message": "Order executed in sandbox",
            "order": order_request
        }
        _audit_log("ORDER_SANDBOX", response)
        
    elif MODE == "LIVE":
        logger.warning(
            f"LIVE ORDER: {side.upper()} ${size_usd:.2f} {symbol}"
        )
        try:
            # Call the client's place_order method
            response = client.place_order(symbol, side, size_usd)
            _audit_log("ORDER_LIVE_RESPONSE", response)
        except Exception as e:
            logger.error(f"Failed to place live order: {e}")
            error_response = {
                "status": "failed",
                "error": str(e),
                "order": order_request
            }
            _audit_log("ORDER_LIVE_FAILED", error_response)
            raise
    else:
        raise RuntimeError(f"Invalid MODE: {MODE}")
    
    # Record timestamp for rate limiting
    _order_timestamps.append(datetime.utcnow())
    
    return response


def approve_pending_order(order_id: str) -> bool:
    """
    Approve a pending order.
    
    Args:
        order_id: ID of the pending order to approve
        
    Returns:
        True if approved, False if not found
    """
    approvals = _load_pending_approvals()
    
    for i, order in enumerate(approvals["pending"]):
        if order.get("order_id") == order_id:
            approved_order = approvals["pending"].pop(i)
            approved_order["approved_at"] = datetime.utcnow().isoformat()
            approvals["approved"].append(approved_order)
            _save_pending_approvals(approvals)
            _audit_log("ORDER_APPROVED", approved_order)
            logger.info(f"Order {order_id} approved")
            return True
    
    logger.warning(f"Order {order_id} not found in pending approvals")
    return False


def reject_pending_order(order_id: str, reason: str = "") -> bool:
    """
    Reject a pending order.
    
    Args:
        order_id: ID of the pending order to reject
        reason: Optional reason for rejection
        
    Returns:
        True if rejected, False if not found
    """
    approvals = _load_pending_approvals()
    
    for i, order in enumerate(approvals["pending"]):
        if order.get("order_id") == order_id:
            rejected_order = approvals["pending"].pop(i)
            rejected_order["rejected_at"] = datetime.utcnow().isoformat()
            rejected_order["rejection_reason"] = reason
            approvals["rejected"].append(rejected_order)
            _save_pending_approvals(approvals)
            _audit_log("ORDER_REJECTED", rejected_order)
            logger.info(f"Order {order_id} rejected: {reason}")
            return True
    
    logger.warning(f"Order {order_id} not found in pending approvals")
    return False


def get_pending_orders():
    """
    Get list of pending orders awaiting approval.
    
    Returns:
        List of pending orders
    """
    approvals = _load_pending_approvals()
    return approvals.get("pending", [])
