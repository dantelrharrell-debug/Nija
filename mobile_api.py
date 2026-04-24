"""
NIJA Mobile API Extensions

This module extends the API server with mobile-specific functionality:
- Push notification registration
- Real-time trading updates
- Mobile-optimized responses
- Device management

SECURITY NOTE: This module requires proper authentication. All endpoints
should be protected with JWT authentication in production.
"""

import os
import logging
from typing import Optional, Dict, List
from flask import Flask, request, jsonify, Blueprint
from functools import wraps
from datetime import datetime
import json
from pathlib import Path

# Import authentication decorator from api_server
# NOTE: In production, uncomment and use require_auth decorator
# from api_server import require_auth

# Configure logging
logger = logging.getLogger(__name__)

# Create mobile API blueprint
mobile_api = Blueprint('mobile_api', __name__, url_prefix='/api/mobile')


# WARNING: In-memory storage for push tokens - NOT SUITABLE FOR PRODUCTION
# TODO: Replace with database storage (PostgreSQL, Redis, etc.)
# This will lose all data on server restart!
# Format: {user_id: [{"token": str, "platform": str, "device_id": str, "registered_at": datetime}]}
push_tokens = {}


# ========================================
# Mobile Device Management
# ========================================

@mobile_api.route('/device/register', methods=['POST'])
# TODO: Add authentication in production - uncomment next line
# @require_auth
def register_device():
    """
    Register a mobile device for push notifications.

    SECURITY WARNING: This endpoint currently lacks authentication.
    In production, this MUST be protected with JWT authentication
    to prevent unauthorized device registration.

    Request body:
        {
            "user_id": "user123",
            "push_token": "fcm_token_here",
            "platform": "ios" | "android",
            "device_id": "unique_device_id",
            "device_info": {
                "model": "iPhone 14 Pro",
                "os_version": "17.0",
                "app_version": "1.0.0"
            }
        }
    """
    data = request.get_json()

    if not data:
        return jsonify({'error': 'Request body is required'}), 400

    required_fields = ['user_id', 'push_token', 'platform', 'device_id']
    for field in required_fields:
        if field not in data:
            return jsonify({'error': f'Missing required field: {field}'}), 400

    user_id = data['user_id']

    # TODO: In production, verify user_id matches authenticated user
    # if request.user_id != user_id:
    #     return jsonify({'error': 'Unauthorized'}), 403
    push_token = data['push_token']
    platform = data['platform']
    device_id = data['device_id']
    device_info = data.get('device_info', {})

    # Validate platform
    if platform not in ['ios', 'android']:
        return jsonify({'error': 'Invalid platform. Must be ios or android'}), 400

    # Store push token
    if user_id not in push_tokens:
        push_tokens[user_id] = []

    # Check if device already registered
    existing_device = None
    for device in push_tokens[user_id]:
        if device['device_id'] == device_id:
            existing_device = device
            break

    if existing_device:
        # Update existing device
        existing_device['push_token'] = push_token
        existing_device['platform'] = platform
        existing_device['device_info'] = device_info
        existing_device['updated_at'] = datetime.utcnow()
        logger.info(f"Updated device registration for user {user_id}, device {device_id}")
    else:
        # Add new device
        push_tokens[user_id].append({
            'push_token': push_token,
            'platform': platform,
            'device_id': device_id,
            'device_info': device_info,
            'registered_at': datetime.utcnow(),
            'updated_at': datetime.utcnow()
        })
        logger.info(f"Registered new device for user {user_id}: {device_id} ({platform})")

    return jsonify({
        'success': True,
        'message': 'Device registered successfully',
        'device_id': device_id,
        'platform': platform
    })


@mobile_api.route('/device/unregister', methods=['POST'])
# TODO: Add authentication in production - uncomment next line
# @require_auth
def unregister_device():
    """
    Unregister a mobile device.

    SECURITY WARNING: Requires authentication in production.

    Request body:
        {
            "user_id": "user123",
            "device_id": "unique_device_id"
        }
    """
    data = request.get_json()

    if not data or 'user_id' not in data or 'device_id' not in data:
        return jsonify({'error': 'user_id and device_id are required'}), 400

    user_id = data['user_id']

    # TODO: In production, verify user_id matches authenticated user
    # if request.user_id != user_id:
    #     return jsonify({'error': 'Unauthorized'}), 403
    device_id = data['device_id']

    if user_id not in push_tokens:
        return jsonify({'error': 'User not found'}), 404

    # Remove device
    push_tokens[user_id] = [d for d in push_tokens[user_id] if d['device_id'] != device_id]

    logger.info(f"Unregistered device for user {user_id}: {device_id}")

    return jsonify({
        'success': True,
        'message': 'Device unregistered successfully'
    })


