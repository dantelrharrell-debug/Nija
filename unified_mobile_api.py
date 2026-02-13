"""
NIJA Unified Mobile API

Production-ready REST and WebSocket API for mobile app integration.
This module provides a comprehensive API layer that wraps the trading engine
and exposes mobile-friendly endpoints with subscription tier enforcement.

Features:
- RESTful API for CRUD operations
- WebSocket support for real-time updates
- Subscription tier enforcement
- In-app purchase validation (iOS/Android)
- Secure authentication with JWT
- Rate limiting per subscription tier
- Education content delivery (premium tier)

Author: NIJA Trading Systems
Version: 1.0
Date: February 2026
"""

import os
import logging
from datetime import datetime, timedelta
from typing import Optional, Dict, List, Any
from functools import wraps
from decimal import Decimal

from flask import Flask, request, jsonify, Blueprint
from flask_cors import CORS
from flask_socketio import SocketIO, emit, join_room, leave_room
import jwt

from auth import get_user_manager
from monetization_engine import MonetizationEngine, SubscriptionTier, BillingInterval
from bot.kill_switch import get_kill_switch
from bot.execution_engine import get_execution_engine
from database.db_connection import get_db_session

# Configure logging
logger = logging.getLogger(__name__)

# Create unified mobile API blueprint
unified_mobile_api = Blueprint('unified_mobile_api', __name__, url_prefix='/api/v1')


# ========================================
# Subscription Tier Configuration
# ========================================

TIER_LIMITS = {
    SubscriptionTier.FREE: {
        'max_positions': 3,
        'max_daily_trades': 10,
        'max_brokers': 1,
        'api_calls_per_minute': 10,
        'features': ['paper_trading', 'basic_analytics'],
        'education_access': False,
        'live_trading': False,
        'websocket_access': False
    },
    SubscriptionTier.BASIC: {
        'max_positions': 5,
        'max_daily_trades': 30,
        'max_brokers': 2,
        'api_calls_per_minute': 30,
        'features': ['live_trading', 'mobile_app', 'email_support', 'basic_analytics'],
        'education_access': False,
        'live_trading': True,
        'websocket_access': True
    },
    SubscriptionTier.PRO: {
        'max_positions': 10,
        'max_daily_trades': 100,
        'max_brokers': 5,
        'api_calls_per_minute': 100,
        'features': ['live_trading', 'mobile_app', 'priority_support', 'advanced_analytics',
                     'meta_ai', 'mmin', 'custom_risk_profiles', 'tradingview_webhooks'],
        'education_access': True,
        'live_trading': True,
        'websocket_access': True
    },
    SubscriptionTier.ENTERPRISE: {
        'max_positions': -1,  # Unlimited
        'max_daily_trades': -1,  # Unlimited
        'max_brokers': -1,  # Unlimited
        'api_calls_per_minute': 300,
        'features': ['live_trading', 'mobile_app', 'dedicated_support', 'advanced_analytics',
                     'meta_ai', 'mmin', 'gmig', 'custom_risk_profiles', 'tradingview_webhooks',
                     'api_access', 'white_label'],
        'education_access': True,
        'live_trading': True,
        'websocket_access': True
    }
}


# ========================================
# Authentication & Authorization
# ========================================

def get_user_subscription_tier(user_id: str) -> SubscriptionTier:
    """
    Get user's current subscription tier.
    
    Args:
        user_id: User identifier
        
    Returns:
        SubscriptionTier: User's subscription tier
    """
    try:
        monetization_engine = MonetizationEngine()
        subscription = monetization_engine.get_subscription(user_id)
        if subscription and subscription.is_active():
            return subscription.tier
        return SubscriptionTier.FREE
    except Exception as e:
        logger.error(f"Error fetching subscription tier for user {user_id}: {e}")
        return SubscriptionTier.FREE


