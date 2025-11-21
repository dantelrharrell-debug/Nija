"""
Safe Order Module - Centralized order submission with safety checks
"""
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

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("SafeOrder")

# Track order submission times for rate limiting
order_timestamps = []

# Track total orders submitted for manual approval
total_orders_submitted = 0

# Pending approvals file path - use pathlib for proper path construction
PENDING_APPROVALS_FILE = str(Path(LOG_PATH).parent / (Path(LOG_PATH).stem + "_pending_approvals.json"))


def validate_mode_and_account():
    """Validate MODE and COINBASE_ACCOUNT_ID requirements."""
    if MODE == "LIVE":
        if not COINBASE_ACCOUNT_ID:
            raise RuntimeError(
                "LIVE mode requires COINBASE_ACCOUNT_ID to be set."
            )
        if not CONFIRM_LIVE:
            raise RuntimeError(
                "LIVE mode requires CONFIRM_LIVE=true to be set."
            )
    elif MODE not in ["SANDBOX", "DRY_RUN", "LIVE"]:
        raise RuntimeError(
            f"Invalid MODE: {MODE}. Must be SANDBOX, DRY_RUN, or LIVE."
        )


def check_rate_limit():
    """
    Check if we're within the rate limit.
    Raises RuntimeError if rate limit exceeded.
    """
    global order_timestamps
    
    now = time.time()
    # Remove timestamps older than 1 minute
    order_timestamps = [ts for ts in order_timestamps if now - ts < 60]
    
    if len(order_timestamps) >= MAX_ORDERS_PER_MINUTE:
        raise RuntimeError(
            f"Rate limit exceeded: {len(order_timestamps)} orders in the last minute. "
            f"Max allowed: {MAX_ORDERS_PER_MINUTE}"
        )
    
    # Add current timestamp
    order_timestamps.append(now)


def enforce_max_order_usd(order_amount_usd: float):
    """
    Enforce MAX_ORDER_USD limit.
    Raises RuntimeError if order exceeds limit.
    """
    if order_amount_usd > MAX_ORDER_USD:
        raise RuntimeError(
            f"Order amount ${order_amount_usd:.2f} exceeds MAX_ORDER_USD limit of ${MAX_ORDER_USD:.2f}"
        )


def requires_manual_approval() -> bool:
    """
    Check if current order requires manual approval.
    Returns True if MANUAL_APPROVAL_COUNT > 0 and total orders < MANUAL_APPROVAL_COUNT
    """
    global total_orders_submitted
    return MANUAL_APPROVAL_COUNT > 0 and total_orders_submitted < MANUAL_APPROVAL_COUNT


def save_pending_approval(order_data: Dict[str, Any]):
    """
    Save order to pending approvals file.
    """
    pending_file = Path(PENDING_APPROVALS_FILE)
    
    # Load existing pending orders
    pending_orders = []
    if pending_file.exists():
        try:
            with open(pending_file, 'r') as f:
                pending_orders = json.load(f)
        except Exception as e:
            logger.error(f"Failed to load pending approvals: {e}")
    
    # Add new order
    order_data["timestamp"] = datetime.utcnow().isoformat()
    order_data["status"] = "pending_approval"
    pending_orders.append(order_data)
    
    # Save back to file
    try:
        pending_file.parent.mkdir(parents=True, exist_ok=True)
        with open(pending_file, 'w') as f:
            json.dump(pending_orders, f, indent=2)
        logger.info(f"Order saved to pending approvals: {PENDING_APPROVALS_FILE}")
    except Exception as e:
        logger.error(f"Failed to save pending approval: {e}")


def audit_log(order_request: Dict[str, Any], coinbase_response: Optional[Dict[str, Any]] = None):
    """
    Log every order request and Coinbase response to the audit log file.
    """
    log_file = Path(LOG_PATH)
    
    log_entry = {
        "timestamp": datetime.utcnow().isoformat(),
        "mode": MODE,
        "order_request": order_request,
        "coinbase_response": coinbase_response
    }
    
    try:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        with open(log_file, 'a') as f:
            f.write(json.dumps(log_entry) + '\n')
    except Exception as e:
        logger.error(f"Failed to write to audit log: {e}")


