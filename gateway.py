"""
NIJA API Gateway - Layer 3 (PUBLIC)

This is the public-facing API that users interact with.
It handles authentication, billing, user controls, and statistics.

SECURITY: This layer NEVER exposes strategy logic or direct trading engine access.
Users can only view stats and control their trading (on/off, settings).

Architecture:
  [ iOS/Android/Web Apps ]
            ↓
  [ API Gateway ] ← YOU ARE HERE
            ↓
  [ User Control Backend ]
            ↓
  [ NIJA Execution Engine ]
            ↓
  [ Exchanges ]
"""

import os
import logging
from datetime import datetime, timedelta
from typing import Optional, Dict
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
import jwt
from functools import wraps
import hashlib
import secrets

from auth import get_api_key_manager, get_user_manager
from execution import get_permission_validator, UserPermissions
from user_control import get_user_control_backend

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Initialize Flask app
app = Flask(__name__)
CORS(app, resources={r"/api/*": {"origins": "*"}})

# Configuration
app.config['SECRET_KEY'] = os.getenv('JWT_SECRET_KEY', secrets.token_hex(32))
app.config['JWT_EXPIRATION_HOURS'] = int(os.getenv('JWT_EXPIRATION_HOURS', '24'))

# Get manager instances
api_key_manager = get_api_key_manager()
user_manager = get_user_manager()
permission_validator = get_permission_validator()
user_control = get_user_control_backend()

# In-memory user credentials (TODO: replace with PostgreSQL/SQLite)
# Format: {email: {password_hash: str, user_id: str}}
user_credentials = {}


def hash_password(password: str) -> str:
    """Hash password using SHA256 (TODO: upgrade to bcrypt/argon2)."""
    return hashlib.sha256(password.encode()).hexdigest()


def verify_password(password: str, password_hash: str) -> bool:
    """Verify password against hash."""
    return hash_password(password) == password_hash


def generate_jwt_token(user_id: str) -> str:
    """
    Generate JWT token for authenticated user.

    Args:
        user_id: User identifier

    Returns:
        str: JWT token
    """
    payload = {
        'user_id': user_id,
        'exp': datetime.utcnow() + timedelta(hours=app.config['JWT_EXPIRATION_HOURS']),
        'iat': datetime.utcnow()
    }
    return jwt.encode(payload, app.config['SECRET_KEY'], algorithm='HS256')


def decode_jwt_token(token: str) -> Optional[Dict]:
    """
    Decode and validate JWT token.

    Args:
        token: JWT token string

    Returns:
        dict: Decoded payload or None if invalid
    """
    try:
        payload = jwt.decode(token, app.config['SECRET_KEY'], algorithms=['HS256'])
        return payload
    except jwt.ExpiredSignatureError:
        logger.warning("JWT token has expired")
        return None
    except jwt.InvalidTokenError:
        logger.warning("Invalid JWT token")
        return None


