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
from bot.user_rules_engine import (
    get_user_rules_engine,
    RULE_TYPE_TAKE_PROFIT,
    RULE_TYPE_STOP_LOSS,
    RULE_TYPE_TRAILING_STOP,
    RULE_TYPE_PORTFOLIO_REBALANCE,
)
import json
from pathlib import Path

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
@app.route('/healthz', methods=['GET'])
def health_check():
    """
    Liveness probe - indicates if the process is alive and not deadlocked.
    Always returns 200 OK if the process is running.
    """
    return jsonify({
        'status': 'alive',
        'timestamp': datetime.utcnow().isoformat(),
        'service': 'NIJA Cloud API',
        'version': '1.0.0'
    })


@app.route('/ready', methods=['GET'])
@app.route('/readiness', methods=['GET'])
def readiness_check():
    """
    Readiness probe - indicates if the service is ready to handle traffic.
    Returns 200 OK only if the service is properly configured and ready.
    Returns 503 Service Unavailable if not ready or configuration error.
    """
    # For API server, readiness means we can connect to required services
    # For now, we'll do basic checks
    ready = True
    errors = []
    
    # Check if required managers are available
    try:
        if api_key_manager is None:
            ready = False
            errors.append("API key manager not initialized")
        if user_manager is None:
            ready = False
            errors.append("User manager not initialized")
    except Exception as e:
        ready = False
        errors.append(f"Service initialization error: {str(e)}")
    
    status = {
        'status': 'ready' if ready else 'not_ready',
        'ready': ready,
        'timestamp': datetime.utcnow().isoformat(),
        'service': 'NIJA Cloud API',
        'version': '1.0.0'
    }
    
    if errors:
        status['errors'] = errors
    
    return jsonify(status), 200 if ready else 503