@mobile_api.route('/device/list', methods=['GET'])
def list_devices():
    """
    List all registered devices for a user.

    Query params:
        user_id: User identifier
    """
    user_id = request.args.get('user_id')

    if not user_id:
        return jsonify({'error': 'user_id is required'}), 400

    devices = push_tokens.get(user_id, [])

    # Return sanitized device list (without push tokens)
    sanitized_devices = [
        {
            'device_id': d['device_id'],
            'platform': d['platform'],
            'device_info': d['device_info'],
            'registered_at': d['registered_at'].isoformat(),
            'updated_at': d['updated_at'].isoformat()
        }
        for d in devices
    ]

    return jsonify({
        'success': True,
        'devices': sanitized_devices,
        'count': len(sanitized_devices)
    })


# ========================================
# Push Notification Management
# ========================================

def send_push_notification(user_id: str, title: str, body: str, data: Optional[Dict] = None):
    """
    Send push notification to all devices registered for a user.

    PLACEHOLDER IMPLEMENTATION: This function does not actually send notifications.
    It requires Firebase Admin SDK (Android) or APNs (iOS) to be configured.

    Args:
        user_id: User identifier
        title: Notification title
        body: Notification body
        data: Additional data payload

    Returns:
        False: Always returns False as this is not yet implemented

    TODO: Implement actual push notification sending:
        - Set up Firebase Admin SDK for Android (FCM)
        - Set up APNs for iOS
        - Handle notification delivery status
        - Implement retry logic
    """
    if user_id not in push_tokens:
        logger.warning(f"No devices registered for user {user_id}")
        return False

    devices = push_tokens[user_id]

    for device in devices:
        try:
            if device['platform'] == 'android':
                # TODO: Send via Firebase Cloud Messaging (FCM)
                # Example:
                # from firebase_admin import messaging
                # message = messaging.Message(
                #     notification=messaging.Notification(title=title, body=body),
                #     data=data or {},
                #     token=device['push_token']
                # )
                # response = messaging.send(message)
                logger.info(f"[PLACEHOLDER] Would send FCM notification to device {device['device_id']}: {title}")
            elif device['platform'] == 'ios':
                # TODO: Send via Apple Push Notification service (APNs)
                # Requires APNs certificate and connection setup
                logger.info(f"[PLACEHOLDER] Would send APNs notification to device {device['device_id']}: {title}")
        except Exception as e:
            logger.error(f"Error in notification placeholder for device {device['device_id']}: {e}")

    # Return False to indicate notifications were not actually sent
    return False


@mobile_api.route('/notifications/send', methods=['POST'])
# TODO: Add ADMIN authentication in production - this should be admin-only
# @require_admin_auth
def send_notification():
    """
    Send a push notification to a user.

    SECURITY WARNING: This endpoint should be protected with admin-level
    authentication in production to prevent abuse. Regular users should
    NOT be able to send notifications to other users.

    This endpoint is intended for:
    - Internal system notifications
    - Admin-triggered alerts
    - Automated trading notifications from the backend

    Request body:
        {
            "user_id": "user123",
            "title": "Trade Executed",
            "body": "BTC/USD long position opened at $45,000",
            "data": {
                "type": "trade_execution",
                "trade_id": "trade_123"
            }
        }
    """
    data = request.get_json()

    if not data:
        return jsonify({'error': 'Request body is required'}), 400

    required_fields = ['user_id', 'title', 'body']
    for field in required_fields:
        if field not in data:
            return jsonify({'error': f'Missing required field: {field}'}), 400

    user_id = data['user_id']
    title = data['title']
    body = data['body']
    notification_data = data.get('data', {})

    success = send_push_notification(user_id, title, body, notification_data)

    if success:
        return jsonify({
            'success': True,
            'message': 'Notification sent successfully'
        })
    else:
        return jsonify({
            'success': False,
            'message': 'Push notification system not yet implemented or no devices registered',
            'note': 'See mobile_api.py send_push_notification() for implementation details'
        }), 501  # 501 Not Implemented


# ========================================
# Mobile-Optimized Endpoints
# ========================================

