"""
tradingview_webhook.py - TradingView webhook endpoint with HMAC SHA256 signature verification.

This blueprint provides a secure webhook endpoint for TradingView alerts.
All webhook requests must include a valid HMAC SHA256 signature in the
'X-Tv-Signature' header, computed using TRADINGVIEW_WEBHOOK_SECRET.
"""

import hmac
import hashlib
import json
import logging
from flask import Blueprint, request, jsonify

from config import TRADINGVIEW_WEBHOOK_SECRET
from safe_order import submit_safe_order

logger = logging.getLogger("TradingViewWebhook")

# Create Flask blueprint
tradingview_bp = Blueprint('tradingview', __name__, url_prefix='/tradingview')


def verify_signature(payload_bytes: bytes, signature: str) -> bool:
    """
    Verify HMAC SHA256 signature from TradingView webhook.
    
    Args:
        payload_bytes: Raw request body as bytes
        signature: Signature from X-Tv-Signature header
    
    Returns:
        True if signature is valid, False otherwise
    """
    if not TRADINGVIEW_WEBHOOK_SECRET or TRADINGVIEW_WEBHOOK_SECRET == "your_webhook_secret_here":
        logger.error("TRADINGVIEW_WEBHOOK_SECRET not properly configured")
        return False
    
    # Compute expected signature
    expected_signature = hmac.new(
        TRADINGVIEW_WEBHOOK_SECRET.encode('utf-8'),
        payload_bytes,
        hashlib.sha256
    ).hexdigest()
    
    # Compare signatures using constant-time comparison to prevent timing attacks
    return hmac.compare_digest(expected_signature, signature)


@tradingview_bp.route('/webhook', methods=['POST'])
def webhook():
    """
    TradingView webhook endpoint.
    
    Expected payload format:
    {
        "symbol": "BTC-USD",
        "side": "buy",  // or "sell"
        "size_usd": 50.0,
        "client_order_id": "optional_id"
    }
    
    Required header:
    X-Tv-Signature: HMAC SHA256 signature of request body
    """
    # Get signature from header
    signature = request.headers.get('X-Tv-Signature', '')
    
    if not signature:
        logger.warning("Webhook request missing X-Tv-Signature header")
        return jsonify({
            "error": "Missing X-Tv-Signature header"
        }), 401
    
    # Get raw request body for signature verification
    payload_bytes = request.get_data()
    
    # Verify signature
    if not verify_signature(payload_bytes, signature):
        logger.warning("Webhook request with invalid signature")
        return jsonify({
            "error": "Invalid signature"
        }), 401
    
    # Parse JSON payload
    try:
        payload = request.get_json()
    except Exception as e:
        logger.error(f"Failed to parse webhook payload: {e}")
        return jsonify({
            "error": "Invalid JSON payload"
        }), 400
    
    # Validate required fields
    symbol = payload.get('symbol')
    side = payload.get('side')
    size_usd = payload.get('size_usd')
    
    if not all([symbol, side, size_usd]):
        logger.error(f"Webhook payload missing required fields: {payload}")
        return jsonify({
            "error": "Missing required fields: symbol, side, size_usd"
        }), 400
    
    # Validate side
    if side not in ['buy', 'sell']:
        logger.error(f"Invalid side value: {side}")
        return jsonify({
            "error": "side must be 'buy' or 'sell'"
        }), 400
    
    # Validate size_usd
    try:
        size_usd = float(size_usd)
        if size_usd <= 0:
            raise ValueError("size_usd must be positive")
    except (ValueError, TypeError) as e:
        logger.error(f"Invalid size_usd value: {size_usd}")
        return jsonify({
            "error": f"Invalid size_usd: {e}"
        }), 400
    
    # Get optional client_order_id
    client_order_id = payload.get('client_order_id')
    
    logger.info(f"TradingView webhook received: {symbol} {side} ${size_usd}")
    
    # Submit order through safe order manager
    try:
        result = submit_safe_order(
            symbol=symbol,
            side=side,
            size_usd=size_usd,
            client_order_id=client_order_id
        )
        
        # Return result
        return jsonify({
            "status": "success",
            "order_result": result
        }), 200
        
    except Exception as e:
        logger.exception(f"Failed to submit order from webhook: {e}")
        return jsonify({
            "error": f"Failed to submit order: {str(e)}"
        }), 500


@tradingview_bp.route('/health', methods=['GET'])
def health():
    """Health check endpoint for TradingView webhook service."""
    return jsonify({
        "status": "healthy",
        "service": "TradingView Webhook"
    }), 200


# Helper function to generate test signature
def generate_test_signature(payload: dict) -> str:
    """
    Generate a test signature for webhook testing.
    
    Args:
        payload: Dict to be sent as webhook payload
    
    Returns:
        HMAC SHA256 signature as hex string
    """
    payload_bytes = json.dumps(payload, separators=(',', ':')).encode('utf-8')
    signature = hmac.new(
        TRADINGVIEW_WEBHOOK_SECRET.encode('utf-8'),
        payload_bytes,
        hashlib.sha256
    ).hexdigest()
    return signature


if __name__ == "__main__":
    # Example of generating a test signature
    test_payload = {
        "symbol": "BTC-USD",
        "side": "buy",
        "size_usd": 50.0
    }
    
    signature = generate_test_signature(test_payload)
    print(f"Test payload: {json.dumps(test_payload, indent=2)}")
    print(f"Signature: {signature}")
    print(f"\nTo test with curl:")
    print(f'curl -X POST http://localhost:5000/tradingview/webhook \\')
    print(f'  -H "Content-Type: application/json" \\')
    print(f'  -H "X-Tv-Signature: {signature}" \\')
    print(f'  -d \'{json.dumps(test_payload)}\'')
