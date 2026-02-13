"""
NIJA Mobile-Ready Backend Server

Main entry point for the mobile-ready REST API and WebSocket server.
This server integrates all mobile features:
- Trading engine API
- In-app purchase validation
- Education content delivery
- Real-time WebSocket updates
- Subscription management

Deploy this to your cloud provider (AWS, GCP, Azure, Railway, etc.)

Author: NIJA Trading Systems
Version: 1.0
Date: February 2026
"""

import os
import logging
from datetime import datetime

from flask import Flask, jsonify
from flask_cors import CORS
from flask_socketio import SocketIO

# Import API blueprints
from api_server import app as base_app, require_auth
from unified_mobile_api import register_unified_mobile_api
from iap_handler import register_iap_api
from education_system import register_education_api
from mobile_api import mobile_api

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# ========================================
# Application Configuration
# ========================================

# Use existing Flask app from api_server or create new one
app = base_app

# Add WebSocket support
socketio = SocketIO(
    app,
    cors_allowed_origins="*",
    async_mode='threading',
    logger=True,
    engineio_logger=False
)

# Configure CORS for mobile apps
CORS(app, resources={
    r"/api/*": {
        "origins": os.getenv('ALLOWED_ORIGINS', '*').split(','),
        "methods": ["GET", "POST", "PUT", "DELETE", "OPTIONS"],
        "allow_headers": ["Content-Type", "Authorization"],
        "expose_headers": ["Content-Type", "Authorization"],
        "supports_credentials": True,
        "max_age": 3600
    }
})

# ========================================
# Register All API Blueprints
# ========================================

# Mobile API endpoints
app.register_blueprint(mobile_api)
logger.info("Registered mobile_api blueprint")

# Unified mobile API (v1) with subscription enforcement
register_unified_mobile_api(app, socketio)

# In-app purchase handlers
register_iap_api(app)

# Education content system
register_education_api(app)

# ========================================
# Root Endpoints
# ========================================

@app.route('/')
def index():
    """
    API root - provides API information and available endpoints.
    """
    return jsonify({
        'name': 'NIJA Mobile API',
        'version': '1.0.0',
        'description': 'Mobile-ready REST and WebSocket API for NIJA trading platform',
        'documentation': '/api/docs',
        'health': '/health',
        'status': '/status',
        'api_versions': {
            'v1': '/api/v1',
            'mobile': '/api/mobile',
            'iap': '/api/iap',
            'education': '/api/education'
        },
        'features': [
            'Trading control and monitoring',
            'Real-time position updates via WebSocket',
            'Subscription management',
            'In-app purchase validation (iOS/Android)',
            'Education content delivery',
            'Performance analytics',
            'Multi-broker support'
        ],
        'websocket': {
            'endpoint': '/socket.io',
            'events': ['connect', 'disconnect', 'subscribe_positions', 'subscribe_trades']
        }
    })


@app.route('/api/docs')
def api_documentation():
    """
    API documentation overview.
    """
    return jsonify({
        'title': 'NIJA Mobile API Documentation',
        'version': '1.0.0',
        'base_url': request.host_url,
        'authentication': {
            'type': 'Bearer JWT',
            'header': 'Authorization: Bearer <token>',
            'endpoints': {
                'register': 'POST /api/auth/register',
                'login': 'POST /api/auth/login'
            }
        },
        'endpoints': {
            'Trading Control': {
                'start_trading': 'POST /api/v1/trading/start',
                'stop_trading': 'POST /api/v1/trading/stop',
                'get_status': 'GET /api/v1/trading/status',
                'get_positions': 'GET /api/v1/positions'
            },
            'Subscriptions': {
                'get_info': 'GET /api/v1/subscription/info',
                'get_tiers': 'GET /api/v1/subscription/tiers',
                'upgrade': 'POST /api/v1/subscription/upgrade'
            },
            'In-App Purchases': {
                'verify_ios': 'POST /api/iap/verify/ios',
                'verify_android': 'POST /api/iap/verify/android',
                'get_status': 'GET /api/iap/subscription/status'
            },
            'Education': {
                'get_catalog': 'GET /api/education/catalog',
                'get_lesson': 'GET /api/education/lessons/<id>',
                'get_progress': 'GET /api/education/progress',
                'update_progress': 'POST /api/education/progress/<lesson_id>'
            },
            'Analytics': {
                'get_performance': 'GET /api/v1/analytics/performance'
            }
        },
        'websocket': {
            'url': f'ws://{request.host}/socket.io',
            'events': {
                'subscribe_positions': 'Subscribe to real-time position updates',
                'subscribe_trades': 'Subscribe to real-time trade executions',
                'position_update': 'Receive position updates',
                'trade_execution': 'Receive trade notifications'
            }
        },
        'rate_limits': {
            'free': '10 requests/minute',
            'basic': '30 requests/minute',
            'pro': '100 requests/minute',
            'enterprise': '300 requests/minute'
        }
    })


# ========================================
# Error Handlers
# ========================================

@app.errorhandler(404)
def not_found(error):
    """Handle 404 errors"""
    return jsonify({
        'error': 'Endpoint not found',
        'message': 'The requested endpoint does not exist',
        'documentation': '/api/docs'
    }), 404


@app.errorhandler(500)
def internal_error(error):
    """Handle 500 errors"""
    logger.error(f"Internal server error: {error}")
    return jsonify({
        'error': 'Internal server error',
        'message': 'An unexpected error occurred',
        'timestamp': datetime.utcnow().isoformat()
    }), 500


@app.errorhandler(403)
def forbidden(error):
    """Handle 403 errors"""
    return jsonify({
        'error': 'Forbidden',
        'message': 'You do not have permission to access this resource',
        'subscription_info': '/api/v1/subscription/tiers'
    }), 403


# ========================================
# Main Entry Point
# ========================================

if __name__ == '__main__':
    # Configuration
    host = os.getenv('HOST', '0.0.0.0')
    port = int(os.getenv('PORT', 5000))
    debug = os.getenv('DEBUG', 'false').lower() == 'true'
    
    logger.info("=" * 60)
    logger.info("NIJA Mobile-Ready Backend Server")
    logger.info("=" * 60)
    logger.info(f"Starting server on {host}:{port}")
    logger.info(f"Debug mode: {debug}")
    logger.info(f"Environment: {os.getenv('FLASK_ENV', 'development')}")
    logger.info("=" * 60)
    logger.info("\nRegistered Endpoints:")
    logger.info("  Root: /")
    logger.info("  Docs: /api/docs")
    logger.info("  Health: /health, /healthz")
    logger.info("  Status: /status")
    logger.info("\nAPI Versions:")
    logger.info("  v1: /api/v1/*")
    logger.info("  Mobile: /api/mobile/*")
    logger.info("  IAP: /api/iap/*")
    logger.info("  Education: /api/education/*")
    logger.info("\nWebSocket:")
    logger.info(f"  Endpoint: ws://{host}:{port}/socket.io")
    logger.info("=" * 60)
    
    # Start server with WebSocket support
    socketio.run(
        app,
        host=host,
        port=port,
        debug=debug,
        use_reloader=debug,
        log_output=True
    )
