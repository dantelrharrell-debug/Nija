"""NIJA Mobile-Ready Backend Server.

Production entry point for the mobile REST and WebSocket service. The gateway
adds a defense-in-depth JWT gate for all user-scoped mobile API namespaces so a
route cannot accidentally become public merely because a decorator is omitted.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime

from flask import jsonify, request
from flask_cors import CORS
from flask_socketio import SocketIO

from api_server import app as base_app, decode_jwt_token
from auth.user_database import get_user_database
from unified_mobile_api import register_unified_mobile_api
from iap_handler import register_iap_api
from education_system import register_education_api
from mobile_api import mobile_api, MOBILE_API_BASE
from account_deletion_api import account_deletion_api
from pricing_api import pricing_api

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

app = base_app

_DEFAULT_ORIGINS = "https://nijaaitrading.com,https://www.nijaaitrading.com"
_allowed_origins = [
    origin.strip()
    for origin in os.getenv("ALLOWED_ORIGINS", _DEFAULT_ORIGINS).split(",")
    if origin.strip()
]
if "*" in _allowed_origins:
    logger.warning("Wildcard mobile CORS is enabled; production should use explicit origins")

socketio = SocketIO(
    app,
    cors_allowed_origins=_allowed_origins,
    async_mode="threading",
    logger=True,
    engineio_logger=False,
)

CORS(
    app,
    resources={
        r"/api/*": {
            "origins": _allowed_origins,
            "methods": ["GET", "POST", "PUT", "DELETE", "OPTIONS"],
            "allow_headers": ["Content-Type", "Authorization"],
            "expose_headers": ["Content-Type", "Authorization"],
            "supports_credentials": True,
            "max_age": 3600,
        }
    },
)

# Public endpoints inside otherwise protected mobile namespaces.
_PUBLIC_MOBILE_PATHS = {
    "/api/mobile/status",
    "/api/mobile/config",
    "/api/v1/subscription/tiers",
}
_PROTECTED_PREFIXES = ("/api/mobile/", "/api/v1/", "/api/account/")


@app.before_request
def mobile_gateway_authentication():
    """Fail closed for every user-scoped mobile HTTP request.

    This is deliberately in addition to route-level decorators. It protects new
    endpoints from accidental exposure and also verifies that the JWT subject
    still maps to an enabled account, immediately invalidating tokens after
    account deletion/disablement.
    """
    if request.method == "OPTIONS":
        return None
    if request.path in _PUBLIC_MOBILE_PATHS:
        return None
    if not request.path.startswith(_PROTECTED_PREFIXES):
        return None

    auth_header = request.headers.get("Authorization", "")
    parts = auth_header.split()
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return jsonify({"error": "Authentication required"}), 401

    payload = decode_jwt_token(parts[1])
    user_id = payload.get("user_id") if isinstance(payload, dict) else None
    if not isinstance(user_id, str) or not user_id:
        return jsonify({"error": "Invalid or expired token"}), 401

    user_record = get_user_database().get_user(user_id)
    if not user_record or not user_record.get("enabled", True):
        return jsonify({"error": "Account is unavailable"}), 401

    request.user_id = user_id
    return None


app.register_blueprint(mobile_api)
logger.info("Registered mobile_api blueprint")

app.register_blueprint(account_deletion_api)
logger.info("Registered account_deletion_api blueprint")

app.register_blueprint(pricing_api)
logger.info("Registered canonical pricing_api blueprint")

register_unified_mobile_api(app, socketio)
register_iap_api(app)
register_education_api(app)


@app.route("/")
def index():
    return jsonify({
        "name": "NIJA Mobile API",
        "version": "1.1.0",
        "description": "Mobile-ready REST and WebSocket API for NIJA trading platform",
        "documentation": "/api/docs",
        "health": "/health",
        "status": "/status",
        "api_versions": {
            "v1": "/api/v1",
            "mobile": MOBILE_API_BASE,
            "iap": "/api/iap",
            "education": "/api/education",
            "commercial_pricing": "/api/commercial/pricing",
        },
        "features": [
            "Authenticated trading control and monitoring",
            "Real-time position updates via WebSocket",
            "Subscription management",
            "Canonical commercial pricing policy",
            "In-app purchase validation (iOS/Android)",
            "Education content delivery",
            "Performance analytics",
            "Multi-broker support",
            "Authenticated account deletion",
            "Persistent encrypted mobile device registration",
        ],
        "websocket": {
            "endpoint": "/socket.io",
            "events": ["connect", "disconnect", "subscribe_positions", "subscribe_trades"],
        },
    })


@app.route("/api/docs")
def api_documentation():
    return jsonify({
        "title": "NIJA Mobile API Documentation",
        "version": "1.1.0",
        "base_url": request.host_url,
        "authentication": {
            "type": "Bearer JWT",
            "header": "Authorization: Bearer <token>",
            "endpoints": {
                "register": "POST /api/auth/register",
                "login": "POST /api/auth/login",
            },
        },
        "endpoints": {
            "Commercial Pricing": {
                "get_public_pricing": "GET /api/commercial/pricing",
                "get_locked_user_offer": "GET /api/commercial/offer/<user_id>",
            },
            "Trading Control": {
                "start_trading": "POST /api/v1/trading/start",
                "stop_trading": "POST /api/v1/trading/stop",
                "get_status": "GET /api/v1/trading/status",
                "get_positions": "GET /api/v1/positions",
            },
            "Device": {
                "register": "POST /api/mobile/device/register",
                "unregister": "DELETE /api/mobile/device/unregister",
                "list": "GET /api/mobile/device/list",
            },
            "Subscriptions": {
                "get_info": "GET /api/v1/subscription/info",
                "get_tiers": "GET /api/v1/subscription/tiers",
                "upgrade": "POST /api/v1/subscription/upgrade",
            },
            "In-App Purchases": {
                "verify_ios": "POST /api/iap/verify/ios",
                "verify_android": "POST /api/iap/verify/android",
                "get_status": "GET /api/iap/subscription/status",
            },
            "Education": {
                "get_catalog": "GET /api/education/catalog",
                "get_lesson": "GET /api/education/lessons/<id>",
                "get_progress": "GET /api/education/progress",
                "update_progress": "POST /api/education/progress/<lesson_id>",
            },
            "Analytics": {"get_performance": "GET /api/v1/analytics/performance"},
            "Account": {
                "get_deletion_requirements": "GET /api/account/deletion",
                "delete_account": "DELETE /api/account/deletion",
            },
        },
        "rate_limits": {
            "free": "10 requests/minute",
            "basic": "30 requests/minute",
            "pro": "100 requests/minute",
            "enterprise": "300 requests/minute",
        },
    })


@app.errorhandler(404)
def not_found(error):
    return jsonify({
        "error": "Endpoint not found",
        "message": "The requested endpoint does not exist",
        "documentation": "/api/docs",
    }), 404


@app.errorhandler(500)
def internal_error(error):
    logger.error("Internal server error: %s", error)
    return jsonify({
        "error": "Internal server error",
        "message": "An unexpected error occurred",
        "timestamp": datetime.utcnow().isoformat(),
    }), 500


@app.errorhandler(403)
def forbidden(error):
    return jsonify({
        "error": "Forbidden",
        "message": "You do not have permission to access this resource",
        "subscription_info": "/api/v1/subscription/tiers",
    }), 403


if __name__ == "__main__":
    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", 5000))
    debug = os.getenv("DEBUG", "false").lower() == "true"

    logger.info("NIJA Mobile-Ready Backend Server starting on %s:%s", host, port)
    logger.info("Environment: %s", os.getenv("FLASK_ENV", "development"))
    socketio.run(
        app,
        host=host,
        port=port,
        debug=debug,
        use_reloader=debug,
        log_output=True,
    )