@mobile_api.route('/dashboard/summary', methods=['GET'])
def get_dashboard_summary():
    """
    Get mobile-optimized dashboard summary.

    Query params:
        user_id: User identifier

    Returns:
        Lightweight summary optimized for mobile display
    """
    user_id = request.args.get('user_id')

    if not user_id:
        return jsonify({'error': 'user_id is required'}), 400

    # TODO: Fetch actual user data
    # For now, return mock data

    return jsonify({
        'success': True,
        'data': {
            'user_id': user_id,
            'trading_active': False,
            'stats': {
                'total_pnl': 0.0,
                'win_rate': 0.0,
                'total_trades': 0,
                'active_positions': 0
            },
            'account': {
                'balance': 0.0,
                'tier': 'basic',
                'max_position_size': 100.0
            },
            'last_updated': datetime.utcnow().isoformat()
        }
    })


@mobile_api.route('/trading/quick-toggle', methods=['POST'])
# TODO: Add authentication in production - uncomment next line
# @require_auth
def quick_toggle_trading():
    """
    Quick toggle trading on/off (mobile-optimized).

    SECURITY WARNING: This endpoint currently lacks authentication.
    In production, this MUST be protected to prevent unauthorized
    users from controlling other users' trading.

    Request body:
        {
            "user_id": "user123",
            "enabled": true | false
        }
    """
    data = request.get_json()

    if not data or 'user_id' not in data or 'enabled' not in data:
        return jsonify({'error': 'user_id and enabled are required'}), 400

    user_id = data['user_id']
    enabled = data['enabled']

    # TODO: In production, verify user_id matches authenticated user
    # if request.user_id != user_id:
    #     return jsonify({'error': 'Unauthorized: Cannot control other users\' trading'}), 403

    # TODO: Implement actual trading toggle
    # For now, return success

    status_text = "enabled" if enabled else "disabled"
    logger.info(f"Trading {status_text} for user {user_id}")

    # Send push notification
    if enabled:
        send_push_notification(
            user_id,
            "Trading Enabled",
            "NIJA is now actively monitoring markets and executing trades",
            {"type": "trading_status", "enabled": True}
        )
    else:
        send_push_notification(
            user_id,
            "Trading Disabled",
            "NIJA has stopped monitoring markets",
            {"type": "trading_status", "enabled": False}
        )

    return jsonify({
        'success': True,
        'trading_enabled': enabled,
        'message': f'Trading {status_text} successfully'
    })


@mobile_api.route('/positions/lightweight', methods=['GET'])
def get_lightweight_positions():
    """
    Get lightweight position data optimized for mobile.

    Query params:
        user_id: User identifier

    Returns:
        Minimal position data for quick loading
    """
    user_id = request.args.get('user_id')

    if not user_id:
        return jsonify({'error': 'user_id is required'}), 400

    # TODO: Fetch actual positions
    # For now, return empty array

    return jsonify({
        'success': True,
        'positions': [],
        'count': 0,
        'last_updated': datetime.utcnow().isoformat()
    })


@mobile_api.route('/trades/recent', methods=['GET'])
# TODO: Add authentication in production
# @require_auth
def get_recent_trades():
    """
    Get recent trades optimized for mobile display.

    SECURITY WARNING: Requires authentication in production.

    Query params:
        user_id: User identifier
        limit: Number of trades to return (default: 10, max: 50)
    """
    user_id = request.args.get('user_id')
    limit = request.args.get('limit', '10')

    if not user_id:
        return jsonify({'error': 'user_id is required'}), 400

    # TODO: In production, verify user_id matches authenticated user
    # if request.user_id != user_id:
    #     return jsonify({'error': 'Unauthorized'}), 403

    # Validate and sanitize limit parameter
    try:
        limit = int(limit)
        if limit < 1 or limit > 50:
            return jsonify({
                'error': f'Invalid limit: {limit}. Must be between 1 and 50'
            }), 400
    except ValueError:
        return jsonify({
            'error': f'Invalid limit: {limit}. Must be an integer'
        }), 400

    # TODO: Fetch actual trades
    # For now, return empty array

    return jsonify({
        'success': True,
        'trades': [],
        'count': 0,
        'limit': limit,
        'last_updated': datetime.utcnow().isoformat()
    })


# ========================================
# App Configuration
# ========================================

@mobile_api.route('/config', methods=['GET'])
def get_mobile_config():
    """
    Get mobile app configuration.

    Returns:
        Configuration settings for the mobile app
    """
    return jsonify({
        'success': True,
        'config': {
            'api_version': '1.0.0',
            'min_app_version': '1.0.0',
            'features': {
                'push_notifications': True,
                'biometric_auth': True,
                'real_time_updates': True,
                'multi_exchange': True
            },
            'refresh_intervals': {
                'dashboard': 30,  # seconds
                'positions': 10,  # seconds
                'trades': 60  # seconds
            },
            'supported_exchanges': [
                'coinbase',
                'kraken',
                'binance',
                'okx',
                'alpaca'
            ],
            'subscription_tiers': {
                'basic': {
                    'name': 'Basic',
                    'max_position_size': 100,
                    'features': ['basic_trading', 'mobile_app']
                },
                'pro': {
                    'name': 'Pro',
                    'max_position_size': 1000,
                    'features': ['basic_trading', 'mobile_app', 'advanced_charts', 'api_access']
                },
                'enterprise': {
                    'name': 'Enterprise',
                    'max_position_size': 10000,
                    'features': ['basic_trading', 'mobile_app', 'advanced_charts', 'api_access', 'priority_support', 'custom_strategies']
                }
            }
        }
    })


