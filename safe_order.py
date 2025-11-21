"""
safe_order.py - Centralized order submission wrapper with safety checks

This module enforces:
- Mode validation (SANDBOX, DRY_RUN, LIVE)
- Account requirements for LIVE mode
- Rate limiting (MAX_ORDERS_PER_MINUTE)
- Order size limits (MAX_ORDER_USD)
- Manual approval for first N trades (MANUAL_APPROVAL_COUNT)
- Audit logging of all order requests and responses
"""

import os
import time
import json
import logging
import requests
from datetime import datetime, timedelta
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

logger = logging.getLogger("SafeOrder")
logging.basicConfig(level=logging.INFO)

# Rate limiting state
_order_timestamps = []

# Rate limiting configuration
RATE_LIMIT_WINDOW_SECONDS = 60

# Manual approval tracking
_approval_file = None
_approved_count = 0

def _init_approval_file():
    """Initialize the manual approval tracking file"""
    global _approval_file, _approved_count
    
    if MANUAL_APPROVAL_COUNT <= 0:
        return
    
    log_dir = os.path.dirname(LOG_PATH)
    if log_dir and not os.path.exists(log_dir):
        os.makedirs(log_dir, exist_ok=True)
    
    _approval_file = LOG_PATH.replace('.log', '_pending_approvals.json')
    
    # Load existing approvals
    if os.path.exists(_approval_file):
        try:
            with open(_approval_file, 'r') as f:
                data = json.load(f)
                _approved_count = len([o for o in data.get('orders', []) if o.get('approved', False)])
        except Exception as e:
            logger.warning(f"Failed to load approval file: {e}")
            _approved_count = 0
    else:
        # Create empty approval file
        _save_approval_state({'orders': []})

def _save_approval_state(data):
    """Save approval state to file"""
    if _approval_file:
        try:
            with open(_approval_file, 'w') as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            logger.error(f"Failed to save approval file: {e}")

def _load_approval_state():
    """Load approval state from file"""
    if _approval_file and os.path.exists(_approval_file):
        try:
            with open(_approval_file, 'r') as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Failed to load approval file: {e}")
    return {'orders': []}

def _check_rate_limit():
    """Check if we're within rate limit"""
    global _order_timestamps
    
    now = time.time()
    cutoff = now - RATE_LIMIT_WINDOW_SECONDS
    
    # Remove timestamps older than the rate limit window
    _order_timestamps = [ts for ts in _order_timestamps if ts > cutoff]
    
    if len(_order_timestamps) >= MAX_ORDERS_PER_MINUTE:
        raise RuntimeError(
            f"Rate limit exceeded: {len(_order_timestamps)} orders in last {RATE_LIMIT_WINDOW_SECONDS}s "
            f"(max: {MAX_ORDERS_PER_MINUTE})"
        )
    
    _order_timestamps.append(now)

def _validate_mode_and_account():
    """Validate MODE and account requirements"""
    if MODE not in ['SANDBOX', 'DRY_RUN', 'LIVE']:
        raise ValueError(f"Invalid MODE: {MODE}. Must be SANDBOX, DRY_RUN, or LIVE")
    
    if MODE == 'LIVE':
        if not COINBASE_ACCOUNT_ID:
            raise RuntimeError(
                "MODE=LIVE requires COINBASE_ACCOUNT_ID to be set. "
                "This prevents accidental live trading."
            )
        if not CONFIRM_LIVE:
            raise RuntimeError(
                "MODE=LIVE requires CONFIRM_LIVE=true to be set. "
                "This is a safety check to prevent accidental live trading."
            )

def _validate_order_size(size_usd):
    """Validate order size against MAX_ORDER_USD"""
    if size_usd > MAX_ORDER_USD:
        raise ValueError(
            f"Order size ${size_usd} exceeds MAX_ORDER_USD=${MAX_ORDER_USD}"
        )

