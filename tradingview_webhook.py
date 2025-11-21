"""
TradingView Webhook Blueprint

Provides a secure webhook endpoint for TradingView alerts with HMAC SHA256 signature verification.
"""

import hmac
import hashlib
import logging
from flask import Blueprint, request, jsonify

from config import TRADINGVIEW_WEBHOOK_SECRET

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("TradingViewWebhook")

# Create blueprint
tradingview_bp = Blueprint('tradingview', __name__)


def verify_signature(payload_body: bytes, signature: str, secret: str) -> bool:
    """
    Verify HMAC SHA256 signature.
    
    Args:
        payload_body: Raw request body bytes
        signature: Signature from X-Tv-Signature header
        secret: Webhook secret
        
    Returns:
        True if signature is valid, False otherwise
    """
    try:
        # Generate expected signature
        expected_signature = hmac.new(
            secret.encode('utf-8'),
            payload_body,
            hashlib.sha256
        ).hexdigest()
        
        # Compare signatures (constant-time comparison)
        return hmac.compare_digest(expected_signature, signature)
        
    except Exception as e:
        logger.error(f"Signature verification error: {e}")
        return False


@tradingview_bp.route('/webhook', methods=['POST'])
def webhook():
    """
    TradingView webhook endpoint.
    
    Expects:
    - X-Tv-Signature header with HMAC SHA256 signature
    - JSON payload with trading signal data
    
    Returns:
        JSON response with status
    """
    try:
        # Get signature from header
        signature = request.headers.get('X-Tv-Signature', '')
        
        if not signature:
            logger.warning("Webhook request missing X-Tv-Signature header")
            return jsonify({
                "status": "error",
                "message": "Missing X-Tv-Signature header"
            }), 401
        
        # Get raw request body
        payload_body = request.get_data()
        
        # Verify signature
        if not verify_signature(payload_body, signature, TRADINGVIEW_WEBHOOK_SECRET):
            logger.warning("Webhook signature verification failed")
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
        
        # Log received webhook (only non-sensitive fields)
        logger.info(
            f"Received TradingView webhook - signal: {payload.get('signal')}, "
            f"symbol: {payload.get('symbol')}"
        )
        
        # Process webhook payload
        # This is where you would integrate with your trading logic
        # For now, we just log and acknowledge receipt
        
        signal = payload.get('signal')
        symbol = payload.get('symbol')
        
        if signal and symbol:
            logger.info(f"TradingView signal: {signal} for {symbol}")
            
            # Here you would call your trading logic, e.g.:
            # from safe_order import submit_order
            # from nija_client import CoinbaseClient
            # client = CoinbaseClient()
            # submit_order(client, symbol, signal, size_usd=10.0)
        else:
            logger.warning("Webhook payload missing signal or symbol")
        
        return jsonify({
            "status": "success",
            "message": "Webhook received and processed"
        }), 200
        
    except Exception as e:
        logger.exception("Error processing webhook")
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500
