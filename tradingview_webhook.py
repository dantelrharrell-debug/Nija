"""
TradingView Webhook Blueprint

Secure webhook endpoint for TradingView alerts with HMAC SHA256 signature verification.
"""

import hmac
import hashlib
import logging
from flask import Blueprint, request, jsonify

from config import TRADINGVIEW_WEBHOOK_SECRET

# Try to import trading modules - gracefully handle if not available
try:
    from safe_order import safe_place_order
    from nija_client import CoinbaseClient
    TRADING_MODULES_AVAILABLE = True
except ImportError as e:
    TRADING_MODULES_AVAILABLE = False
    _import_error = str(e)

# Setup logging
logger = logging.getLogger("TradingViewWebhook")

# Create Blueprint
tradingview_bp = Blueprint('tradingview', __name__, url_prefix='/api/tradingview')


def verify_signature(payload_body: bytes, signature: str) -> bool:
    """
    Verify HMAC SHA256 signature from TradingView
    
    Args:
        payload_body: Raw request body bytes
        signature: Signature from X-Tv-Signature header
    
    Returns:
        True if signature is valid, False otherwise
    """
    if not signature:
        logger.warning("No signature provided in X-Tv-Signature header")
        return False
    
    if not TRADINGVIEW_WEBHOOK_SECRET or TRADINGVIEW_WEBHOOK_SECRET == "your_webhook_secret_here":
        logger.error("TRADINGVIEW_WEBHOOK_SECRET not configured properly")
        return False
    
    # Compute HMAC SHA256
    expected_signature = hmac.new(
        TRADINGVIEW_WEBHOOK_SECRET.encode('utf-8'),
        payload_body,
        hashlib.sha256
    ).hexdigest()
    
    # Compare signatures (constant-time comparison)
    return hmac.compare_digest(signature, expected_signature)


@tradingview_bp.route('/webhook', methods=['POST'])
def webhook():
    """
    TradingView webhook endpoint with HMAC signature verification
    
    Expected headers:
        X-Tv-Signature: HMAC SHA256 signature of the request body
    
    Expected JSON payload:
        {
            "symbol": "BTC-USD",
            "side": "buy",
            "size_usd": 100.0,
            "strategy": "strategy_name",
            "alert_message": "optional alert message"
        }
    """
    try:
        # Get signature from header
        signature = request.headers.get('X-Tv-Signature', '')
        
        # Get raw request body for signature verification
        payload_body = request.get_data()
        
        # Verify signature
        if not verify_signature(payload_body, signature):
            logger.warning(f"Invalid signature for webhook from {request.remote_addr}")
            return jsonify({
                "status": "error",
                "error": "Invalid signature"
            }), 401
        
        # Parse JSON payload
        payload = request.get_json()
        if not payload:
            logger.warning("Empty or invalid JSON payload")
            return jsonify({
                "status": "error",
                "error": "Invalid JSON payload"
            }), 400
        
        logger.info(f"Received authenticated TradingView webhook: {payload}")
        
        # Extract order details
        symbol = payload.get('symbol')
        side = payload.get('side')
        size_usd = payload.get('size_usd')
        
        # Validate required fields
        if not all([symbol, side, size_usd]):
            logger.warning(f"Missing required fields in payload: {payload}")
            return jsonify({
                "status": "error",
                "error": "Missing required fields: symbol, side, size_usd"
            }), 400
        
        # Validate side
        if side not in ['buy', 'sell']:
            logger.warning(f"Invalid side '{side}' in payload")
            return jsonify({
                "status": "error",
                "error": "Invalid side. Must be 'buy' or 'sell'"
            }), 400
        
        # Validate and convert size_usd to float
        try:
            size_usd_float = float(size_usd)
            if size_usd_float <= 0:
                raise ValueError("size_usd must be positive")
        except (ValueError, TypeError) as e:
            logger.warning(f"Invalid size_usd '{size_usd}': {e}")
            return jsonify({
                "status": "error",
                "error": f"Invalid size_usd. Must be a positive number: {e}"
            }), 400
        
        # Check if trading modules are available
        if not TRADING_MODULES_AVAILABLE:
            logger.error(f"Trading modules not available: {_import_error}")
            return jsonify({
                "status": "error",
                "error": "Trading functionality not available"
            }), 500
        
        # Process order through safe_order module
        try:
            client = CoinbaseClient()
            
            # Add webhook metadata
            metadata = {
                "source": "tradingview_webhook",
                "strategy": payload.get('strategy'),
                "alert_message": payload.get('alert_message'),
                "remote_addr": request.remote_addr
            }
            
            result = safe_place_order(
                client=client,
                symbol=symbol,
                side=side,
                size_usd=size_usd_float,
                metadata=metadata
            )
            
            logger.info(f"Order processed: {result}")
            
            return jsonify({
                "status": "success",
                "result": result
            }), 200
            
        except Exception as e:
            logger.exception("Failed to process order from webhook")
            return jsonify({
                "status": "error",
                "error": f"Failed to process order: {str(e)}"
            }), 500
    
    except Exception as e:
        logger.exception("Webhook processing error")
        return jsonify({
            "status": "error",
            "error": str(e)
        }), 500


@tradingview_bp.route('/health', methods=['GET'])
def health():
    """Health check endpoint"""
    return jsonify({
        "status": "ok",
        "service": "tradingview_webhook"
    }), 200