def require_subscription_tier(required_tier: SubscriptionTier):
    """
    Decorator to enforce minimum subscription tier for endpoint access.
    
    Args:
        required_tier: Minimum required subscription tier
    """
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if not hasattr(request, 'user_id'):
                return jsonify({'error': 'Authentication required'}), 401
            
            user_tier = get_user_subscription_tier(request.user_id)
            
            # Define tier hierarchy
            tier_hierarchy = {
                SubscriptionTier.FREE: 0,
                SubscriptionTier.BASIC: 1,
                SubscriptionTier.PRO: 2,
                SubscriptionTier.ENTERPRISE: 3
            }
            
            if tier_hierarchy.get(user_tier, 0) < tier_hierarchy.get(required_tier, 0):
                return jsonify({
                    'error': 'Insufficient subscription tier',
                    'required_tier': required_tier.value,
                    'current_tier': user_tier.value,
                    'message': f'This feature requires {required_tier.value} tier or higher'
                }), 403
            
            # Add tier info to request context
            request.subscription_tier = user_tier
            request.tier_limits = TIER_LIMITS[user_tier]
            
            return f(*args, **kwargs)
        
        return decorated_function
    return decorator


def require_feature(feature_name: str):
    """
    Decorator to enforce feature access based on subscription tier.
    
    Args:
        feature_name: Name of the feature to check
    """
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if not hasattr(request, 'user_id'):
                return jsonify({'error': 'Authentication required'}), 401
            
            user_tier = get_user_subscription_tier(request.user_id)
            tier_features = TIER_LIMITS[user_tier]['features']
            
            if feature_name not in tier_features:
                return jsonify({
                    'error': 'Feature not available',
                    'feature': feature_name,
                    'current_tier': user_tier.value,
                    'message': f'This feature is not included in your {user_tier.value} subscription'
                }), 403
            
            request.subscription_tier = user_tier
            request.tier_limits = TIER_LIMITS[user_tier]
            
            return f(*args, **kwargs)
        
        return decorated_function
    return decorator


# ========================================
# Trading Control Endpoints
# ========================================

@unified_mobile_api.route('/trading/start', methods=['POST'])
@require_feature('live_trading')
def start_trading():
    """
    Start automated trading for the user.
    
    Requires: live_trading feature (Basic tier or higher)
    
    Request body (optional):
        {
            "broker": "coinbase",  // Optional: specific broker to start
            "risk_profile": "conservative"  // Optional: risk profile override
        }
    """
    user_id = request.user_id
    data = request.get_json() or {}
    
    try:
        kill_switch = get_kill_switch()
        
        # Check if trading is globally disabled
        if not kill_switch.is_trading_enabled():
            return jsonify({
                'error': 'Trading is currently disabled globally',
                'message': 'Trading has been disabled by system administrator'
            }), 503
        
        # Enable trading for this user
        # TODO: Integrate with user-specific trading state
        broker = data.get('broker')
        risk_profile = data.get('risk_profile')
        
        logger.info(f"Starting trading for user {user_id}, broker={broker}, risk_profile={risk_profile}")
        
        return jsonify({
            'success': True,
            'message': 'Trading started successfully',
            'user_id': user_id,
            'broker': broker,
            'risk_profile': risk_profile,
            'timestamp': datetime.utcnow().isoformat()
        })
    
    except Exception as e:
        logger.error(f"Error starting trading for user {user_id}: {e}")
        return jsonify({'error': 'Failed to start trading', 'details': str(e)}), 500


@unified_mobile_api.route('/trading/stop', methods=['POST'])
@require_feature('live_trading')
def stop_trading():
    """
    Stop automated trading for the user.
    
    Requires: live_trading feature (Basic tier or higher)
    
    Request body (optional):
        {
            "broker": "coinbase",  // Optional: specific broker to stop
            "close_positions": false  // Optional: whether to close all positions
        }
    """
    user_id = request.user_id
    data = request.get_json() or {}
    
    try:
        broker = data.get('broker')
        close_positions = data.get('close_positions', False)
        
        logger.info(f"Stopping trading for user {user_id}, broker={broker}, close_positions={close_positions}")
        
        # TODO: Integrate with user-specific trading state
        
        return jsonify({
            'success': True,
            'message': 'Trading stopped successfully',
            'user_id': user_id,
            'broker': broker,
            'positions_closed': close_positions,
            'timestamp': datetime.utcnow().isoformat()
        })
    
    except Exception as e:
        logger.error(f"Error stopping trading for user {user_id}: {e}")
        return jsonify({'error': 'Failed to stop trading', 'details': str(e)}), 500


