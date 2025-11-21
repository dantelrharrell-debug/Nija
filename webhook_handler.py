"""
TradingView Webhook Handler with HMAC SHA256 signature verification
"""
import hmac
import hashlib
import logging
from flask import Blueprint, request, jsonify

from config import TRADINGVIEW_WEBHOOK_SECRET

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("WebhookHandler")

# Create Flask Blueprint
webhook_bp = Blueprint('tradingview_webhook', __name__)


def verify_signature(payload: bytes, signature: str) -> bool:
    """
    Verify HMAC SHA256 signature from TradingView.
    
    Args:
        payload: Raw request body bytes
        signature: Signature from X-Tv-Signature header
    
    Returns:
        True if signature is valid, False otherwise
    """
    if not TRADINGVIEW_WEBHOOK_SECRET:
        logger.warning("TRADINGVIEW_WEBHOOK_SECRET not set - signature verification disabled")
        return True  # Allow requests if no secret is configured (for testing)
    
    try:
        # Compute expected signature
        expected_signature = hmac.new(
            TRADINGVIEW_WEBHOOK_SECRET.encode('utf-8'),
            payload,
            hashlib.sha256
        ).hexdigest()
        
        # Compare signatures (constant-time comparison)
        return hmac.compare_digest(expected_signature, signature)
    except Exception as e:
        logger.error(f"Error verifying signature: {e}")
        return False


@webhook_bp.route('/tradingview/webhook', methods=['POST'])
def tradingview_webhook():
    """
    TradingView webhook endpoint with HMAC SHA256 signature verification.
    
    Expected header: X-Tv-Signature
    Expected payload: JSON with trading signal data
    """
    # Get signature from header
    signature = request.headers.get('X-Tv-Signature', '')
    
    # Get raw payload
    payload = request.get_data()
    
    # Verify signature
    if not verify_signature(payload, signature):
        logger.warning("Invalid webhook signature")
        return jsonify({
            "status": "error",
            "message": "Invalid signature"
        }), 401
    
    # Parse JSON payload
    try:
        data = request.get_json()
    except Exception as e:
        logger.error(f"Failed to parse webhook payload: {e}")
        return jsonify({
            "status": "error",
            "message": "Invalid JSON payload"
        }), 400
    
    logger.info(f"Received valid TradingView webhook: {data}")
    
    # Process webhook data
    # This would typically trigger a trade via safe_order.submit_order()
    # For now, just acknowledge receipt
    
    try:
        # Extract common TradingView fields
        action = data.get('action')  # e.g., "buy", "sell"
        symbol = data.get('symbol')  # e.g., "BTC-USD"
        price = data.get('price')
        
        logger.info(f"TradingView signal - Action: {action}, Symbol: {symbol}, Price: {price}")
        
        # Here you would call safe_order.submit_order() to execute the trade
        # Example:
        # from safe_order import submit_order
        # from nija_client import CoinbaseClient
        # client = CoinbaseClient()
        # result = submit_order(client, symbol, action, size_usd)
        
        return jsonify({
            "status": "success",
            "message": "Webhook received and processed",
            "data": {
                "action": action,
                "symbol": symbol
            }
        }), 200
        
    except Exception as e:
        logger.exception("Error processing webhook")
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500


@webhook_bp.route('/tradingview/health', methods=['GET'])
def webhook_health():
    """Health check endpoint for webhook service."""
    return jsonify({
        "status": "healthy",
        "service": "TradingView Webhook Handler",
        "signature_verification": "enabled" if TRADINGVIEW_WEBHOOK_SECRET else "disabled"
    }), 200
