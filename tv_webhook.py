"""
TradingView webhook endpoint with HMAC SHA256 signature verification.
"""

import hmac
import hashlib
import logging
from flask import Blueprint, request, jsonify

from config import TRADINGVIEW_WEBHOOK_SECRET

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("TradingViewWebhook")

# Create Flask blueprint
tv_webhook = Blueprint('tv_webhook', __name__)


def verify_signature(payload_body, signature):
    """
    Verify HMAC SHA256 signature from TradingView.
    
    Args:
        payload_body: Raw request body as bytes
        signature: Signature from X-Tv-Signature header
    
    Returns:
        bool: True if signature is valid, False otherwise
    """
    if not signature:
        logger.warning("No signature provided in X-Tv-Signature header")
        return False
    
    # Compute expected signature
    secret_bytes = TRADINGVIEW_WEBHOOK_SECRET.encode('utf-8')
    expected_signature = hmac.new(
        secret_bytes,
        payload_body,
        hashlib.sha256
    ).hexdigest()
    
    # Compare signatures (constant-time comparison)
    is_valid = hmac.compare_digest(expected_signature, signature)
    
    if not is_valid:
        logger.warning(f"Invalid signature. Expected: {expected_signature}, Got: {signature}")
    
    return is_valid


@tv_webhook.route('/tradingview/webhook', methods=['POST'])
def handle_webhook():
    """
    Handle TradingView webhook with signature verification.
    
    Expected header: X-Tv-Signature containing HMAC SHA256 signature
    
    Returns:
        JSON response with status
    """
    try:
        # Get signature from header
        signature = request.headers.get('X-Tv-Signature', '')
        
        # Get raw request body
        payload_body = request.get_data()
        
        # Verify signature
        if not verify_signature(payload_body, signature):
            logger.error("Webhook signature verification failed")
            return jsonify({
                "status": "error",
                "message": "Invalid signature"
            }), 401
        
        # Parse JSON payload
        try:
            payload = request.get_json()
        except Exception as e:
            logger.error(f"Failed to parse JSON payload: {e}")
            return jsonify({
                "status": "error",
                "message": "Invalid JSON payload"
            }), 400
        
        # Log the webhook
        logger.info(f"Received TradingView webhook: {payload}")
        
        # Process the webhook
        # TODO: Implement your trading logic here
        # Example: Extract signal, symbol, side, etc. and call safe_order.submit_order()
        
        # For now, just acknowledge receipt
        return jsonify({
            "status": "success",
            "message": "Webhook received and verified",
            "payload": payload
        }), 200
        
    except Exception as e:
        logger.exception(f"Error processing webhook: {e}")
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500


@tv_webhook.route('/tradingview/health', methods=['GET'])
def health_check():
    """
    Health check endpoint for the TradingView webhook service.
    
    Returns:
        JSON response with service status
    """
    return jsonify({
        "status": "healthy",
        "service": "TradingView Webhook",
        "signature_verification": "enabled"
    }), 200