def submit_order(
    client,
    symbol: str,
    side: str,
    size_usd: float,
    order_type: str = "market"
) -> Dict[str, Any]:
    """
    Centralized order submission with all safety checks.
    
    Args:
        client: CoinbaseClient instance
        symbol: Trading pair (e.g., "BTC-USD")
        side: "buy" or "sell"
        size_usd: Order amount in USD
        order_type: Order type (default: "market")
    
    Returns:
        Order response dict
    """
    global total_orders_submitted
    
    # Validate mode and account
    validate_mode_and_account()
    
    # Check rate limit
    check_rate_limit()
    
    # Enforce MAX_ORDER_USD
    enforce_max_order_usd(size_usd)
    
    # Build order request
    order_request = {
        "symbol": symbol,
        "side": side,
        "size_usd": size_usd,
        "order_type": order_type,
        "mode": MODE
    }
    
    # Check if manual approval required
    if requires_manual_approval():
        logger.warning(
            f"Order #{total_orders_submitted + 1} requires manual approval "
            f"(MANUAL_APPROVAL_COUNT={MANUAL_APPROVAL_COUNT})"
        )
        save_pending_approval(order_request)
        audit_log(order_request, {"status": "pending_approval"})
        total_orders_submitted += 1
        return {
            "status": "pending_approval",
            "message": f"Order saved for manual approval. Check {PENDING_APPROVALS_FILE}"
        }
    
    # Execute order based on MODE
    coinbase_response = None
    
    if MODE == "DRY_RUN":
        logger.info(f"DRY_RUN: {side.upper()} ${size_usd:.2f} {symbol}")
        coinbase_response = {
            "status": "dry_run",
            "message": "Order not executed (DRY_RUN mode)"
        }
    elif MODE == "SANDBOX":
        logger.info(f"SANDBOX: {side.upper()} ${size_usd:.2f} {symbol}")
        # Note: SANDBOX mode currently logs orders without executing them
        # For actual sandbox testing, implement sandbox-specific API calls
        # or use a test account with minimal funds
        coinbase_response = {
            "status": "sandbox",
            "message": "Order logged in SANDBOX mode (not executed)"
        }
    elif MODE == "LIVE":
        logger.info(f"LIVE: Placing {side.upper()} order for ${size_usd:.2f} {symbol}")
        try:
            coinbase_response = client.place_order(symbol, side, size_usd)
        except Exception as e:
            logger.error(f"Failed to place live order: {e}")
            coinbase_response = {
                "status": "error",
                "error": str(e)
            }
    
    # Audit log
    audit_log(order_request, coinbase_response)
    
    total_orders_submitted += 1
    
    return coinbase_response


def get_pending_approvals() -> list:
    """
    Retrieve all pending approval orders.
    """
    pending_file = Path(PENDING_APPROVALS_FILE)
    
    if not pending_file.exists():
        return []
    
    try:
        with open(pending_file, 'r') as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Failed to load pending approvals: {e}")
        return []


def approve_order(order_index: int):
    """
    Approve a pending order by index.
    This would typically be called by a manual approval process.
    """
    pending_orders = get_pending_approvals()
    
    if order_index < 0 or order_index >= len(pending_orders):
        raise ValueError(f"Invalid order index: {order_index}")
    
    order = pending_orders[order_index]
    order["status"] = "approved"
    order["approved_at"] = datetime.utcnow().isoformat()
    
    # Save updated pending orders
    pending_file = Path(PENDING_APPROVALS_FILE)
    try:
        with open(pending_file, 'w') as f:
            json.dump(pending_orders, f, indent=2)
        logger.info(f"Order {order_index} approved")
        return order
    except Exception as e:
        logger.error(f"Failed to approve order: {e}")
        raise