# ========================================
# Mobile Simulation & Education Mode
# ========================================

@mobile_api.route('/simulation/dashboard', methods=['GET'])
# @require_auth
def get_simulation_dashboard():
    """
    Get simulation dashboard optimized for mobile display.
    
    Returns key metrics and performance data for education mode.
    Mobile-optimized with smaller payloads and formatted data.
    """
    try:
        results_path = Path('/home/runner/work/Nija/Nija/results/demo_backtest.json')
        
        if not results_path.exists():
            # Return default education mode state
            return jsonify({
                'mode': 'education',
                'balance': 10000.0,
                'status': 'ready',
                'message': 'Start trading to see results'
            }), 200
        
        with open(results_path, 'r') as f:
            results = json.load(f)
        
        summary = results.get('summary', {})
        
        # Mobile-optimized response with key metrics
        response = {
            'mode': 'education',
            'balance': {
                'initial': summary.get('initial_balance', 10000.0),
                'current': summary.get('final_balance', 10000.0),
                'pnl': summary.get('total_pnl', 0.0),
                'pnl_pct': summary.get('total_return_pct', 0.0)
            },
            'performance': {
                'total_trades': summary.get('total_trades', 0),
                'win_rate': round(summary.get('win_rate', 0.0) * 100, 1),
                'profit_factor': round(summary.get('profit_factor', 0.0), 2),
                'sharpe_ratio': round(summary.get('sharpe_ratio', 0.0), 2)
            },
            'risk': {
                'max_drawdown': summary.get('max_drawdown', 0.0),
                'max_drawdown_pct': round(summary.get('max_drawdown_pct', 0.0), 2)
            },
            'recent_trades': summary.get('total_trades', 0),
            'timestamp': datetime.utcnow().isoformat()
        }
        
        return jsonify(response), 200
        
    except Exception as e:
        logger.error(f"Error retrieving simulation dashboard: {e}")
        return jsonify({
            'error': 'Failed to load simulation data',
            'mode': 'education',
            'balance': {'initial': 10000.0, 'current': 10000.0}
        }), 500


@mobile_api.route('/simulation/trades/recent', methods=['GET'])
# @require_auth
def get_recent_simulation_trades():
    """
    Get recent simulation trades for mobile display.
    
    Returns last 10 trades by default, formatted for mobile UI.
    """
    try:
        limit = min(int(request.args.get('limit', 10)), 50)
        
        results_path = Path('/home/runner/work/Nija/Nija/results/demo_backtest.json')
        
        if not results_path.exists():
            return jsonify({
                'trades': [],
                'total': 0,
                'message': 'No simulation trades yet'
            }), 200
        
        with open(results_path, 'r') as f:
            results = json.load(f)
        
        all_trades = results.get('trades', [])
        
        # Get most recent trades
        recent_trades = all_trades[-limit:] if all_trades else []
        recent_trades.reverse()  # Most recent first
        
        # Format for mobile
        formatted_trades = []
        for trade in recent_trades:
            formatted_trades.append({
                'symbol': trade.get('symbol', ''),
                'side': trade.get('side', ''),
                'pnl': round(trade.get('pnl', 0.0), 2),
                'pnl_pct': round(trade.get('pnl_pct', 0.0), 2),
                'entry_time': trade.get('entry_time', ''),
                'exit_time': trade.get('exit_time', ''),
                'exit_reason': trade.get('exit_reason', ''),
                'status': 'win' if trade.get('pnl', 0) > 0 else 'loss' if trade.get('pnl', 0) < 0 else 'breakeven'
            })
        
        return jsonify({
            'trades': formatted_trades,
            'total': len(all_trades),
            'showing': len(formatted_trades)
        }), 200
        
    except Exception as e:
        logger.error(f"Error retrieving simulation trades: {e}")
        return jsonify({'error': 'Failed to load trades'}), 500


# Export helper functions
__all__ = [
    'mobile_api',
    'send_push_notification',
    'push_tokens'
]