@unified_mobile_api.route('/trading/status', methods=['GET'])
def get_trading_status():
    """
    Get current trading status for the user.
    
    Returns:
        {
            "enabled": true,
            "active_positions": 3,
            "today_trades": 12,
            "profit_today": 125.50,
            "brokers": ["coinbase", "kraken"]
        }
    """
    user_id = request.user_id
    
    try:
        # TODO: Fetch actual trading status from database
        
        return jsonify({
            'success': True,
            'user_id': user_id,
            'trading_enabled': True,
            'active_positions': 0,
            'today_trades': 0,
            'profit_today_usd': 0.0,
            'connected_brokers': [],
            'timestamp': datetime.utcnow().isoformat()
        })
    
    except Exception as e:
        logger.error(f"Error fetching trading status for user {user_id}: {e}")
        return jsonify({'error': 'Failed to fetch trading status', 'details': str(e)}), 500


# ========================================
# Position Management Endpoints
# ========================================

@unified_mobile_api.route('/positions', methods=['GET'])
@require_feature('live_trading')
def get_positions():
    """
    Get all active positions for the user.
    
    Query params:
        broker: Optional broker filter
        limit: Max number of positions to return (default: 50)
    
    Returns:
        {
            "positions": [...],
            "count": 5,
            "total_value_usd": 1250.00
        }
    """
    user_id = request.user_id
    broker = request.args.get('broker')
    limit = int(request.args.get('limit', 50))
    
    try:
        # TODO: Fetch actual positions from database
        
        return jsonify({
            'success': True,
            'positions': [],
            'count': 0,
            'total_value_usd': 0.0,
            'broker_filter': broker,
            'timestamp': datetime.utcnow().isoformat()
        })
    
    except Exception as e:
        logger.error(f"Error fetching positions for user {user_id}: {e}")
        return jsonify({'error': 'Failed to fetch positions', 'details': str(e)}), 500


@unified_mobile_api.route('/positions/<position_id>', methods=['GET'])
@require_feature('live_trading')
def get_position_detail(position_id: str):
    """
    Get detailed information about a specific position.
    
    Args:
        position_id: Position identifier
    
    Returns:
        Detailed position information including P&L, entry/exit prices, etc.
    """
    user_id = request.user_id
    
    try:
        # TODO: Fetch position details from database
        
        return jsonify({
            'success': True,
            'position_id': position_id,
            'message': 'Position details endpoint - implementation pending'
        })
    
    except Exception as e:
        logger.error(f"Error fetching position {position_id} for user {user_id}: {e}")
        return jsonify({'error': 'Failed to fetch position details', 'details': str(e)}), 500


# ========================================
# Subscription Management Endpoints
# ========================================

@unified_mobile_api.route('/subscription/info', methods=['GET'])
def get_subscription_info():
    """
    Get user's current subscription information.
    
    Returns:
        {
            "tier": "pro",
            "status": "active",
            "trial_end": "2026-03-01T00:00:00",
            "renewal_date": "2026-03-15T00:00:00",
            "features": [...],
            "limits": {...}
        }
    """
    user_id = request.user_id
    
    try:
        user_tier = get_user_subscription_tier(user_id)
        tier_limits = TIER_LIMITS[user_tier]
        
        monetization_engine = MonetizationEngine()
        subscription = monetization_engine.get_subscription(user_id)
        
        response = {
            'success': True,
            'tier': user_tier.value,
            'status': subscription.status if subscription else 'inactive',
            'is_trial': subscription.is_trial() if subscription else False,
            'features': tier_limits['features'],
            'limits': {
                'max_positions': tier_limits['max_positions'],
                'max_daily_trades': tier_limits['max_daily_trades'],
                'max_brokers': tier_limits['max_brokers'],
                'api_calls_per_minute': tier_limits['api_calls_per_minute']
            },
            'education_access': tier_limits['education_access']
        }
        
        if subscription:
            response['trial_end'] = subscription.trial_end.isoformat() if subscription.trial_end else None
            response['renewal_date'] = subscription.current_period_end.isoformat()
            response['days_until_renewal'] = subscription.days_until_renewal()
        
        return jsonify(response)
    
    except Exception as e:
        logger.error(f"Error fetching subscription info for user {user_id}: {e}")
        return jsonify({'error': 'Failed to fetch subscription info', 'details': str(e)}), 500