def require_auth(f):
    """
    Decorator to require JWT authentication for endpoints.

    Expects Authorization header: "Bearer <token>"
    Adds user_id to request context.
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        auth_header = request.headers.get('Authorization')

        if not auth_header:
            return jsonify({'error': 'Missing authorization header'}), 401

        parts = auth_header.split()
        if len(parts) != 2 or parts[0].lower() != 'bearer':
            return jsonify({'error': 'Invalid authorization header format. Use: Bearer <token>'}), 401

        token = parts[1]
        payload = decode_jwt_token(token)

        if not payload:
            return jsonify({'error': 'Invalid or expired token'}), 401

        # Add user_id to request context
        request.user_id = payload['user_id']

        return f(*args, **kwargs)

    return decorated_function


# ========================================
# Frontend Serving
# ========================================

FRONTEND_DIR = os.path.join(os.path.dirname(__file__), 'frontend')
STATIC_DIR = os.path.join(FRONTEND_DIR, 'static')
TEMPLATE_DIR = os.path.join(FRONTEND_DIR, 'templates')


@app.route('/')
def serve_frontend():
    """Serve the main frontend application."""
    return send_from_directory(TEMPLATE_DIR, 'index.html')


@app.route('/static/<path:path>')
def serve_static(path):
    """Serve static files (CSS, JS, images)."""
    return send_from_directory(STATIC_DIR, path)


# ========================================
# Health Check & Info Endpoints
# ========================================

@app.route('/health', methods=['GET'])
def health_check():
    """Health check endpoint for monitoring."""
    return jsonify({
        'status': 'healthy',
        'timestamp': datetime.utcnow().isoformat(),
        'service': 'NIJA API Gateway',
        'version': '1.0.0',
        'layer': 'Layer 3 - Public API'
    })


@app.route('/api/info', methods=['GET'])
def get_info():
    """Get API information."""
    return jsonify({
        'name': 'NIJA API Gateway',
        'version': '1.0.0',
        'layer': 'Layer 3 - Public API',
        'description': 'Consumer-friendly trading platform API',
        'architecture': {
            'layer_1': 'Core Brain (PRIVATE - Strategy & AI)',
            'layer_2': 'Execution Engine (Isolated per user)',
            'layer_3': 'Public API (YOU ARE HERE)'
        },
        'endpoints': {
            'health': '/health - Health check',
            'info': '/api/info - API information',
            'auth': {
                'register': '/api/auth/register - Register new user',
                'login': '/api/auth/login - Login user'
            },
            'user': {
                'profile': '/api/user/profile - Get user profile',
                'settings': '/api/user/settings - Manage user settings',
                'brokers': '/api/user/brokers - Manage broker API keys',
                'stats': '/api/user/stats - Get trading statistics'
            },
            'trading': {
                'status': '/api/trading/status - Get trading status',
                'control': '/api/trading/control - Start/stop trading',
                'positions': '/api/trading/positions - Get active positions',
                'history': '/api/trading/history - Get trade history'
            }
        }
    })


# ========================================
# Authentication Endpoints
# ========================================

@app.route('/api/auth/register', methods=['POST'])
def register():
    """
    Register a new user.

    Request body:
        {
            "email": "user@example.com",
            "password": "secure_password",
            "subscription_tier": "basic"  // optional: basic, pro, enterprise
        }
    """
    data = request.get_json()

    if not data or 'email' not in data or 'password' not in data:
        return jsonify({'error': 'Email and password are required'}), 400

    email = data['email'].lower().strip()
    password = data['password']
    subscription_tier = data.get('subscription_tier', 'basic')

    # Validate email format (basic check)
    if '@' not in email or '.' not in email:
        return jsonify({'error': 'Invalid email format'}), 400

    # Check if user already exists
    if email in user_credentials:
        return jsonify({'error': 'User already exists'}), 409

    # Create user ID
    user_id = f"user_{secrets.token_hex(8)}"

    # Store credentials
    user_credentials[email] = {
        'password_hash': hash_password(password),
        'user_id': user_id
    }

    # Create user profile
    try:
        user_profile = user_manager.create_user(
            user_id=user_id,
            email=email,
            subscription_tier=subscription_tier
        )

        # Register default permissions based on tier
        max_position_size = {
            'basic': 100.0,
            'pro': 1000.0,
            'enterprise': 10000.0
        }.get(subscription_tier, 100.0)

        permissions = UserPermissions(
            user_id=user_id,
            max_position_size_usd=max_position_size,
            max_daily_loss_usd=max_position_size * 0.5,
            max_positions=3 if subscription_tier == 'basic' else 10
        )
        permission_validator.register_user(permissions)

        # Generate token
        token = generate_jwt_token(user_id)

        logger.info(f"✅ New user registered: {email} (ID: {user_id}, Tier: {subscription_tier})")

        return jsonify({
            'message': 'User registered successfully',
            'user_id': user_id,
            'email': email,
            'subscription_tier': subscription_tier,
            'token': token
        }), 201

    except Exception as e:
        logger.error(f"❌ Failed to register user: {e}")
        return jsonify({'error': 'Registration failed'}), 500


@app.route('/api/auth/login', methods=['POST'])
def login():
    """
    Login user and return JWT token.

    Request body:
        {
            "email": "user@example.com",
            "password": "secure_password"
        }
    """
    data = request.get_json()

    if not data or 'email' not in data or 'password' not in data:
        return jsonify({'error': 'Email and password are required'}), 400

    email = data['email'].lower().strip()
    password = data['password']

    # Check credentials
    if email not in user_credentials:
        return jsonify({'error': 'Invalid credentials'}), 401

    user_creds = user_credentials[email]

    if not verify_password(password, user_creds['password_hash']):
        return jsonify({'error': 'Invalid credentials'}), 401

    user_id = user_creds['user_id']

    # Get user profile
    user_profile = user_manager.get_user(user_id)

    if not user_profile or not user_profile.get('enabled', True):
        return jsonify({'error': 'Account disabled'}), 403

    # Generate token
    token = generate_jwt_token(user_id)

    logger.info(f"✅ User logged in: {email} (ID: {user_id})")

    return jsonify({
        'message': 'Login successful',
        'user_id': user_id,
        'email': email,
        'subscription_tier': user_profile.get('subscription_tier', 'basic'),
        'token': token
    })


# ========================================
# User Management Endpoints
# ========================================

@app.route('/api/user/profile', methods=['GET'])
@require_auth
def get_user_profile():
    """Get user profile (requires authentication)."""
    user_id = request.user_id
    user_profile = user_manager.get_user(user_id)

    if not user_profile:
        return jsonify({'error': 'User not found'}), 404

    # Get user permissions
    permissions = permission_validator.get_user_permissions(user_id)

    return jsonify({
        'user_id': user_id,
        'email': user_profile['email'],
        'subscription_tier': user_profile['subscription_tier'],
        'created_at': user_profile['created_at'],
        'enabled': user_profile['enabled'],
        'brokers': api_key_manager.list_user_brokers(user_id),
        'permissions': permissions.to_dict() if permissions else None
    })


@app.route('/api/user/settings', methods=['GET', 'PUT'])
@require_auth
def user_settings():
    """Get or update user settings."""
    user_id = request.user_id

    if request.method == 'GET':
        user_profile = user_manager.get_user(user_id)
        if not user_profile:
            return jsonify({'error': 'User not found'}), 404

        return jsonify({
            'subscription_tier': user_profile.get('subscription_tier', 'basic'),
            'enabled': user_profile.get('enabled', True)
        })

    elif request.method == 'PUT':
        data = request.get_json()

        # Only allow updating certain fields
        allowed_updates = {}
        if 'subscription_tier' in data:
            allowed_updates['subscription_tier'] = data['subscription_tier']

        if allowed_updates:
            user_manager.update_user(user_id, allowed_updates)
            logger.info(f"User {user_id} updated settings: {allowed_updates}")

        return jsonify({'message': 'Settings updated successfully'})


# ========================================
# Broker API Key Management Endpoints
# ========================================

@app.route('/api/user/brokers', methods=['GET'])
@require_auth
def list_brokers():
    """List all configured brokers for user."""
    user_id = request.user_id
    brokers = api_key_manager.list_user_brokers(user_id)

    return jsonify({
        'user_id': user_id,
        'brokers': brokers,
        'count': len(brokers)
    })


@app.route('/api/user/brokers/<broker_name>', methods=['POST', 'DELETE'])
@require_auth
def manage_broker_keys(broker_name: str):
    """
    Add or remove broker API keys.

    SECURITY NOTE: API keys are encrypted and stored securely.
    They are NEVER exposed to the public API or logs.
    """
    user_id = request.user_id

    # Validate broker name
    supported_brokers = ['coinbase', 'kraken', 'binance', 'okx', 'alpaca']
    if broker_name.lower() not in supported_brokers:
        return jsonify({
            'error': f'Unsupported broker. Supported: {", ".join(supported_brokers)}'
        }), 400

    if request.method == 'POST':
        data = request.get_json()

        if not data or 'api_key' not in data or 'api_secret' not in data:
            return jsonify({'error': 'api_key and api_secret are required'}), 400

        api_key = data['api_key']
        api_secret = data['api_secret']
        additional_params = data.get('additional_params', {})

        # Store encrypted credentials
        api_key_manager.store_user_api_key(
            user_id=user_id,
            broker=broker_name.lower(),
            api_key=api_key,
            api_secret=api_secret,
            additional_params=additional_params
        )

        logger.info(f"✅ User {user_id} added {broker_name} API credentials")

        return jsonify({
            'message': f'{broker_name} API credentials added successfully',
            'broker': broker_name
        }), 201

    elif request.method == 'DELETE':
        success = api_key_manager.delete_user_api_key(user_id, broker_name.lower())

        if success:
            logger.info(f"✅ User {user_id} removed {broker_name} API credentials")
            return jsonify({
                'message': f'{broker_name} API credentials removed successfully'
            })
        else:
            return jsonify({
                'error': f'No {broker_name} credentials found for this user'
            }), 404


# ========================================
# Trading Control Endpoints (Layer 3 → Layer 2)
# ========================================

@app.route('/api/trading/control', methods=['POST'])
@require_auth
def trading_control():
    """
    Control user's trading engine (start/stop).

    This endpoint sends commands to Layer 2 (Execution Engine).
    It does NOT expose strategy logic (Layer 1).

    Request body:
        {
            "action": "start" | "stop" | "pause"
        }
    """
    user_id = request.user_id
    data = request.get_json()

    if not data or 'action' not in data:
        return jsonify({'error': 'Action is required (start/stop/pause)'}), 400

    action = data['action'].lower()

    if action not in ['start', 'stop', 'pause']:
        return jsonify({'error': 'Invalid action. Use: start, stop, or pause'}), 400

    # Send command to User Control Backend (Layer 2)
    if action == 'start':
        result = user_control.start_trading(user_id)
    elif action == 'stop':
        result = user_control.stop_trading(user_id)
    elif action == 'pause':
        result = user_control.pause_trading(user_id)
    else:
        result = {'success': False, 'error': 'Invalid action'}

    logger.info(f"🎮 User {user_id} trading control: {action} -> {result}")

    if result.get('success'):
        return jsonify({
            'message': result.get('message', f'Trading {action} successful'),
            'user_id': user_id,
            'action': action,
            'status': result.get('status', 'unknown')
        })
    else:
        return jsonify({
            'error': result.get('error', 'Command failed'),
            'user_id': user_id,
            'action': action
        }), 400


@app.route('/api/trading/status', methods=['GET'])
@require_auth
def get_trading_status():
    """
    Get current trading status for user.

    Returns status from Layer 2 (Execution Engine) without exposing
    strategy logic from Layer 1 (Core Brain).
    """
    user_id = request.user_id

    # Query User Control Backend for user's trading status
    status = user_control.get_user_status(user_id)

    # Format response
    response = {
        'user_id': user_id,
        'trading_enabled': status.get('status') == 'running',
        'engine_status': status.get('status', 'unknown'),
        'last_activity': status.get('last_activity'),
        'created_at': status.get('created_at'),
        'stats': status.get('stats', {}),
        'layer': 'Layer 2 - Execution Engine'
    }

    return jsonify(response)


@app.route('/api/trading/positions', methods=['GET'])
@require_auth
def get_positions():
    """
    Get active trading positions for user.

    Returns position data from Layer 2 (Execution Engine).
    Does NOT expose entry/exit logic from Layer 1 (Core Brain).
    """
    user_id = request.user_id

    # Query User Control Backend for user's active positions
    positions = user_control.get_user_positions(user_id)

    return jsonify({
        'user_id': user_id,
        'positions': positions,
        'count': len(positions)
    })


@app.route('/api/trading/history', methods=['GET'])
@require_auth
def get_trade_history():
    """
    Get trade history for user.

    Returns historical trade data from Layer 2 (Execution Engine).
    Does NOT expose strategy signals from Layer 1 (Core Brain).
    """
    user_id = request.user_id

    # Optional query parameters
    limit = request.args.get('limit', 50, type=int)
    offset = request.args.get('offset', 0, type=int)

    # TODO: Query Layer 2 for user's trade history
    trades = []

    return jsonify({
        'user_id': user_id,
        'trades': trades,
        'count': len(trades),
        'limit': limit,
        'offset': offset
    })


# ========================================
# Statistics Endpoints (Read-Only)
# ========================================

@app.route('/api/user/stats', methods=['GET'])
@require_auth
def get_user_stats():
    """
    Get user trading statistics.

    Returns aggregated statistics from Layer 2 (Execution Engine).
    Does NOT expose strategy performance metrics from Layer 1 (Core Brain).
    """
    user_id = request.user_id

    # Query User Control Backend for user statistics
    stats = user_control.get_user_stats(user_id)

    # Add additional calculated fields
    if 'total_pnl' not in stats:
        stats['total_pnl'] = 0.0
    if 'win_rate' not in stats:
        stats['win_rate'] = 0.0
    if 'total_profit' not in stats:
        stats['total_profit'] = 0.0
    if 'total_loss' not in stats:
        stats['total_loss'] = 0.0

    return jsonify(stats)


# ========================================
# Error Handlers
# ========================================

@app.errorhandler(404)
def not_found(error):
    """Handle 404 errors."""
    return jsonify({'error': 'Endpoint not found'}), 404


@app.errorhandler(500)
def internal_error(error):
    """Handle 500 errors."""
    logger.error(f"Internal server error: {error}")
    return jsonify({'error': 'Internal server error'}), 500


# ========================================
# Main Entry Point
# ========================================

if __name__ == '__main__':
    port = int(os.getenv('PORT', 5000))
    debug = os.getenv('FLASK_DEBUG', 'False').lower() == 'true'

    logger.info("=" * 60)
    logger.info("🚀 Starting NIJA API Gateway (Layer 3 - Public API)")
    logger.info("=" * 60)
    logger.info(f"Port: {port}")
    logger.info(f"Debug: {debug}")
    logger.info(f"Frontend: http://localhost:{port}/")
    logger.info(f"API: http://localhost:{port}/api/")
    logger.info("=" * 60)
    logger.info("Architecture:")
    logger.info("  Layer 1: Core Brain (PRIVATE - Strategy & AI)")
    logger.info("  Layer 2: Execution Engine (Isolated per user)")
    logger.info("  Layer 3: Public API Gateway ← YOU ARE HERE")
    logger.info("=" * 60)

    app.run(
        host='0.0.0.0',
        port=port,
        debug=debug
    )