def _audit_log(order_request, response):
    """Log order request and response to audit log"""
    try:
        log_dir = os.path.dirname(LOG_PATH)
        if log_dir and not os.path.exists(log_dir):
            os.makedirs(log_dir, exist_ok=True)
        
        log_entry = {
            'timestamp': datetime.utcnow().isoformat(),
            'mode': MODE,
            'request': order_request,
            'response': response
        }
        
        with open(LOG_PATH, 'a') as f:
            f.write(json.dumps(log_entry) + '\n')
        
        logger.info(f"Audit logged to {LOG_PATH}")
    except Exception as e:
        logger.error(f"Failed to write audit log: {e}")

def _check_manual_approval():
    """Check if manual approval is required"""
    global _approved_count
    
    if MANUAL_APPROVAL_COUNT <= 0:
        return True
    
    # Reload approval state to check for updates
    state = _load_approval_state()
    _approved_count = len([o for o in state.get('orders', []) if o.get('approved', False)])
    
    if _approved_count < MANUAL_APPROVAL_COUNT:
        return False
    
    return True

def _add_pending_order(order_request):
    """Add order to pending approvals file"""
    state = _load_approval_state()
    
    order_entry = {
        'timestamp': datetime.utcnow().isoformat(),
        'request': order_request,
        'approved': False,
        'order_number': len(state['orders']) + 1
    }
    
    state['orders'].append(order_entry)
    _save_approval_state(state)
    
    logger.warning(
        f"Order #{order_entry['order_number']} pending manual approval. "
        f"Update {_approval_file} to approve. "
        f"({_approved_count}/{MANUAL_APPROVAL_COUNT} approved so far)"
    )

def submit_order(client, symbol, side, size_usd, order_type='market'):
    """
    Submit an order through the safe order wrapper
    
    Args:
        client: CoinbaseClient instance
        symbol: Trading pair (e.g., 'BTC-USD')
        side: 'buy' or 'sell'
        size_usd: Order size in USD
        order_type: Order type (default: 'market')
    
    Returns:
        dict: Order response or status
    
    Raises:
        ValueError: Invalid parameters
        RuntimeError: Safety checks failed
    """
    # Initialize approval tracking if needed
    if _approval_file is None:
        _init_approval_file()
    
    # Validate mode and account requirements
    _validate_mode_and_account()
    
    # Validate order size
    _validate_order_size(size_usd)
    
    # Check rate limit
    _check_rate_limit()
    
    # Build order request
    order_request = {
        'symbol': symbol,
        'side': side,
        'size_usd': size_usd,
        'type': order_type,
        'mode': MODE,
        'timestamp': datetime.utcnow().isoformat()
    }
    
    # Check manual approval requirement
    if not _check_manual_approval():
        _add_pending_order(order_request)
        response = {
            'status': 'pending_approval',
            'message': f'Order requires manual approval ({_approved_count}/{MANUAL_APPROVAL_COUNT} approved)',
            'approval_file': _approval_file
        }
        _audit_log(order_request, response)
        return response
    
    # Handle different modes
    if MODE == 'DRY_RUN':
        response = {
            'status': 'dry_run',
            'message': f'DRY RUN: {side.upper()} ${size_usd} {symbol}',
            'order': order_request
        }
        logger.info(response['message'])
        _audit_log(order_request, response)
        return response
    
    if MODE == 'SANDBOX':
        response = {
            'status': 'sandbox',
            'message': f'SANDBOX: {side.upper()} ${size_usd} {symbol}',
            'order': order_request
        }
        logger.info(response['message'])
        _audit_log(order_request, response)
        return response
    
    # MODE == 'LIVE' - actually place the order
    try:
        logger.info(f"LIVE ORDER: {side.upper()} ${size_usd} {symbol}")
        response = client.place_order(symbol, side, size_usd)
        _audit_log(order_request, response)
        return response
    except requests.exceptions.RequestException as e:
        # Handle API/network errors
        error_response = {
            'status': 'error',
            'error': str(e),
            'order': order_request
        }
        _audit_log(order_request, error_response)
        raise
    except ValueError as e:
        # Handle validation errors
        error_response = {
            'status': 'error',
            'error': str(e),
            'order': order_request
        }
        _audit_log(order_request, error_response)
        raise
    except Exception as e:
        # Handle unexpected errors but still log them
        error_response = {
            'status': 'error',
            'error': str(e),
            'order': order_request
        }
        _audit_log(order_request, error_response)
        raise