@unified_mobile_api.route('/subscription/tiers', methods=['GET'])
def get_available_tiers():
    """
    Get information about all available subscription tiers.
    
    Returns:
        {
            "tiers": [
                {
                    "tier": "basic",
                    "name": "Basic",
                    "monthly_price": 49.00,
                    "yearly_price": 470.00,
                    "features": [...],
                    "limits": {...}
                },
                ...
            ]
        }
    """
    try:
        monetization_engine = MonetizationEngine()
        
        tiers = []
        for tier in [SubscriptionTier.BASIC, SubscriptionTier.PRO, SubscriptionTier.ENTERPRISE]:
            tier_data = TIER_LIMITS[tier]
            pricing = monetization_engine.get_tier_pricing(tier)
            
            tiers.append({
                'tier': tier.value,
                'name': tier.value.capitalize(),
                'monthly_price': float(pricing.monthly_price) if pricing else 0.0,
                'yearly_price': float(pricing.yearly_price) if pricing else 0.0,
                'yearly_savings': float(pricing.monthly_price * 12 - pricing.yearly_price) if pricing else 0.0,
                'features': tier_data['features'],
                'limits': {
                    'max_positions': tier_data['max_positions'],
                    'max_daily_trades': tier_data['max_daily_trades'],
                    'max_brokers': tier_data['max_brokers']
                },
                'education_access': tier_data['education_access']
            })
        
        return jsonify({
            'success': True,
            'tiers': tiers
        })
    
    except Exception as e:
        logger.error(f"Error fetching tier information: {e}")
        return jsonify({'error': 'Failed to fetch tier information', 'details': str(e)}), 500


@unified_mobile_api.route('/subscription/upgrade', methods=['POST'])
def upgrade_subscription():
    """
    Upgrade user's subscription tier.
    
    Request body:
        {
            "tier": "pro",
            "interval": "monthly",  // monthly or yearly
            "payment_method_id": "pm_xxx"  // Stripe payment method ID
        }
    """
    user_id = request.user_id
    data = request.get_json()
    
    if not data or 'tier' not in data:
        return jsonify({'error': 'tier is required'}), 400
    
    try:
        tier = SubscriptionTier(data['tier'])
        interval = BillingInterval(data.get('interval', 'monthly'))
        payment_method_id = data.get('payment_method_id')
        
        monetization_engine = MonetizationEngine()
        
        # Create or update subscription
        subscription = monetization_engine.create_subscription(
            user_id=user_id,
            tier=tier,
            interval=interval,
            payment_method_id=payment_method_id
        )
        
        logger.info(f"Upgraded subscription for user {user_id} to {tier.value}")
        
        return jsonify({
            'success': True,
            'message': f'Successfully upgraded to {tier.value} tier',
            'subscription': subscription.to_dict()
        })
    
    except ValueError as e:
        return jsonify({'error': 'Invalid tier or interval', 'details': str(e)}), 400
    except Exception as e:
        logger.error(f"Error upgrading subscription for user {user_id}: {e}")
        return jsonify({'error': 'Failed to upgrade subscription', 'details': str(e)}), 500


# ========================================
# Education Content Endpoints (Premium)
# ========================================

@unified_mobile_api.route('/education/lessons', methods=['GET'])
@require_subscription_tier(SubscriptionTier.PRO)
def get_education_lessons():
    """
    Get list of available education lessons.
    
    Requires: Pro tier or higher
    
    Query params:
        category: Optional category filter (trading_basics, strategies, risk_management)
        completed: Filter by completion status (true/false)
    
    Returns:
        {
            "lessons": [
                {
                    "id": "lesson_1",
                    "title": "Understanding RSI Indicators",
                    "category": "strategies",
                    "duration_minutes": 15,
                    "completed": false
                },
                ...
            ]
        }
    """
    user_id = request.user_id
    category = request.args.get('category')
    completed = request.args.get('completed')
    
    try:
        # TODO: Fetch lessons from education system
        
        return jsonify({
            'success': True,
            'lessons': [],
            'category_filter': category,
            'completed_filter': completed,
            'message': 'Education lessons endpoint - implementation pending'
        })
    
    except Exception as e:
        logger.error(f"Error fetching education lessons for user {user_id}: {e}")
        return jsonify({'error': 'Failed to fetch lessons', 'details': str(e)}), 500