@app.route('/status', methods=['GET'])
def detailed_status():
    """Detailed status information for operators and debugging."""
    return jsonify({
        'status': 'healthy',
        'timestamp': datetime.utcnow().isoformat(),
        'service': 'NIJA Cloud API',
        'version': '1.0.0',
        'components': {
            'api_key_manager': 'available' if api_key_manager else 'unavailable',
            'user_manager': 'available' if user_manager else 'unavailable',
            'permission_validator': 'available' if permission_validator else 'unavailable'
        }
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
# Simulation & Backtest Results API
# ========================================

@app.route('/api/simulation/results', methods=['GET'])
@require_auth
def get_simulation_results():
    """
    Get backtest/simulation results.
    
    Returns the latest simulation results from the results directory.
    This allows users to view historical performance metrics.
    
    Returns:
        JSON response with simulation results or error
    """
    try:
        results_path = Path('/home/runner/work/Nija/Nija/results/demo_backtest.json')
        
        if not results_path.exists():
            return jsonify({
                'error': 'No simulation results available',
                'message': 'Run a backtest first to generate results'
            }), 404
        
        with open(results_path, 'r') as f:
            results = json.load(f)
        
        # Return summary data (full trade list can be very large)
        response = {
            'summary': results.get('summary', {}),
            'total_trades': len(results.get('trades', [])),
            'timestamp': datetime.utcnow().isoformat(),
            'source': 'demo_backtest.json'
        }
        
        return jsonify(response), 200
        
    except json.JSONDecodeError as e:
        logger.error(f"Error parsing simulation results: {e}")
        return jsonify({'error': 'Invalid simulation results format'}), 500
    except Exception as e:
        logger.error(f"Error retrieving simulation results: {e}")
        return jsonify({'error': 'Failed to retrieve simulation results'}), 500


@app.route('/api/simulation/results/trades', methods=['GET'])
@require_auth
def get_simulation_trades():
    """
    Get detailed trade history from simulation.
    
    Query parameters:
        - limit: Maximum number of trades to return (default: 50, max: 500)
        - offset: Number of trades to skip (default: 0)
    
    Returns:
        JSON response with trade details
    """
    try:
        limit = min(int(request.args.get('limit', 50)), 500)
        offset = int(request.args.get('offset', 0))
        
        results_path = Path('/home/runner/work/Nija/Nija/results/demo_backtest.json')
        
        if not results_path.exists():
            return jsonify({
                'error': 'No simulation results available'
            }), 404
        
        with open(results_path, 'r') as f:
            results = json.load(f)
        
        all_trades = results.get('trades', [])
        total_trades = len(all_trades)
        
        # Paginate trades
        trades_slice = all_trades[offset:offset + limit]
        
        response = {
            'trades': trades_slice,
            'total_trades': total_trades,
            'limit': limit,
            'offset': offset,
            'has_more': (offset + limit) < total_trades
        }
        
        return jsonify(response), 200
        
    except Exception as e:
        logger.error(f"Error retrieving simulation trades: {e}")
        return jsonify({'error': 'Failed to retrieve simulation trades'}), 500


@app.route('/api/simulation/status', methods=['GET'])
@require_auth
def get_simulation_status():
    """
    Get status of simulation/backtest system.
    
    Returns:
        JSON response with simulation system status
    """
    try:
        results_path = Path('/home/runner/work/Nija/Nija/results/demo_backtest.json')
        
        status = {
            'simulation_available': True,
            'results_available': results_path.exists(),
            'education_mode': True,
            'simulated_balance': 10000.0,
            'description': 'Paper trading with simulated funds'
        }
        
        if results_path.exists():
            # Get last modified time
            stat = results_path.stat()
            status['last_updated'] = datetime.fromtimestamp(stat.st_mtime).isoformat()
        
        return jsonify(status), 200
        
    except Exception as e:
        logger.error(f"Error retrieving simulation status: {e}")
        return jsonify({'error': 'Failed to retrieve simulation status'}), 500


# ========================================
# User Take-Profit / Stop-Loss Rules Endpoints
# ========================================

def _normalize_trigger_pct(value: float, rule_type: str) -> float:
    """
    Normalize trigger_pct to internal percentage format (1–100 scale).

    Accepts two input formats:
      - Fractional: 0.10 (= 10%), -0.10 (= -10% for stop-loss)
      - Percentage: 10.0 (= 10%)

    For stop-loss, the input may be negative (fractional) or positive (percentage).
    Returns the absolute percentage value (e.g. 10.0 for a -10% stop).
    """
    if rule_type == RULE_TYPE_STOP_LOSS:
        # Accept negative fractional (-0.10 → 10) or positive percentage (10.0 → 10)
        abs_val = abs(value)
        if 0 < abs_val <= 1.0:
            return abs_val * 100.0
        return abs_val
    else:
        # take_profit / trailing_stop: positive only
        if 0 < value <= 1.0:
            return value * 100.0
        return value


def _normalize_sell_pct(value: float) -> float:
    """
    Normalize sell_pct to internal percentage format (1–100 scale).

    Accepts:
      - Fractional: 0.25 (= 25%), 1.0 (= 100%)
      - Percentage: 25.0 (= 25%), 100.0 (= 100%)

    Raises ValueError if the normalized value is not in the range (0, 100].
    """
    normalized = value * 100.0 if 0 < value <= 1.0 else value
    if not (0 < normalized <= 100):
        raise ValueError(f"sell_pct must be between 0 and 100 (exclusive of 0), got {value}")
    return normalized


@app.route('/api/rules', methods=['GET'])
@require_auth
def list_rules():
    """
    List all active take-profit and stop-loss rules for the authenticated user.

    Optional query parameters:
        symbol (str): Filter rules to a specific trading symbol.
        type   (str): Filter by rule type ('take-profit' or 'stop-loss').

    Returns:
        JSON list of rule objects.
    """
    user_id = request.user_id
    symbol = request.args.get('symbol')
    rule_type_param = request.args.get('type')

    # Map user-friendly URL names to internal constants; also accept internal names directly
    _type_map = {
        'take-profit': RULE_TYPE_TAKE_PROFIT,
        'stop-loss': RULE_TYPE_STOP_LOSS,
        'trailing-stop': RULE_TYPE_TRAILING_STOP,
        'portfolio-rebalance': RULE_TYPE_PORTFOLIO_REBALANCE,
        RULE_TYPE_TAKE_PROFIT: RULE_TYPE_TAKE_PROFIT,
        RULE_TYPE_STOP_LOSS: RULE_TYPE_STOP_LOSS,
        RULE_TYPE_TRAILING_STOP: RULE_TYPE_TRAILING_STOP,
        RULE_TYPE_PORTFOLIO_REBALANCE: RULE_TYPE_PORTFOLIO_REBALANCE,
    }

    rule_type = None
    if rule_type_param:
        rule_type = _type_map.get(rule_type_param)
        if rule_type is None:
            return jsonify({'error': "Invalid rule type. Use: take-profit, stop-loss, trailing-stop, or portfolio-rebalance"}), 400

    engine = get_user_rules_engine()
    rules = engine.get_rules(user_id, symbol=symbol, rule_type=rule_type)

    return jsonify({
        'user_id': user_id,
        'rules': [r.to_dict() for r in rules],
        'count': len(rules),
    })


@app.route('/api/rules/take-profit', methods=['POST'])
@require_auth
def add_take_profit_rule():
    """
    Add a take-profit rule for the authenticated user.

    Request body (JSON):
        {
            "symbol":             "1INCH-USD",  // optional; omit (or null) to apply to all symbols
            "trigger_pct":        0.10,          // sell when position gains this % —
                                                 //   fractional (0.10 = +10%) or percentage (10.0 = +10%)
            "sell_pct":           0.25,          // sell this fraction/% of the position —
                                                 //   fractional (0.25 = 25%) or percentage (25.0 = 25%)
            "lock_to_stablecoin": false          // optional; when true, proceeds are flagged
                                                 //   for conversion to USDC/USDT
        }

    Example: "Sell 25% of all positions if they gain 10%."
        POST /api/rules/take-profit
        {"trigger_pct": 0.10, "sell_pct": 0.25, "symbol": null}

    Returns:
        201 with the created rule object.
    """
    user_id = request.user_id
    data = request.get_json()

    if not data:
        return jsonify({'error': 'Request body is required'}), 400

    if 'trigger_pct' not in data:
        return jsonify({'error': 'trigger_pct is required (e.g. 0.10 for +10%, or 10.0 for +10%)'}), 400
    if 'sell_pct' not in data:
        return jsonify({'error': 'sell_pct is required (e.g. 0.25 for 25%, or 25.0 for 25%)'}), 400

    try:
        trigger_pct = float(data['trigger_pct'])
        sell_pct = float(data['sell_pct'])
    except (TypeError, ValueError):
        return jsonify({'error': 'trigger_pct and sell_pct must be numeric'}), 400

    lock_to_stablecoin = bool(data.get('lock_to_stablecoin', False))
    symbol = data.get('symbol')

    # Normalize to internal percentage format (1–100 scale), then validate
    trigger_pct = _normalize_trigger_pct(trigger_pct, RULE_TYPE_TAKE_PROFIT)
    if trigger_pct <= 0:
        return jsonify({'error': 'trigger_pct must be positive (e.g. 0.10 for +10%, or 10.0 for +10%)'}), 400
    if trigger_pct > 10000:
        return jsonify({'error': 'trigger_pct is unreasonably large; check your input format'}), 400

    try:
        sell_pct = _normalize_sell_pct(sell_pct)
    except ValueError as exc:
        return jsonify({'error': str(exc)}), 400

    try:
        engine = get_user_rules_engine()
        rule = engine.add_take_profit_rule(
            user_id=user_id,
            trigger_pct=trigger_pct,
            sell_pct=sell_pct,
            symbol=symbol,
            lock_to_stablecoin=lock_to_stablecoin,
        )
    except ValueError as exc:
        return jsonify({'error': str(exc)}), 400
    except Exception as exc:
        logger.error("Failed to add take-profit rule for %s: %s", user_id, exc)
        return jsonify({'error': 'Failed to add rule'}), 500

    logger.info("Take-profit rule added: user=%s symbol=%s trigger=%.1f%% sell=%.0f%% lock_stable=%s",
                user_id, symbol or 'all', trigger_pct, sell_pct, lock_to_stablecoin)
    return jsonify({
        'message': 'Take-profit rule added successfully',
        'rule': rule.to_dict(),
    }), 201


@app.route('/api/rules/stop-loss', methods=['POST'])
@require_auth
def add_stop_loss_rule():
    """
    Add a stop-loss rule for the authenticated user.

    Request body (JSON):
        {
            "symbol":             "AI3-USD",  // optional; omit (or null) to apply to all symbols
            "trigger_pct":        -0.10,       // sell when position is down this % —
                                               //   negative fractional (-0.10 = -10%) or
                                               //   positive percentage (10.0 = -10%)
            "sell_pct":           1.0,         // sell this fraction/% of the position —
                                               //   fractional (1.0 = 100%) or percentage (100.0)
            "lock_to_stablecoin": false        // optional; when true, proceeds are flagged
                                               //   for conversion to USDC/USDT
        }

    Example: "Sell 100% of all positions if they drop 10%."
        POST /api/rules/stop-loss
        {"trigger_pct": -0.10, "sell_pct": 1.0, "symbol": null}

    Returns:
        201 with the created rule object.
    """
    user_id = request.user_id
    data = request.get_json()

    if not data:
        return jsonify({'error': 'Request body is required'}), 400

    if 'trigger_pct' not in data:
        return jsonify({'error': 'trigger_pct is required (e.g. -0.10 for -10%, or 10.0 for -10%)'}), 400
    if 'sell_pct' not in data:
        return jsonify({'error': 'sell_pct is required (e.g. 1.0 for 100%, or 100.0 for 100%)'}), 400

    try:
        trigger_pct = float(data['trigger_pct'])
        sell_pct = float(data['sell_pct'])
    except (TypeError, ValueError):
        return jsonify({'error': 'trigger_pct and sell_pct must be numeric'}), 400

    lock_to_stablecoin = bool(data.get('lock_to_stablecoin', False))
    symbol = data.get('symbol')

    # Normalize to internal positive percentage format (1–100 scale), then validate
    trigger_pct = _normalize_trigger_pct(trigger_pct, RULE_TYPE_STOP_LOSS)
    if trigger_pct <= 0:
        return jsonify({'error': 'trigger_pct must be non-zero (e.g. -0.10 or 10.0 for a 10% stop)'}), 400
    if trigger_pct > 10000:
        return jsonify({'error': 'trigger_pct is unreasonably large; check your input format'}), 400

    try:
        sell_pct = _normalize_sell_pct(sell_pct)
    except ValueError as exc:
        return jsonify({'error': str(exc)}), 400

    try:
        engine = get_user_rules_engine()
        rule = engine.add_stop_loss_rule(
            user_id=user_id,
            trigger_pct=trigger_pct,
            sell_pct=sell_pct,
            symbol=symbol,
            lock_to_stablecoin=lock_to_stablecoin,
        )
    except ValueError as exc:
        return jsonify({'error': str(exc)}), 400
    except Exception as exc:
        logger.error("Failed to add stop-loss rule for %s: %s", user_id, exc)
        return jsonify({'error': 'Failed to add rule'}), 500

    logger.info("Stop-loss rule added: user=%s symbol=%s trigger=%.1f%% sell=%.0f%% lock_stable=%s",
                user_id, symbol or 'all', trigger_pct, sell_pct, lock_to_stablecoin)
    return jsonify({
        'message': 'Stop-loss rule added successfully',
        'rule': rule.to_dict(),
    }), 201


@app.route('/api/rules/trailing-stop', methods=['POST'])
@require_auth
def add_trailing_stop_rule():
    """
    Add a trailing-stop rule for the authenticated user.

    The trailing stop tracks the highest (peak) price seen for each matching
    position.  When price drops ``trail_pct`` percent below that peak, NIJA
    sells ``sell_pct`` percent of the position.  After firing, the peak resets
    so the rule re-arms and can trigger again on a subsequent rally-then-drop.

    Request body (JSON):
        {
            "symbol":             "BTC-USD",  // optional; omit (or null) to apply to all symbols
            "trail_pct":          5.0,         // sell when price falls this % from peak (percentage)
            "sell_pct":           1.0,         // sell this fraction/% of position when triggered —
                                               //   fractional (1.0 = 100%) or percentage (100.0)
            "lock_to_stablecoin": false        // optional; when true, proceeds are flagged
                                               //   for conversion to USDC/USDT
        }

    Example: "Sell 100% of all positions if price drops 5% from the highest seen."
        POST /api/rules/trailing-stop
        {"trail_pct": 5, "sell_pct": 1.0, "symbol": null}

    Returns:
        201 with the created rule object.
    """
    user_id = request.user_id
    data = request.get_json()

    if not data:
        return jsonify({'error': 'Request body is required'}), 400

    if 'trail_pct' not in data:
        return jsonify({'error': 'trail_pct is required (e.g. 5.0 for a 5% trailing stop)'}), 400
    if 'sell_pct' not in data:
        return jsonify({'error': 'sell_pct is required (e.g. 1.0 for 100%, or 100.0 for 100%)'}), 400

    try:
        trail_pct = float(data['trail_pct'])
        sell_pct = float(data['sell_pct'])
    except (TypeError, ValueError):
        return jsonify({'error': 'trail_pct and sell_pct must be numeric'}), 400

    lock_to_stablecoin = bool(data.get('lock_to_stablecoin', False))
    symbol = data.get('symbol')

    # Normalize sell_pct to internal percentage format (1–100 scale)
    try:
        sell_pct = _normalize_sell_pct(sell_pct)
    except ValueError as exc:
        return jsonify({'error': str(exc)}), 400

    try:
        engine = get_user_rules_engine()
        rule = engine.add_trailing_stop_rule(
            user_id=user_id,
            trail_pct=trail_pct,
            sell_pct=sell_pct,
            symbol=symbol,
            lock_to_stablecoin=lock_to_stablecoin,
        )
    except ValueError as exc:
        return jsonify({'error': str(exc)}), 400
    except Exception as exc:
        logger.error("Failed to add trailing-stop rule for %s: %s", user_id, exc)
        return jsonify({'error': 'Failed to add rule'}), 500

    logger.info("Trailing-stop rule added: user=%s symbol=%s trail=%.1f%% sell=%.0f%% lock_stable=%s",
                user_id, symbol or 'all', trail_pct, sell_pct, lock_to_stablecoin)
    return jsonify({
        'message': 'Trailing-stop rule added successfully',
        'rule': rule.to_dict(),
    }), 201


@app.route('/api/rules/portfolio-rebalance', methods=['POST'])
@require_auth
def add_portfolio_rebalance_rule():
    """
    Add a portfolio-rebalance rule for the authenticated user.

    When a position's USD value exceeds ``max_portfolio_pct`` percent of the
    total open-position portfolio value, NIJA sells the excess to bring the
    position back to exactly the threshold.

    Request body (JSON):
        {
            "symbol":             "ETH-USD",  // optional; omit (or null) to apply to all symbols
            "max_portfolio_pct":  20.0,        // trim if position grows above this % of portfolio
            "lock_to_stablecoin": false        // optional; when true, proceeds are flagged
                                               //   for conversion to USDC/USDT
        }

    Example: "Trim any single holding that grows above 20% of my portfolio."
        POST /api/rules/portfolio-rebalance
        {"max_portfolio_pct": 20, "symbol": null}

    Returns:
        201 with the created rule object.
    """
    user_id = request.user_id
    data = request.get_json()

    if not data:
        return jsonify({'error': 'Request body is required'}), 400

    if 'max_portfolio_pct' not in data:
        return jsonify({'error': 'max_portfolio_pct is required (e.g. 20.0 to cap any holding at 20% of portfolio)'}), 400

    try:
        max_portfolio_pct = float(data['max_portfolio_pct'])
    except (TypeError, ValueError):
        return jsonify({'error': 'max_portfolio_pct must be numeric'}), 400

    lock_to_stablecoin = bool(data.get('lock_to_stablecoin', False))
    symbol = data.get('symbol')

    try:
        engine = get_user_rules_engine()
        rule = engine.add_portfolio_rebalance_rule(
            user_id=user_id,
            max_portfolio_pct=max_portfolio_pct,
            symbol=symbol,
            lock_to_stablecoin=lock_to_stablecoin,
        )
    except ValueError as exc:
        return jsonify({'error': str(exc)}), 400
    except Exception as exc:
        logger.error("Failed to add portfolio-rebalance rule for %s: %s", user_id, exc)
        return jsonify({'error': 'Failed to add rule'}), 500

    logger.info("Portfolio-rebalance rule added: user=%s symbol=%s max_pct=%.1f%% lock_stable=%s",
                user_id, symbol or 'all', max_portfolio_pct, lock_to_stablecoin)
    return jsonify({
        'message': 'Portfolio-rebalance rule added successfully',
        'rule': rule.to_dict(),
    }), 201


@app.route('/api/rules/<rule_id>', methods=['GET', 'DELETE'])
@require_auth
def manage_rule(rule_id: str):
    """
    Get or delete a specific rule by ID.

    GET    /api/rules/<rule_id>  — retrieve the rule details.
    DELETE /api/rules/<rule_id>  — deactivate (soft-delete) the rule.
    """
    user_id = request.user_id
    engine = get_user_rules_engine()

    if request.method == 'GET':
        rule = engine.get_rule_by_id(user_id, rule_id)
        if not rule:
            return jsonify({'error': 'Rule not found'}), 404
        return jsonify(rule.to_dict())

    elif request.method == 'DELETE':
        deleted = engine.delete_rule(user_id, rule_id)
        if not deleted:
            return jsonify({'error': 'Rule not found or already deleted'}), 404
        logger.info("Rule %s deleted by user %s", rule_id, user_id)
        return jsonify({'message': 'Rule deleted successfully', 'rule_id': rule_id})


# ========================================
# Portfolio Profit Engine Endpoints
# ========================================

def _get_ppe():
    """Return the global PortfolioProfitEngine singleton."""
    from bot.portfolio_profit_engine import get_portfolio_profit_engine
    return get_portfolio_profit_engine()


@app.route('/api/portfolio/profit', methods=['GET'])
@require_auth
def get_portfolio_profit(user_id: str):
    """
    GET /api/portfolio/profit
    Returns the current TOTAL PORTFOLIO PROFIT summary.
    """
    try:
        engine = _get_ppe()
        summary = engine.get_summary()
        return jsonify({'success': True, 'data': summary})
    except Exception as exc:
        logger.error("Error fetching portfolio profit: %s", exc)
        return jsonify({'error': str(exc)}), 500


@app.route('/api/portfolio/profit/report', methods=['GET'])
@require_auth
def get_portfolio_profit_report(user_id: str):
    """
    GET /api/portfolio/profit/report
    Returns a human-readable portfolio profit report.
    """
    try:
        engine = _get_ppe()
        report = engine.get_report()
        return jsonify({'success': True, 'report': report})
    except Exception as exc:
        logger.error("Error generating portfolio profit report: %s", exc)
        return jsonify({'error': str(exc)}), 500


@app.route('/api/portfolio/profit/trades', methods=['GET'])
@require_auth
def get_portfolio_trade_log(user_id: str):
    """
    GET /api/portfolio/profit/trades?limit=50
    Returns the most recent trade records captured by the profit engine.
    """
    try:
        limit = int(request.args.get('limit', 50))
        engine = _get_ppe()
        trades = engine.get_trade_log(limit=limit)
        return jsonify({'success': True, 'trades': trades, 'count': len(trades)})
    except Exception as exc:
        logger.error("Error fetching portfolio trade log: %s", exc)
        return jsonify({'error': str(exc)}), 500


@app.route('/api/portfolio/profit/harvest', methods=['POST'])
@require_auth
def harvest_portfolio_profit(user_id: str):
    """
    POST /api/portfolio/profit/harvest
    Body (JSON, optional): {"amount": 100.0, "note": "manual harvest"}
    Harvests (withdraws) accumulated portfolio profits.
    If "amount" is omitted, all available profit is harvested.
    """
    try:
        body = request.get_json(silent=True) or {}
        amount = body.get('amount', None)
        note = body.get('note', f'Harvested by user {user_id}')

        if amount is not None:
            amount = float(amount)
            if amount <= 0:
                return jsonify({'error': 'amount must be positive'}), 400

        engine = _get_ppe()
        harvested = engine.harvest_profits(amount=amount, note=note)
        summary = engine.get_summary()

        logger.info("Profit harvest: user=%s amount=%.2f", user_id, harvested)
        return jsonify({
            'success': True,
            'harvested_usd': harvested,
            'available_to_harvest': summary['available_to_harvest'],
            'total_harvested': summary['harvested_profit'],
        })
    except Exception as exc:
        logger.error("Error harvesting profit: %s", exc)
        return jsonify({'error': str(exc)}), 500


@app.route('/api/portfolio/profit/harvest/log', methods=['GET'])
@require_auth
def get_harvest_log(user_id: str):
    """
    GET /api/portfolio/profit/harvest/log
    Returns all harvest events for the current epoch.
    """
    try:
        engine = _get_ppe()
        log = engine.get_harvest_log()
        return jsonify({'success': True, 'harvest_log': log, 'count': len(log)})
    except Exception as exc:
        logger.error("Error fetching harvest log: %s", exc)
        return jsonify({'error': str(exc)}), 500


@app.route('/api/portfolio/reset', methods=['POST'])
@require_auth
def reset_portfolio(user_id: str):
    """
    POST /api/portfolio/reset
    Body (JSON, optional): {"new_base_capital": 5000.0}
    Resets the portfolio profit tracker, starting a new epoch.
    Returns a summary of the completed epoch.
    """
    try:
        body = request.get_json(silent=True) or {}
        new_base_capital = float(body.get('new_base_capital', 0.0))

        engine = _get_ppe()
        old_epoch_summary = engine.reset_portfolio(new_base_capital=new_base_capital)

        logger.info(
            "Portfolio reset by user=%s, new epoch=%s, base_capital=%.2f",
            user_id,
            engine.get_summary()['epoch'],
            new_base_capital,
        )
        return jsonify({
            'success': True,
            'message': 'Portfolio reset successfully. New epoch started.',
            'new_epoch': engine.get_summary()['epoch'],
            'previous_epoch_summary': old_epoch_summary,
        })
    except Exception as exc:
        logger.error("Error resetting portfolio: %s", exc)
        return jsonify({'error': str(exc)}), 500


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


# ========================================
# Self-Learning Strategy Allocator Endpoints
# ========================================

def _get_sla():
    """Return the global SelfLearningStrategyAllocator singleton."""
    from bot.self_learning_strategy_allocator import get_self_learning_allocator
    return get_self_learning_allocator()


@app.route('/api/strategy/allocations', methods=['GET'])
@require_auth
def get_strategy_allocations(user_id: str):
    """
    GET /api/strategy/allocations
    Returns current capital allocation weights for all strategies.
    """
    try:
        allocator = _get_sla()
        return jsonify({'success': True, 'allocations': allocator.get_weights()})
    except Exception as exc:
        logger.error("Error fetching strategy allocations: %s", exc)
        return jsonify({'error': str(exc)}), 500


@app.route('/api/strategy/stats', methods=['GET'])
@require_auth
def get_strategy_stats(user_id: str):
    """
    GET /api/strategy/stats?strategy=ApexTrend
    Returns performance stats. Omit query param for all strategies.
    """
    try:
        strategy = request.args.get('strategy')
        allocator = _get_sla()
        stats = allocator.get_stats(strategy=strategy)
        return jsonify({'success': True, 'stats': stats})
    except Exception as exc:
        logger.error("Error fetching strategy stats: %s", exc)
        return jsonify({'error': str(exc)}), 500


@app.route('/api/strategy/report', methods=['GET'])
@require_auth
def get_strategy_allocator_report(user_id: str):
    """
    GET /api/strategy/report
    Returns a human-readable allocation report.
    """
    try:
        allocator = _get_sla()
        return jsonify({'success': True, 'report': allocator.get_report()})
    except Exception as exc:
        logger.error("Error generating strategy report: %s", exc)
        return jsonify({'error': str(exc)}), 500


@app.route('/api/strategy/best', methods=['GET'])
@require_auth
def get_best_strategy(user_id: str):
    """
    GET /api/strategy/best
    Returns the name of the highest-weighted strategy.
    """
    try:
        allocator = _get_sla()
        best = allocator.get_best_strategy()
        weights = allocator.get_weights()
        return jsonify({
            'success': True,
            'best_strategy': best,
            'allocation': weights.get(best, 0.0) if best else 0.0,
        })
    except Exception as exc:
        logger.error("Error fetching best strategy: %s", exc)
        return jsonify({'error': str(exc)}), 500


# ========================================
# Smart Drawdown Recovery Endpoints
# ========================================

def _get_sdr():
    """Return the global SmartDrawdownRecovery singleton."""
    from bot.smart_drawdown_recovery import get_smart_drawdown_recovery
    return get_smart_drawdown_recovery()


@app.route('/api/drawdown/status', methods=['GET'])
@require_auth
def get_drawdown_status(user_id: str):
    """
    GET /api/drawdown/status
    Returns the current drawdown severity and recovery status.
    """
    try:
        engine = _get_sdr()
        status = engine.get_status()
        can_trade, reason = engine.can_trade()
        status['can_trade'] = can_trade
        status['can_trade_reason'] = reason
        return jsonify({'success': True, 'data': status})
    except Exception as exc:
        logger.error("Error fetching drawdown status: %s", exc)
        return jsonify({'error': str(exc)}), 500


@app.route('/api/drawdown/report', methods=['GET'])
@require_auth
def get_drawdown_report(user_id: str):
    """
    GET /api/drawdown/report
    Returns a human-readable drawdown recovery report.
    """
    try:
        engine = _get_sdr()
        return jsonify({'success': True, 'report': engine.get_report()})
    except Exception as exc:
        logger.error("Error generating drawdown report: %s", exc)
        return jsonify({'error': str(exc)}), 500


@app.route('/api/drawdown/guidance', methods=['GET'])
@require_auth
def get_drawdown_guidance(user_id: str):
    """
    GET /api/drawdown/guidance
    Returns current trading guidance: position-size multiplier,
    profit-lock multiplier, preferred strategies.
    """
    try:
        engine = _get_sdr()
        guidance = {
            'severity': engine.get_status()['severity'],
            'in_recovery_mode': engine.get_status()['in_recovery_mode'],
            'position_size_multiplier': engine.get_position_size_multiplier(),
            'profit_lock_multiplier': engine.get_profit_lock_multiplier(),
            'preferred_strategies': engine.get_preferred_strategies(),
        }
        can_trade, reason = engine.can_trade()
        guidance['can_trade'] = can_trade
        guidance['can_trade_reason'] = reason
        return jsonify({'success': True, 'guidance': guidance})
    except Exception as exc:
        logger.error("Error fetching drawdown guidance: %s", exc)
        return jsonify({'error': str(exc)}), 500


@app.route('/api/drawdown/capital', methods=['PUT'])
@require_auth
def update_drawdown_capital(user_id: str):
    """
    PUT /api/drawdown/capital
    Body: {"current_capital": 4850.0}
    Sync the drawdown engine with the latest account balance.
    """
    try:
        body = request.get_json(silent=True) or {}
        capital = body.get('current_capital')
        if capital is None:
            return jsonify({'error': 'current_capital is required'}), 400
        capital = float(capital)
        engine = _get_sdr()
        engine.update_capital(capital)
        status = engine.get_status()
        return jsonify({
            'success': True,
            'severity': status['severity'],
            'drawdown_pct': status['drawdown_pct'],
        })
    except Exception as exc:
        logger.error("Error updating drawdown capital: %s", exc)
        return jsonify({'error': str(exc)}), 500


# ========================================
# Capital Recycling Engine Endpoints
# ========================================

def _get_cre():
    """Return the global CapitalRecyclingEngine singleton."""
    from bot.capital_recycling_engine import get_capital_recycling_engine
    return get_capital_recycling_engine()


@app.route('/api/recycle/status', methods=['GET'])
@require_auth
def get_recycle_status(user_id: str):
    """
    GET /api/recycle/status
    Returns pool balance, cumulative deposits/claims, and last allocations.
    """
    try:
        engine = _get_cre()
        return jsonify({'success': True, 'data': engine.get_status()})
    except Exception as exc:
        logger.error("Error fetching recycle status: %s", exc)
        return jsonify({'error': str(exc)}), 500


@app.route('/api/recycle/report', methods=['GET'])
@require_auth
def get_recycle_report(user_id: str):
    """
    GET /api/recycle/report
    Returns a human-readable Capital Recycling Engine report.
    """
    try:
        engine = _get_cre()
        return jsonify({'success': True, 'report': engine.get_report()})
    except Exception as exc:
        logger.error("Error generating recycle report: %s", exc)
        return jsonify({'error': str(exc)}), 500


@app.route('/api/recycle/deposit', methods=['POST'])
@require_auth
def recycle_deposit(user_id: str):
    """
    POST /api/recycle/deposit
    Body: {"amount_usd": 250.0, "source_symbol": "BTC-USD", "regime": "BULL_TRENDING", "note": ""}
    Deposit harvested profit into the recycling pool.
    """
    try:
        body = request.get_json(silent=True) or {}
        amount = body.get('amount_usd')
        if amount is None:
            return jsonify({'error': 'amount_usd is required'}), 400
        amount = float(amount)
        if amount <= 0:
            return jsonify({'error': 'amount_usd must be positive'}), 400
        source_symbol = str(body.get('source_symbol', 'MANUAL'))
        regime = str(body.get('regime', 'UNKNOWN'))
        note = str(body.get('note', ''))
        engine = _get_cre()
        pool = engine.deposit_profit(amount, source_symbol=source_symbol, regime=regime, note=note)
        return jsonify({
            'success': True,
            'deposited_usd': round(amount, 4),
            'pool_usd': round(pool, 4),
        })
    except Exception as exc:
        logger.error("Error depositing to recycle pool: %s", exc)
        return jsonify({'error': str(exc)}), 500


@app.route('/api/recycle/allocate', methods=['GET'])
@require_auth
def recycle_allocate(user_id: str):
    """
    GET /api/recycle/allocate?regime=BULL_TRENDING
    Compute per-strategy allocations from the current pool without
    modifying the pool.
    """
    try:
        regime = request.args.get('regime', 'UNKNOWN')
        engine = _get_cre()
        allocations = engine.allocate(regime=regime)
        return jsonify({
            'success': True,
            'regime': regime,
            'pool_usd': round(engine.get_pool_balance(), 4),
            'allocations': {k: round(v, 4) for k, v in allocations.items()},
        })
    except Exception as exc:
        logger.error("Error computing recycle allocations: %s", exc)
        return jsonify({'error': str(exc)}), 500


@app.route('/api/recycle/claim', methods=['POST'])
@require_auth
def recycle_claim(user_id: str):
    """
    POST /api/recycle/claim
    Body: {"strategy": "ApexTrend", "requested_usd": 100.0,
           "regime": "BULL_TRENDING", "note": ""}
    Claim recycled capital for a strategy.
    """
    try:
        body = request.get_json(silent=True) or {}
        strategy = body.get('strategy')
        if not strategy:
            return jsonify({'error': 'strategy is required'}), 400
        requested = body.get('requested_usd')
        if requested is None:
            return jsonify({'error': 'requested_usd is required'}), 400
        requested = float(requested)
        if requested <= 0:
            return jsonify({'error': 'requested_usd must be positive'}), 400
        regime = str(body.get('regime', 'UNKNOWN'))
        note = str(body.get('note', ''))
        engine = _get_cre()
        granted = engine.claim_allocation(
            strategy=str(strategy),
            requested_usd=requested,
            regime=regime,
            note=note,
        )
        return jsonify({
            'success': True,
            'strategy': strategy,
            'requested_usd': round(requested, 4),
            'granted_usd': round(granted, 4),
            'pool_usd': round(engine.get_pool_balance(), 4),
        })
    except Exception as exc:
        logger.error("Error claiming recycle allocation: %s", exc)
        return jsonify({'error': str(exc)}), 500
