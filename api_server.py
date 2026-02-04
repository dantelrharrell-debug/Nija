"""
NIJA Cloud API Backend

This is the main REST API server that provides a consumer-friendly interface
for the NIJA trading platform. It handles user authentication, broker management,
and trading control.

Architecture:
  Mobile App / Web App
         ↓
  Cloud API Backend (this file)
         ↓
  Execution Engine (NIJA)
         ↓
  Exchange APIs
"""

import os
import logging
from datetime import datetime, timedelta
from typing import Optional, Dict, List
from flask import Flask, request, jsonify
from flask_cors import CORS
import jwt
from functools import wraps
import hashlib
import secrets

from auth import get_api_key_manager, get_user_manager
from execution import get_permission_validator, UserPermissions
from bot.kill_switch import get_kill_switch

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

# In-memory user credentials (TODO: replace with database)
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
# Health Check & Info Endpoints
# ========================================

@app.route('/health', methods=['GET'])
def health_check():
    """Health check endpoint for monitoring."""
    return jsonify({
        'status': 'healthy',
        'timestamp': datetime.utcnow().isoformat(),
        'service': 'NIJA Cloud API',
        'version': '1.0.0'
    })


@app.route('/api/info', methods=['GET'])
def get_info():
    """Get API information."""
    return jsonify({
        'name': 'NIJA Cloud API',
        'version': '1.0.0',
        'description': 'Consumer-friendly trading platform API',
        'endpoints': [
            '/health - Health check',
            '/api/info - API information',
            '/api/auth/register - Register new user',
            '/api/auth/login - Login user',
            '/api/user/profile - Get user profile',
            '/api/user/brokers - Manage broker API keys',
            '/api/user/stats - Get trading statistics',
            '/api/trading/status - Get trading status',
            '/api/trading/positions - Get active positions'
        ]
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

        logger.info(f"New user registered: {email} (ID: {user_id}, Tier: {subscription_tier})")

        return jsonify({
            'message': 'User registered successfully',
            'user_id': user_id,
            'email': email,
            'subscription_tier': subscription_tier,
            'token': token
        }), 201

    except Exception as e:
        logger.error(f"Failed to register user: {e}")
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

    logger.info(f"User logged in: {email} (ID: {user_id})")

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
    """Add or remove broker API keys."""
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

        logger.info(f"User {user_id} added {broker_name} API credentials")

        return jsonify({
            'message': f'{broker_name} API credentials added successfully',
            'broker': broker_name
        }), 201

    elif request.method == 'DELETE':
        success = api_key_manager.delete_user_api_key(user_id, broker_name.lower())

        if success:
            logger.info(f"User {user_id} removed {broker_name} API credentials")
            return jsonify({
                'message': f'{broker_name} API credentials removed successfully'
            })
        else:
            return jsonify({
                'error': f'No {broker_name} credentials found for this user'
            }), 404


# ========================================
# Trading Status & Statistics Endpoints
# ========================================

@app.route('/api/user/stats', methods=['GET'])
@require_auth
def get_user_stats():
    """Get user trading statistics."""
    user_id = request.user_id

    # TODO: Implement actual stats from trading engine
    # For now, return placeholder data
    stats = {
        'user_id': user_id,
        'total_trades': 0,
        'win_rate': 0.0,
        'total_pnl': 0.0,
        'total_profit': 0.0,
        'total_loss': 0.0,
        'active_positions': 0,
        'daily_pnl': 0.0,
        'weekly_pnl': 0.0,
        'monthly_pnl': 0.0
    }

    return jsonify(stats)


@app.route('/api/trading/status', methods=['GET'])
@require_auth
def get_trading_status():
    """Get current trading status for user."""
    user_id = request.user_id

    # TODO: Implement actual trading status from execution engine
    status = {
        'user_id': user_id,
        'trading_enabled': True,
        'active_positions': 0,
        'pending_orders': 0,
        'last_trade_time': None,
        'engine_status': 'running'
    }

    return jsonify(status)


@app.route('/api/trading/positions', methods=['GET'])
@require_auth
def get_positions():
    """Get active trading positions for user."""
    user_id = request.user_id

    # TODO: Implement actual position tracking
    positions = []

    return jsonify({
        'user_id': user_id,
        'positions': positions,
        'count': len(positions)
    })


@app.route('/api/trading/history', methods=['GET'])
@require_auth
def get_trade_history():
    """Get trade history for user."""
    user_id = request.user_id

    # Optional query parameters
    limit = request.args.get('limit', 50, type=int)
    offset = request.args.get('offset', 0, type=int)

    # TODO: Implement actual trade history retrieval
    trades = []

    return jsonify({
        'user_id': user_id,
        'trades': trades,
        'count': len(trades),
        'limit': limit,
        'offset': offset
    })


# ========================================
# Emergency Controls - Kill Switch
# ========================================

@app.route('/api/emergency/kill-switch/status', methods=['GET'])
def get_kill_switch_status():
    """
    Get kill-switch status (no auth required for emergency access).
    
    Returns kill switch status and recent activation history.
    """
    try:
        kill_switch = get_kill_switch()
        status = kill_switch.get_status()
        
        return jsonify({
            'is_active': status['is_active'],
            'kill_file_exists': status['kill_file_exists'],
            'kill_file_path': status['kill_file_path'],
            'recent_history': status['recent_history'],
            'activation_count': kill_switch.get_activation_count()
        }), 200
        
    except Exception as e:
        logger.error(f"Error getting kill-switch status: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/emergency/kill-switch/activate', methods=['POST'])
def activate_kill_switch():
    """
    EMERGENCY: Activate kill-switch to halt all trading.
    
    No authentication required - this is an EMERGENCY endpoint.
    Can be called from anywhere when immediate halt is needed.
    
    Request body:
    {
        "reason": "Human-readable reason for activation",
        "source": "UI|CLI|MANUAL|AUTO" (optional)
    }
    """
    try:
        data = request.get_json() or {}
        reason = data.get('reason', 'Emergency activation via API')
        source = data.get('source', 'API')
        
        kill_switch = get_kill_switch()
        kill_switch.activate(reason, source)
        
        logger.critical(f"🚨 KILL SWITCH ACTIVATED via API - Reason: {reason}")
        
        return jsonify({
            'success': True,
            'message': 'Kill switch activated - all trading halted',
            'reason': reason,
            'source': source,
            'is_active': True
        }), 200
        
    except Exception as e:
        logger.error(f"Error activating kill-switch: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/emergency/kill-switch/deactivate', methods=['POST'])
@require_auth  # Deactivation requires authentication for safety
def deactivate_kill_switch():
    """
    Deactivate kill-switch (REQUIRES AUTHENTICATION).
    
    This should only be done after:
    1. Understanding why it was activated
    2. Resolving the underlying issue
    3. Verifying system integrity
    
    Request body:
    {
        "reason": "Reason for deactivation"
    }
    """
    try:
        data = request.get_json() or {}
        reason = data.get('reason', f'Deactivation by user {request.user_id}')
        
        kill_switch = get_kill_switch()
        kill_switch.deactivate(reason)
        
        logger.warning(f"🟢 Kill switch deactivated by user {request.user_id} - Reason: {reason}")
        
        return jsonify({
            'success': True,
            'message': 'Kill switch deactivated - trading can resume',
            'reason': reason,
            'is_active': False,
            'warning': 'Manual verification recommended before resuming trading'
        }), 200
        
    except Exception as e:
        logger.error(f"Error deactivating kill-switch: {e}")
        return jsonify({'error': str(e)}), 500


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

    logger.info(f"Starting NIJA Cloud API server on port {port}")
    logger.info(f"Debug mode: {debug}")

    app.run(
        host='0.0.0.0',
        port=port,
        debug=debug
    )
