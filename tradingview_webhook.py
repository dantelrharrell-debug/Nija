"""
tradingview_webhook.py - TradingView webhook endpoint with HMAC SHA256 security.

This blueprint provides a secure endpoint for receiving TradingView webhook alerts.
Security is enforced via HMAC SHA256 signature verification.
"""

import hmac
import hashlib
import json
import logging
from flask import Blueprint, request, jsonify

from config import TRADINGVIEW_WEBHOOK_SECRET

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("TradingViewWebhook")

# Validate webhook secret at module import
if not TRADINGVIEW_WEBHOOK_SECRET or TRADINGVIEW_WEBHOOK_SECRET == "your_webhook_secret_here":
    logger.warning(
        "⚠️  TRADINGVIEW_WEBHOOK_SECRET is not set or using default value. "
        "Webhook signature verification will not be secure! "
        "Set TRADINGVIEW_WEBHOOK_SECRET environment variable to a strong, random secret."
    )

# Create Flask blueprint
tradingview_bp = Blueprint('tradingview', __name__, url_prefix='/tradingview')


def verify_signature(payload_body: bytes, signature: str) -> bool:
    """
    Verify HMAC SHA256 signature from TradingView.
    
    Args:
        payload_body: Raw request body as bytes
        signature: Signature from X-Tv-Signature header
    
    Returns:
        True if signature is valid, False otherwise
    """
    if not signature:
        return False
    
    # Compute expected signature
    expected_signature = hmac.new(
        TRADINGVIEW_WEBHOOK_SECRET.encode('utf-8'),
        payload_body,
        hashlib.sha256
    ).hexdigest()
    
    # Compare signatures (constant time comparison)
    return hmac.compare_digest(expected_signature, signature)


@tradingview_bp.route('/webhook', methods=['POST'])
def webhook():
    """
    TradingView webhook endpoint.
    
    Expected header:
        X-Tv-Signature: HMAC SHA256 signature of the request body
    
    Expected payload format (example):
        {
            "symbol": "BTC-USD",
            "action": "buy",
            "price": 50000.00,
            "quantity": 0.001,
            "strategy": "MyStrategy",
            "timestamp": "2025-01-01T00:00:00Z"
        }
    """
    try:
        # Get signature from header
        signature = request.headers.get('X-Tv-Signature', '')
        
        # Verify signature
        if not verify_signature(request.data, signature):
            logger.warning("⚠️  Invalid webhook signature")
            return jsonify({
                "status": "error",
                "message": "Invalid signature"
            }), 401
        
        # Parse payload
        payload = request.get_json()
        if not payload:
            return jsonify({
                "status": "error",
                "message": "Invalid JSON payload"
            }), 400
        
        logger.info(f"✅ Received valid webhook: {payload}")
        
        # Extract trade parameters
        symbol = payload.get('symbol')
        action = payload.get('action', '').lower()
        
        if not symbol or action not in ['buy', 'sell']:
            return jsonify({
                "status": "error",
                "message": "Invalid payload: 'symbol' and 'action' (buy/sell) required"
            }), 400
        
        # Here you would integrate with safe_order.submit_order()
        # For now, we'll just log and return success
        logger.info(f"📊 Trade signal: {action.upper()} {symbol}")
        
        # TODO: Integrate with safe_order module
        # from safe_order import submit_order
        # from nija_client import CoinbaseClient
        # client = CoinbaseClient()
        # result = submit_order(
        #     client=client,
        #     symbol=symbol,
        #     side=action,
        #     size_usd=payload.get('size_usd', 10.0),
        #     metadata={'source': 'tradingview', 'strategy': payload.get('strategy')}
        # )
        
        return jsonify({
            "status": "success",
            "message": "Webhook received and processed",
            "data": {
                "symbol": symbol,
                "action": action
            }
        }), 200
    
    except Exception as e:
        logger.exception("Failed to process webhook")
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500


@tradingview_bp.route('/health', methods=['GET'])
def health():
    """Health check endpoint."""
    return jsonify({
        "status": "healthy",
        "service": "TradingView Webhook"
    }), 200
