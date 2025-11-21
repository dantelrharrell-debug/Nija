"""
Safe order submission module with rate limiting, order size limits, and audit logging.
All trading orders should go through this module to enforce safety rules.
"""

import time
import json
import logging
from datetime import datetime
from threading import Lock
from pathlib import Path

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

# Thread-safe rate limiter
_rate_limit_lock = Lock()
_order_timestamps = []
_order_count = 0
_pending_approvals_path = None


def _get_pending_approvals_path():
    """Get the path to the pending approvals file."""
    global _pending_approvals_path
    if _pending_approvals_path is None:
        log_path = Path(LOG_PATH)
        _pending_approvals_path = log_path.parent / "pending-approvals.json"
    return _pending_approvals_path


def _init_pending_approvals():
    """Initialize pending approvals file if it doesn't exist."""
    path = _get_pending_approvals_path()
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, 'w') as f:
            json.dump({"pending": [], "approved": []}, f, indent=2)


def _load_pending_approvals():
    """Load pending approvals from file."""
    _init_pending_approvals()
    path = _get_pending_approvals_path()
    with open(path, 'r') as f:
        return json.load(f)


def _save_pending_approvals(data):
    """Save pending approvals to file."""
    path = _get_pending_approvals_path()
    with open(path, 'w') as f:
        json.dump(data, f, indent=2)


def _check_rate_limit():
    """
    Check if we're within the rate limit (MAX_ORDERS_PER_MINUTE).
    Raises RuntimeError if rate limit exceeded.
    """
    with _rate_limit_lock:
        now = time.time()
        # Remove timestamps older than 60 seconds
        global _order_timestamps
        _order_timestamps = [ts for ts in _order_timestamps if now - ts < 60]
        
        if len(_order_timestamps) >= MAX_ORDERS_PER_MINUTE:
            raise RuntimeError(
                f"Rate limit exceeded: {MAX_ORDERS_PER_MINUTE} orders per minute. "
                f"Please wait before placing another order."
            )
        
        # Add current timestamp
        _order_timestamps.append(now)


def _check_order_size(size_usd):
    """
    Validate order size against MAX_ORDER_USD.
    Raises ValueError if order size exceeds limit.
    """
    if size_usd > MAX_ORDER_USD:
        raise ValueError(
            f"Order size ${size_usd:.2f} exceeds maximum allowed ${MAX_ORDER_USD:.2f}"
        )


def _requires_manual_approval():
    """
    Check if this order requires manual approval based on MANUAL_APPROVAL_COUNT.
    Returns True if manual approval is needed.
    """
    global _order_count
    if MANUAL_APPROVAL_COUNT <= 0:
        return False
    
    _order_count += 1
    return _order_count <= MANUAL_APPROVAL_COUNT


def _audit_log(event_type, data):
    """
    Log order events to audit log file.
    
    Args:
        event_type: Type of event (e.g., "order_request", "order_response", "order_rejected")
        data: Dictionary of event data
    """
    log_path = Path(LOG_PATH)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    
    log_entry = {
        "timestamp": datetime.utcnow().isoformat(),
        "event_type": event_type,
        "mode": MODE,
        "data": data
    }
    
    with open(log_path, 'a') as f:
        f.write(json.dumps(log_entry) + '\n')
    
    logger.info(f"Audit log: {event_type} - {data}")


def validate_mode_and_account():
    """
    Validate that MODE and account settings are correct for trading.
    Raises RuntimeError if validation fails.
    """
    if MODE == "LIVE":
        if not COINBASE_ACCOUNT_ID:
            raise RuntimeError("LIVE mode requires COINBASE_ACCOUNT_ID to be set")
        if not CONFIRM_LIVE:
            raise RuntimeError("LIVE mode requires CONFIRM_LIVE=true to be set")
    elif MODE not in ["SANDBOX", "DRY_RUN", "LIVE"]:
        raise RuntimeError(f"Invalid MODE: {MODE}. Must be SANDBOX, DRY_RUN, or LIVE")


