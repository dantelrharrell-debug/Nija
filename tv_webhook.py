"""
tv_webhook.py - TradingView webhook endpoint with HMAC signature verification

This module provides a Flask blueprint for receiving TradingView webhooks
with HMAC SHA256 signature verification for security.
"""

import hmac
import hashlib
import logging
from flask import Blueprint, request, jsonify
from config import TRADINGVIEW_WEBHOOK_SECRET

logger = logging.getLogger("TVWebhook")

# Create blueprint
tv_webhook_bp = Blueprint('tv_webhook', __name__)

def verify_signature(payload_bytes, signature):
    """
    Verify HMAC SHA256 signature from TradingView
    
    Args:
        payload_bytes: Raw request body as bytes
        signature: Signature from X-Tv-Signature header
    
    Returns:
        bool: True if signature is valid
    """
    if not TRADINGVIEW_WEBHOOK_SECRET or TRADINGVIEW_WEBHOOK_SECRET == "your_webhook_secret_here":
        logger.warning("TRADINGVIEW_WEBHOOK_SECRET not configured - webhook security disabled!")
        return True  # Allow for development, but warn
    
    expected_signature = hmac.new(
        TRADINGVIEW_WEBHOOK_SECRET.encode('utf-8'),
        payload_bytes,
        hashlib.sha256
    ).hexdigest()
    
    return hmac.compare_digest(signature, expected_signature)

@tv_webhook_bp.route('/webhook/tradingview', methods=['POST'])
def tradingview_webhook():
    """
    Handle TradingView webhook with HMAC signature verification
    
    Expected header:
        X-Tv-Signature: HMAC SHA256 signature of request body
    
    Expected payload (JSON):
        {
            "symbol": "BTC-USD",
            "action": "buy" or "sell",
            "price": <optional>,
            "size": <optional size in USD>,
            ...
        }
    
    Returns:
        JSON response with status
    """
    try:
        # Get signature from header
        signature = request.headers.get('X-Tv-Signature', '')
        
        if not signature:
            logger.warning("Missing X-Tv-Signature header")
            return jsonify({
                'status': 'error',
                'message': 'Missing X-Tv-Signature header'
            }), 401
        
        # Get raw request body for signature verification
        payload_bytes = request.get_data()
        
        # Verify signature
        if not verify_signature(payload_bytes, signature):
            logger.warning("Invalid webhook signature")
            return jsonify({
                'status': 'error',
                'message': 'Invalid signature'
            }), 401
        
        # Parse JSON payload
        payload = request.get_json()
        
        if not payload:
            return jsonify({
                'status': 'error',
                'message': 'Invalid JSON payload'
            }), 400
        
        logger.info(f"Received TradingView webhook: {payload}")
        
        # Extract order details
        symbol = payload.get('symbol', '')
        action = payload.get('action', '').lower()
        size_usd = payload.get('size')
        
        if not symbol or action not in ['buy', 'sell']:
            return jsonify({
                'status': 'error',
                'message': 'Invalid payload - symbol and action (buy/sell) required'
            }), 400
        
        # Here you would integrate with safe_order.submit_order()
        # For now, just log and acknowledge
        response = {
            'status': 'received',
            'message': f'Webhook received: {action} {symbol}',
            'payload': payload
        }
        
        logger.info(f"Webhook processed: {response}")
        
        return jsonify(response), 200
        
    except Exception as e:
        logger.exception("Error processing TradingView webhook")
        return jsonify({
            'status': 'error',
            'message': str(e)
        }), 500

@tv_webhook_bp.route('/webhook/tradingview/health', methods=['GET'])
def webhook_health():
    """Health check endpoint for webhook"""
    return jsonify({
        'status': 'healthy',
        'endpoint': '/webhook/tradingview',
        'signature_required': True
    }), 200
