"""
tradingview_webhook.py - TradingView webhook endpoint with HMAC SHA256 signature validation.

This blueprint provides a secure webhook endpoint for TradingView alerts.
Requests must include an X-Tv-Signature header containing the HMAC SHA256 signature
of the request body using TRADINGVIEW_WEBHOOK_SECRET.
"""

import hmac
import hashlib
import json
import logging
from flask import Blueprint, request, jsonify

from config import TRADINGVIEW_WEBHOOK_SECRET

logger = logging.getLogger(__name__)

# Create Flask blueprint
tradingview_bp = Blueprint('tradingview', __name__)


def verify_signature(payload_body: bytes, signature: str) -> bool:
    """
    Verify HMAC SHA256 signature of the webhook payload.
    
    Args:
        payload_body: Raw request body bytes
        signature: Signature from X-Tv-Signature header
    
    Returns:
        True if signature is valid, False otherwise
    """
    if not TRADINGVIEW_WEBHOOK_SECRET or TRADINGVIEW_WEBHOOK_SECRET == "your_webhook_secret_here":
        # SECURITY: In production, this should fail, not allow unsigned requests
        # Only allowing for development/testing when secret is not configured
        from config import MODE
        if MODE == "LIVE":
            logger.error("TRADINGVIEW_WEBHOOK_SECRET must be configured for LIVE mode")
            return False
        logger.warning("TRADINGVIEW_WEBHOOK_SECRET not configured - signature verification disabled (development mode only)")
        return True
    
    try:
        # Compute expected signature
        expected_signature = hmac.new(
            TRADINGVIEW_WEBHOOK_SECRET.encode('utf-8'),
            payload_body,
            hashlib.sha256
        ).hexdigest()
        
        # Compare signatures (constant-time comparison)
        return hmac.compare_digest(signature, expected_signature)
    except Exception as e:
        logger.error(f"Signature verification error: {e}")
        return False


@tradingview_bp.route('/webhook/tradingview', methods=['POST'])
def tradingview_webhook():
    """
    TradingView webhook endpoint.
    
    Expected payload format:
    {
        "symbol": "BTC-USD",
        "side": "buy",  // or "sell"
        "size_usd": 50.0  // optional, uses default if not provided
    }
    """
    try:
        # Get signature from header
        signature = request.headers.get('X-Tv-Signature', '')
        
        # Get raw request body for signature verification
        payload_body = request.get_data()
        
        # Verify signature
        if not verify_signature(payload_body, signature):
            logger.warning(f"Invalid webhook signature from {request.remote_addr}")
            return jsonify({
                "status": "error",
                "message": "Invalid signature"
            }), 401
        
        # Parse JSON payload
        try:
            payload = request.get_json()
        except Exception as e:
            logger.error(f"Failed to parse webhook payload: {e}")
            return jsonify({
                "status": "error",
                "message": "Invalid JSON payload"
            }), 400
        
        if not payload:
            return jsonify({
                "status": "error",
                "message": "Empty payload"
            }), 400
        
        logger.info(f"Received TradingView webhook: {payload}")
        
        # Extract order parameters
        symbol = payload.get('symbol')
        side = payload.get('side', '').lower()
        size_usd = float(payload.get('size_usd', 50.0))  # Default size
        
        # Validate required fields
        if not symbol:
            return jsonify({
                "status": "error",
                "message": "Missing required field: symbol"
            }), 400
        
        if side not in ['buy', 'sell']:
            return jsonify({
                "status": "error",
                "message": "Invalid side: must be 'buy' or 'sell'"
            }), 400
        
        # Import here to avoid circular dependencies
        from safe_order import submit_order
        from nija_client import CoinbaseClient
        
        # Submit order through safe order pipeline
        try:
            client = CoinbaseClient()
            result = submit_order(client, symbol, side, size_usd)
            
            return jsonify({
                "status": "success",
                "result": result
            }), 200
            
        except Exception as e:
            logger.exception(f"Failed to submit order from webhook: {e}")
            return jsonify({
                "status": "error",
                "message": f"Order submission failed: {str(e)}"
            }), 500
        
    except Exception as e:
        logger.exception(f"Webhook handler error: {e}")
        return jsonify({
            "status": "error",
            "message": f"Internal error: {str(e)}"
        }), 500


@tradingview_bp.route('/webhook/tradingview/test', methods=['GET'])
def test_webhook():
    """Test endpoint to verify webhook is accessible."""
    from safe_order import get_order_stats
    
    stats = get_order_stats()
    
    return jsonify({
        "status": "ok",
        "message": "TradingView webhook endpoint is active",
        "order_stats": stats,
    }), 200