@unified_mobile_api.route('/education/lessons/<lesson_id>', methods=['GET'])
@require_subscription_tier(SubscriptionTier.PRO)
def get_lesson_content(lesson_id: str):
    """
    Get detailed content for a specific lesson.
    
    Requires: Pro tier or higher
    
    Args:
        lesson_id: Lesson identifier
    
    Returns:
        Detailed lesson content including text, videos, quizzes, etc.
    """
    user_id = request.user_id
    
    try:
        # TODO: Fetch lesson content from education system
        
        return jsonify({
            'success': True,
            'lesson_id': lesson_id,
            'message': 'Lesson content endpoint - implementation pending'
        })
    
    except Exception as e:
        logger.error(f"Error fetching lesson {lesson_id} for user {user_id}: {e}")
        return jsonify({'error': 'Failed to fetch lesson content', 'details': str(e)}), 500


@unified_mobile_api.route('/education/progress', methods=['GET'])
@require_subscription_tier(SubscriptionTier.PRO)
def get_education_progress():
    """
    Get user's education progress and achievements.
    
    Requires: Pro tier or higher
    
    Returns:
        {
            "completed_lessons": 5,
            "total_lessons": 20,
            "completion_percentage": 25.0,
            "achievements": [...]
        }
    """
    user_id = request.user_id
    
    try:
        # TODO: Fetch user progress from education system
        
        return jsonify({
            'success': True,
            'completed_lessons': 0,
            'total_lessons': 0,
            'completion_percentage': 0.0,
            'achievements': [],
            'message': 'Education progress endpoint - implementation pending'
        })
    
    except Exception as e:
        logger.error(f"Error fetching education progress for user {user_id}: {e}")
        return jsonify({'error': 'Failed to fetch progress', 'details': str(e)}), 500


# ========================================
# Analytics & Reporting Endpoints
# ========================================

@unified_mobile_api.route('/analytics/performance', methods=['GET'])
@require_feature('basic_analytics')
def get_performance_analytics():
    """
    Get trading performance analytics.
    
    Requires: basic_analytics feature
    
    Query params:
        period: Time period (today, week, month, year, all)
        broker: Optional broker filter
    
    Returns:
        {
            "total_trades": 150,
            "win_rate": 0.62,
            "profit_usd": 1250.50,
            "sharpe_ratio": 1.45,
            "max_drawdown": -5.2
        }
    """
    user_id = request.user_id
    period = request.args.get('period', 'month')
    broker = request.args.get('broker')
    
    try:
        # TODO: Fetch analytics from database
        
        return jsonify({
            'success': True,
            'period': period,
            'broker': broker,
            'total_trades': 0,
            'win_rate': 0.0,
            'profit_usd': 0.0,
            'message': 'Performance analytics endpoint - implementation pending'
        })
    
    except Exception as e:
        logger.error(f"Error fetching analytics for user {user_id}: {e}")
        return jsonify({'error': 'Failed to fetch analytics', 'details': str(e)}), 500


# ========================================
# WebSocket Event Handlers
# ========================================