def submit_order(client, symbol, side, size_usd, order_type="market"):
    """
    Centralized order submission with all safety checks.
    
    Args:
        client: CoinbaseClient instance
        symbol: Trading pair symbol (e.g., "BTC-USD")
        side: "buy" or "sell"
        size_usd: Order size in USD
        order_type: Order type (default: "market")
    
    Returns:
        dict: Order response from Coinbase or status dict
    
    Raises:
        RuntimeError: If safety checks fail
        ValueError: If order parameters are invalid
    """
    # Validate mode and account
    validate_mode_and_account()
    
    # Check rate limit
    _check_rate_limit()
    
    # Validate order size
    _check_order_size(size_usd)
    
    # Prepare order data
    order_data = {
        "symbol": symbol,
        "side": side,
        "size_usd": size_usd,
        "order_type": order_type,
        "timestamp": datetime.utcnow().isoformat()
    }
    
    # Log order request
    _audit_log("order_request", order_data)
    
    # Check if manual approval is required
    if _requires_manual_approval():
        logger.warning(f"Order requires manual approval (count: {_order_count}/{MANUAL_APPROVAL_COUNT})")
        
        # Add to pending approvals
        approvals = _load_pending_approvals()
        order_data["order_id"] = f"pending_{int(time.time() * 1000)}"
        order_data["status"] = "pending_approval"
        approvals["pending"].append(order_data)
        _save_pending_approvals(approvals)
        
        _audit_log("order_pending", order_data)
        
        return {
            "status": "pending_approval",
            "message": f"Order marked for manual approval. Approve in {_get_pending_approvals_path()}",
            "order_data": order_data
        }
    
    # Execute order based on mode
    if MODE == "DRY_RUN":
        logger.info(f"DRY_RUN: {side.upper()} ${size_usd:.2f} {symbol}")
        response = {
            "status": "dry_run",
            "side": side,
            "symbol": symbol,
            "size_usd": size_usd
        }
        _audit_log("order_dry_run", response)
        return response
    
    elif MODE == "SANDBOX":
        logger.info(f"SANDBOX: {side.upper()} ${size_usd:.2f} {symbol}")
        # In sandbox mode, we would use sandbox API endpoints
        # For now, treat it like dry run
        response = {
            "status": "sandbox",
            "side": side,
            "symbol": symbol,
            "size_usd": size_usd
        }
        _audit_log("order_sandbox", response)
        return response
    
    elif MODE == "LIVE":
        logger.warning(f"⚠️  LIVE ORDER: {side.upper()} ${size_usd:.2f} {symbol}")
        
        try:
            # Call the actual client method to place order
            response = client.place_order(symbol, side, size_usd)
            _audit_log("order_response", response)
            return response
        except Exception as e:
            error_data = {
                "error": str(e),
                "order_data": order_data
            }
            _audit_log("order_error", error_data)
            raise
    
    else:
        raise RuntimeError(f"Unknown MODE: {MODE}")


def get_pending_approvals():
    """
    Get list of orders pending manual approval.
    
    Returns:
        dict: Pending and approved orders
    """
    return _load_pending_approvals()


def approve_order(order_id):
    """
    Approve a pending order by moving it from pending to approved list.
    
    Args:
        order_id: ID of the order to approve
    
    Returns:
        bool: True if approved, False if not found
    """
    approvals = _load_pending_approvals()
    
    for i, order in enumerate(approvals["pending"]):
        if order.get("order_id") == order_id:
            # Move to approved
            order["approved_at"] = datetime.utcnow().isoformat()
            order["status"] = "approved"
            approvals["approved"].append(order)
            approvals["pending"].pop(i)
            _save_pending_approvals(approvals)
            
            _audit_log("order_approved", order)
            logger.info(f"Order {order_id} approved")
            return True
    
    logger.warning(f"Order {order_id} not found in pending approvals")
    return False
