"""
safe_order.py - Centralized order submission with safety checks and audit logging.

Responsibilities:
- Validate mode and account requirements
- Rate limit by MAX_ORDERS_PER_MINUTE
- Enforce MAX_ORDER_USD
- Manual approval workflow for first N trades
- Audit logging of all order requests and responses
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
    LOG_PATH,
)

logger = logging.getLogger(__name__)

# Global rate limiting state
_order_timestamps = []

# Manual approval state
_pending_approvals_path = None
_approved_count = 0


def _get_pending_approvals_path() -> str:
    """
    Get the path to the pending approvals file.
    
    Note: Uses /tmp as fallback which may be cleared on system reboot.
    For production use, ensure LOG_PATH is set to a persistent location.
    """
    global _pending_approvals_path
    if _pending_approvals_path is None:
        log_dir = os.path.dirname(LOG_PATH)
        if log_dir:
            os.makedirs(log_dir, exist_ok=True)
        _pending_approvals_path = os.path.join(
            log_dir or "/tmp", "pending_approvals.json"
        )
    return _pending_approvals_path


def _load_approved_count() -> int:
    """Load the count of manually approved orders."""
    approvals_path = _get_pending_approvals_path()
    if not os.path.exists(approvals_path):
        return 0
    try:
        with open(approvals_path, 'r') as f:
            data = json.load(f)
            return data.get("approved_count", 0)
    except Exception as e:
        logger.warning(f"Failed to load approved count: {e}")
        return 0


def _save_pending_approval(order_request: Dict[str, Any]) -> None:
    """Save an order request to the pending approvals file."""
    approvals_path = _get_pending_approvals_path()
    
    # Load existing data
    pending_orders = []
    approved_count = 0
    if os.path.exists(approvals_path):
        try:
            with open(approvals_path, 'r') as f:
                data = json.load(f)
                pending_orders = data.get("pending_orders", [])
                approved_count = data.get("approved_count", 0)
        except Exception as e:
            logger.warning(f"Failed to load pending approvals: {e}")
    
    # Add new pending order
    pending_orders.append({
        "timestamp": datetime.utcnow().isoformat(),
        "order": order_request,
    })
    
    # Save updated data
    try:
        with open(approvals_path, 'w') as f:
            json.dump({
                "approved_count": approved_count,
                "pending_orders": pending_orders,
            }, f, indent=2)
        logger.info(f"Order saved to pending approvals: {approvals_path}")
    except Exception as e:
        logger.error(f"Failed to save pending approval: {e}")


def _increment_approved_count() -> None:
    """Increment the approved count and remove from pending."""
    approvals_path = _get_pending_approvals_path()
    
    approved_count = 0
    pending_orders = []
    
    if os.path.exists(approvals_path):
        try:
            with open(approvals_path, 'r') as f:
                data = json.load(f)
                approved_count = data.get("approved_count", 0)
                pending_orders = data.get("pending_orders", [])
        except Exception as e:
            logger.warning(f"Failed to load approvals: {e}")
    
    # Increment and remove first pending order if any
    approved_count += 1
    if pending_orders:
        pending_orders = pending_orders[1:]
    
    try:
        with open(approvals_path, 'w') as f:
            json.dump({
                "approved_count": approved_count,
                "pending_orders": pending_orders,
            }, f, indent=2)
    except Exception as e:
        logger.error(f"Failed to save approved count: {e}")


def _audit_log(event_type: str, data: Dict[str, Any]) -> None:
    """Log order events to the audit log file."""
    log_dir = os.path.dirname(LOG_PATH)
    if log_dir:
        os.makedirs(log_dir, exist_ok=True)
    
    log_entry = {
        "timestamp": datetime.utcnow().isoformat(),
        "event_type": event_type,
        "data": data,
    }
    
    try:
        with open(LOG_PATH, 'a') as f:
            f.write(json.dumps(log_entry) + '\n')
    except Exception as e:
        logger.error(f"Failed to write audit log: {e}")


def _check_rate_limit() -> bool:
    """
    Check if we're within the rate limit.
    Returns True if we can proceed, False if rate limit exceeded.
    """
    global _order_timestamps
    
    now = time.time()
    # Remove timestamps older than 1 minute
    _order_timestamps = [ts for ts in _order_timestamps if now - ts < 60]
    
    if len(_order_timestamps) >= MAX_ORDERS_PER_MINUTE:
        return False
    
    return True


def _record_order_attempt() -> None:
    """Record an order attempt for rate limiting."""
    global _order_timestamps
    _order_timestamps.append(time.time())


def validate_order_request(
    symbol: str,
    side: str,
    size_usd: float,
) -> Optional[str]:
    """
    Validate an order request against safety rules.
    Returns None if valid, or an error message string if invalid.
    """
    # Check MODE requirements
    if MODE == "LIVE":
        if not COINBASE_ACCOUNT_ID:
            return "LIVE mode requires COINBASE_ACCOUNT_ID to be set"
        if not CONFIRM_LIVE:
            return "LIVE mode requires CONFIRM_LIVE=true to be set"
    
    # Check order size limit
    if size_usd > MAX_ORDER_USD:
        return f"Order size ${size_usd} exceeds MAX_ORDER_USD limit of ${MAX_ORDER_USD}"
    
    # Check rate limit
    if not _check_rate_limit():
        return f"Rate limit exceeded: max {MAX_ORDERS_PER_MINUTE} orders per minute"
    
    return None


def submit_order(
    client,
    symbol: str,
    side: str,
    size_usd: float,
) -> Dict[str, Any]:
    """
    Submit an order through the safe order pipeline.
    
    Args:
        client: CoinbaseClient instance
        symbol: Trading pair symbol (e.g., "BTC-USD")
        side: "buy" or "sell"
        size_usd: Order size in USD
    
    Returns:
        Dictionary with order response or error details
    """
    order_request = {
        "symbol": symbol,
        "side": side,
        "size_usd": size_usd,
        "mode": MODE,
    }
    
    # Audit log the request
    _audit_log("order_request", order_request)
    
    # Validate the request
    validation_error = validate_order_request(symbol, side, size_usd)
    if validation_error:
        error_response = {
            "status": "rejected",
            "error": validation_error,
            "order": order_request,
        }
        _audit_log("order_rejected", error_response)
        logger.error(f"Order rejected: {validation_error}")
        return error_response
    
    # Check manual approval requirement
    global _approved_count
    _approved_count = _load_approved_count()
    
    needs_approval = MANUAL_APPROVAL_COUNT > 0 and _approved_count < MANUAL_APPROVAL_COUNT
    
    if needs_approval:
        # Save to pending approvals
        _save_pending_approval(order_request)
        pending_response = {
            "status": "pending_approval",
            "message": f"Order requires manual approval (count: {_approved_count}/{MANUAL_APPROVAL_COUNT})",
            "order": order_request,
            "approvals_file": _get_pending_approvals_path(),
        }
        _audit_log("order_pending", pending_response)
        logger.info(f"Order pending manual approval: {pending_response}")
        return pending_response
    
    # Record the order attempt for rate limiting
    _record_order_attempt()
    
    # Submit the order based on MODE
    try:
        if MODE == "SANDBOX" or MODE == "DRY_RUN":
            # Simulate order submission
            response = {
                "status": "simulated",
                "mode": MODE,
                "order": order_request,
                "message": f"{MODE} mode: order not actually submitted",
            }
            logger.info(f"{MODE} mode: simulated {side.upper()} ${size_usd} {symbol}")
        else:  # LIVE mode
            # Actually submit to Coinbase
            response = client.place_order(symbol, side, size_usd)
            response["mode"] = MODE
            logger.info(f"LIVE order submitted: {response}")
        
        _audit_log("order_submitted", {"request": order_request, "response": response})
        
        # Increment approved count if we're tracking approvals
        # This happens AFTER successful submission
        if MANUAL_APPROVAL_COUNT > 0:
            _increment_approved_count()
        
        return response
        
    except Exception as e:
        error_response = {
            "status": "failed",
            "error": str(e),
            "order": order_request,
        }
        _audit_log("order_failed", error_response)
        logger.exception(f"Order submission failed: {e}")
        return error_response


def get_order_stats() -> Dict[str, Any]:
    """Get statistics about order submissions."""
    global _order_timestamps
    now = time.time()
    _order_timestamps = [ts for ts in _order_timestamps if now - ts < 60]
    
    return {
        "mode": MODE,
        "orders_last_minute": len(_order_timestamps),
        "max_orders_per_minute": MAX_ORDERS_PER_MINUTE,
        "max_order_usd": MAX_ORDER_USD,
        "manual_approval_count": MANUAL_APPROVAL_COUNT,
        "approved_count": _load_approved_count(),
        "log_path": LOG_PATH,
        "pending_approvals_path": _get_pending_approvals_path(),
    }