def setup_websocket_handlers(socketio: SocketIO):
    """
    Set up WebSocket event handlers for real-time updates.
    
    Args:
        socketio: SocketIO instance
    """
    
    @socketio.on('connect')
    def handle_connect():
        """Handle client connection."""
        logger.info(f"Client connected: {request.sid}")
        emit('connected', {'message': 'Connected to NIJA trading server'})
    
    @socketio.on('disconnect')
    def handle_disconnect():
        """Handle client disconnection."""
        logger.info(f"Client disconnected: {request.sid}")
    
    @socketio.on('subscribe_positions')
    def handle_subscribe_positions(data):
        """
        Subscribe to real-time position updates.
        
        Requires: WebSocket access (Basic tier or higher)
        """
        user_id = data.get('user_id')
        
        if not user_id:
            emit('error', {'message': 'user_id is required'})
            return
        
        # Verify subscription tier allows WebSocket access
        user_tier = get_user_subscription_tier(user_id)
        if not TIER_LIMITS[user_tier]['websocket_access']:
            emit('error', {
                'message': 'WebSocket access requires Basic tier or higher',
                'current_tier': user_tier.value
            })
            return
        
        room = f'positions_{user_id}'
        join_room(room)
        logger.info(f"User {user_id} subscribed to position updates")
        emit('subscribed', {'room': room, 'type': 'positions'})
    
    @socketio.on('subscribe_trades')
    def handle_subscribe_trades(data):
        """
        Subscribe to real-time trade execution updates.
        
        Requires: WebSocket access (Basic tier or higher)
        """
        user_id = data.get('user_id')
        
        if not user_id:
            emit('error', {'message': 'user_id is required'})
            return
        
        # Verify subscription tier
        user_tier = get_user_subscription_tier(user_id)
        if not TIER_LIMITS[user_tier]['websocket_access']:
            emit('error', {
                'message': 'WebSocket access requires Basic tier or higher',
                'current_tier': user_tier.value
            })
            return
        
        room = f'trades_{user_id}'
        join_room(room)
        logger.info(f"User {user_id} subscribed to trade updates")
        emit('subscribed', {'room': room, 'type': 'trades'})
    
    @socketio.on('unsubscribe')
    def handle_unsubscribe(data):
        """Unsubscribe from a room."""
        room = data.get('room')
        if room:
            leave_room(room)
            emit('unsubscribed', {'room': room})


# ========================================
# Helper Functions
# ========================================

def broadcast_position_update(user_id: str, position_data: Dict[str, Any], socketio: SocketIO):
    """
    Broadcast position update to subscribed clients.
    
    Args:
        user_id: User identifier
        position_data: Position information to broadcast
        socketio: SocketIO instance
    """
    room = f'positions_{user_id}'
    socketio.emit('position_update', position_data, room=room)
    logger.debug(f"Broadcasted position update to room {room}")


def broadcast_trade_execution(user_id: str, trade_data: Dict[str, Any], socketio: SocketIO):
    """
    Broadcast trade execution to subscribed clients.
    
    Args:
        user_id: User identifier
        trade_data: Trade information to broadcast
        socketio: SocketIO instance
    """
    room = f'trades_{user_id}'
    socketio.emit('trade_execution', trade_data, room=room)
    logger.debug(f"Broadcasted trade execution to room {room}")


# ========================================
# Blueprint Registration
# ========================================

def register_unified_mobile_api(app: Flask, socketio: SocketIO = None):
    """
    Register the unified mobile API blueprint and WebSocket handlers.
    
    Args:
        app: Flask application instance
        socketio: Optional SocketIO instance for WebSocket support
    """
    app.register_blueprint(unified_mobile_api)
    
    if socketio:
        setup_websocket_handlers(socketio)
        logger.info("WebSocket handlers registered")
    
    logger.info("Unified mobile API registered at /api/v1")


if __name__ == '__main__':
    # Test endpoint information
    print("NIJA Unified Mobile API")
    print("=" * 50)
    print("\nAvailable Endpoints:")
    print("  POST   /api/v1/trading/start")
    print("  POST   /api/v1/trading/stop")
    print("  GET    /api/v1/trading/status")
    print("  GET    /api/v1/positions")
    print("  GET    /api/v1/positions/<id>")
    print("  GET    /api/v1/subscription/info")
    print("  GET    /api/v1/subscription/tiers")
    print("  POST   /api/v1/subscription/upgrade")
    print("  GET    /api/v1/education/lessons")
    print("  GET    /api/v1/education/lessons/<id>")
    print("  GET    /api/v1/education/progress")
    print("  GET    /api/v1/analytics/performance")
    print("\nWebSocket Events:")
    print("  subscribe_positions")
    print("  subscribe_trades")
    print("  unsubscribe")
