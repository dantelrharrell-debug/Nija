"""
NIJA Founder Control Dashboard

A comprehensive dashboard for founders to monitor and control the entire NIJA platform.
Provides real-time visibility into all users, accounts, trades, and system health.

Features:
- Global risk monitoring across all accounts
- User management and onboarding oversight
- Real-time trade monitoring
- System health and performance metrics
- Emergency controls and kill switches
- Revenue and subscription analytics
- Alpha user invitation management

Author: NIJA Trading Systems
Version: 1.0
Date: January 27, 2026
"""

from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS
import logging
from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta
import threading
import time

# Import core NIJA components
from core.global_risk_engine import get_global_risk_engine, RiskLevel
from database.db_connection import init_database, get_db_session
from database.models import User, TradingInstance, Position, Trade, DailyStatistic
from cache.redis_client import init_redis, get_redis_client
from logging_system.centralized_logger import setup_centralized_logging, query_logs

logger = logging.getLogger(__name__)


class FounderDashboard:
    """
    Founder Control Dashboard

    Centralized control center for platform founders to monitor and manage
    the entire NIJA trading ecosystem.
    """

    def __init__(self, update_interval: int = 5):
        """
        Initialize Founder Dashboard

        Args:
            update_interval: Seconds between metric updates (default: 5)
        """
        self.update_interval = update_interval
        self.risk_engine = get_global_risk_engine()
        self._lock = threading.Lock()
        self._last_update = datetime.now()
        self._metrics_cache: Dict[str, Any] = {}

        # Start background updater
        self._updater_thread = threading.Thread(target=self._background_updater, daemon=True)
        self._updater_running = True
        self._updater_thread.start()

        logger.info("✅ Founder Dashboard initialized")

    def _background_updater(self) -> None:
        """Background thread to update metrics periodically"""
        while self._updater_running:
            try:
                self._update_metrics()
            except Exception as e:
                logger.error(f"Error updating dashboard metrics: {e}")
            time.sleep(self.update_interval)

    def _update_metrics(self) -> None:
        """Update dashboard metrics from database and risk engine"""
        with self._lock:
            try:
                with get_db_session() as session:
                    # User metrics
                    total_users = session.query(User).count()
                    active_users = session.query(User).filter(User.is_active == True).count()

                    # Trading instance metrics
                    active_instances = session.query(TradingInstance).filter(
                        TradingInstance.status == 'active'
                    ).count()

                    # Position metrics
                    active_positions = session.query(Position).filter(
                        Position.status == 'open'
                    ).count()

                    # Trade metrics (last 24 hours)
                    yesterday = datetime.now() - timedelta(days=1)
                    recent_trades = session.query(Trade).filter(
                        Trade.entry_time >= yesterday
                    ).count()

                    # Calculate total PnL (last 24 hours)
                    recent_pnl_sum = session.query(Trade).filter(
                        Trade.entry_time >= yesterday,
                        Trade.realized_pnl.isnot(None)
                    ).with_entities(
                        Trade.realized_pnl
                    ).all()

                    total_pnl_24h = sum(pnl[0] for pnl in recent_pnl_sum if pnl[0])

                    self._metrics_cache = {
                        'users': {
                            'total': total_users,
                            'active': active_users,
                            'inactive': total_users - active_users
                        },
                        'trading_instances': {
                            'active': active_instances
                        },
                        'positions': {
                            'active': active_positions
                        },
                        'trades_24h': {
                            'count': recent_trades,
                            'total_pnl': float(total_pnl_24h) if total_pnl_24h else 0.0
                        },
                        'last_updated': datetime.now().isoformat()
                    }

                self._last_update = datetime.now()

            except Exception as e:
                logger.error(f"Error in _update_metrics: {e}")

    def get_dashboard_overview(self) -> Dict[str, Any]:
        """
        Get complete dashboard overview

        Returns:
            Dictionary with all dashboard data
        """
        with self._lock:
            metrics = self._metrics_cache.copy()

        # Add risk engine metrics
        portfolio_metrics = self.risk_engine.calculate_portfolio_metrics()
        risk_summary = self.risk_engine.get_status_summary()

        return {
            'platform_metrics': metrics,
            'risk_metrics': {
                'portfolio': portfolio_metrics.to_dict(),
                'critical_events_24h': risk_summary['critical_events_24h'],
                'accounts_at_risk': len(risk_summary['portfolio_metrics']['accounts_at_risk'])
            },
            'timestamp': datetime.now().isoformat()
        }

    def get_all_users(self, include_inactive: bool = False) -> List[Dict[str, Any]]:
        """
        Get all users with their current status

        Args:
            include_inactive: Whether to include inactive users

        Returns:
            List of user dictionaries
        """
        with get_db_session() as session:
            query = session.query(User)
            if not include_inactive:
                query = query.filter(User.is_active == True)

            users = query.all()

            return [
                {
                    'user_id': user.user_id,
                    'email': user.email,
                    'subscription_tier': user.subscription_tier,
                    'is_active': user.is_active,
                    'created_at': user.created_at.isoformat() if user.created_at else None,
                    'last_login': user.last_login.isoformat() if user.last_login else None
                }
                for user in users
            ]

    def get_user_details(self, user_id: str) -> Optional[Dict[str, Any]]:
        """
        Get detailed information about a specific user

        Args:
            user_id: User identifier

        Returns:
            User details dictionary or None if not found
        """
        with get_db_session() as session:
            user = session.query(User).filter(User.user_id == user_id).first()
            if not user:
                return None

            # Get user's trading instances
            instances = session.query(TradingInstance).filter(
                TradingInstance.user_id == user_id
            ).all()

            # Get user's active positions
            positions = session.query(Position).filter(
                Position.user_id == user_id,
                Position.status == 'open'
            ).all()

            # Get risk metrics for user
            account_metrics = self.risk_engine.get_account_metrics(user_id)

            return {
                'user': {
                    'user_id': user.user_id,
                    'email': user.email,
                    'subscription_tier': user.subscription_tier,
                    'is_active': user.is_active,
                    'created_at': user.created_at.isoformat() if user.created_at else None,
                    'last_login': user.last_login.isoformat() if user.last_login else None
                },
                'trading_instances': [
                    {
                        'instance_id': inst.instance_id,
                        'broker': inst.broker,
                        'status': inst.status,
                        'created_at': inst.created_at.isoformat() if inst.created_at else None
                    }
                    for inst in instances
                ],
                'positions': [
                    {
                        'position_id': pos.position_id,
                        'symbol': pos.symbol,
                        'size': float(pos.size) if pos.size else 0,
                        'entry_price': float(pos.entry_price) if pos.entry_price else 0,
                        'current_price': float(pos.current_price) if pos.current_price else 0,
                        'unrealized_pnl': float(pos.unrealized_pnl) if pos.unrealized_pnl else 0
                    }
                    for pos in positions
                ],
                'risk_metrics': account_metrics.to_dict() if account_metrics else None
            }

    def get_system_health(self) -> Dict[str, Any]:
        """
        Get system health metrics

        Returns:
            Dictionary with health status
        """
        import psutil

        return {
            'cpu_percent': psutil.cpu_percent(interval=1),
            'memory_percent': psutil.virtual_memory().percent,
            'disk_percent': psutil.disk_usage('/').percent,
            'timestamp': datetime.now().isoformat()
        }

    def get_risk_events(self,
                       hours: int = 24,
                       risk_level: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Get recent risk events

        Args:
            hours: Number of hours to look back
            risk_level: Filter by risk level (optional)

        Returns:
            List of risk events
        """
        level_enum = RiskLevel[risk_level] if risk_level else None
        events = self.risk_engine.get_risk_events(
            hours=hours,
            risk_level=level_enum
        )

        return [event.to_dict() for event in events]

    def trigger_emergency_shutdown(self, reason: str) -> Dict[str, Any]:
        """
        Trigger emergency platform-wide shutdown

        Args:
            reason: Reason for shutdown

        Returns:
            Status dictionary
        """
        logger.critical(f"🚨 EMERGENCY SHUTDOWN TRIGGERED: {reason}")

        # TODO: Implement actual shutdown logic
        # - Stop all trading instances
        # - Close all positions (or set to liquidation-only mode)
        # - Notify all users
        # - Lock platform

        return {
            'status': 'shutdown_initiated',
            'reason': reason,
            'timestamp': datetime.now().isoformat()
        }

    def approve_alpha_user(self, user_id: str) -> Dict[str, Any]:
        """
        Approve an alpha user for platform access

        Args:
            user_id: User identifier

        Returns:
            Status dictionary
        """
        with get_db_session() as session:
            user = session.query(User).filter(User.user_id == user_id).first()
            if not user:
                return {'status': 'error', 'message': 'User not found'}

            user.is_active = True
            user.subscription_tier = 'alpha'
            session.commit()

            logger.info(f"✅ Alpha user approved: {user_id}")

            return {
                'status': 'approved',
                'user_id': user_id,
                'timestamp': datetime.now().isoformat()
            }

    def get_revenue_metrics(self) -> Dict[str, Any]:
        """
        Get revenue and monetization metrics

        Returns:
            Revenue metrics dictionary
        """
        with get_db_session() as session:
            # Count users by subscription tier
            tier_counts = {}
            for tier in ['free', 'basic', 'pro', 'enterprise', 'alpha']:
                count = session.query(User).filter(
                    User.subscription_tier == tier,
                    User.is_active == True
                ).count()
                tier_counts[tier] = count

            # TODO: Calculate actual revenue based on tier pricing
            # This is a placeholder
            revenue_estimate = (
                tier_counts.get('basic', 0) * 29 +
                tier_counts.get('pro', 0) * 99 +
                tier_counts.get('enterprise', 0) * 499
            )

            return {
                'users_by_tier': tier_counts,
                'monthly_recurring_revenue': revenue_estimate,
                'total_active_users': sum(tier_counts.values()),
                'timestamp': datetime.now().isoformat()
            }

    def shutdown(self) -> None:
        """Shutdown dashboard and background threads"""
        self._updater_running = False
        if self._updater_thread.is_alive():
            self._updater_thread.join(timeout=5)
        logger.info("Founder Dashboard shutdown complete")


def create_app(config: Optional[Dict[str, Any]] = None) -> Flask:
    """
    Create and configure Flask application for Founder Dashboard

    Args:
        config: Optional configuration dictionary

    Returns:
        Configured Flask application
    """
    app = Flask(__name__)
    CORS(app)

    # Initialize infrastructure
    setup_centralized_logging(log_level='INFO', enable_aggregator=True)
    init_database()
    init_redis()

    # Initialize dashboard
    update_interval = config.get('update_interval', 5) if config else 5
    dashboard = FounderDashboard(update_interval=update_interval)

    # Health check endpoint
    @app.route('/api/health', methods=['GET'])
    def health_check():
        """Health check endpoint"""
        return jsonify({'status': 'healthy', 'timestamp': datetime.now().isoformat()})

    # Dashboard overview
    @app.route('/api/founder/overview', methods=['GET'])
    def get_overview():
        """Get complete dashboard overview"""
        try:
            data = dashboard.get_dashboard_overview()
            return jsonify(data)
        except Exception as e:
            logger.error(f"Error in get_overview: {e}")
            return jsonify({'error': 'Failed to retrieve dashboard overview'}), 500

    # User management endpoints
    @app.route('/api/founder/users', methods=['GET'])
    def get_users():
        """Get all users"""
        try:
            include_inactive = request.args.get('include_inactive', 'false').lower() == 'true'
            users = dashboard.get_all_users(include_inactive=include_inactive)
            return jsonify({'users': users, 'count': len(users)})
        except Exception as e:
            logger.error(f"Error in get_users: {e}")
            return jsonify({'error': 'Failed to retrieve users'}), 500

    @app.route('/api/founder/users/<user_id>', methods=['GET'])
    def get_user(user_id: str):
        """Get specific user details"""
        try:
            user_data = dashboard.get_user_details(user_id)
            if not user_data:
                return jsonify({'error': 'User not found'}), 404
            return jsonify(user_data)
        except Exception as e:
            logger.error(f"Error in get_user: {e}")
            return jsonify({'error': 'Failed to retrieve user details'}), 500

    @app.route('/api/founder/users/<user_id>/approve', methods=['POST'])
    def approve_user(user_id: str):
        """Approve alpha user"""
        try:
            result = dashboard.approve_alpha_user(user_id)
            return jsonify(result)
        except Exception as e:
            logger.error(f"Error in approve_user: {e}")
            return jsonify({'error': 'Failed to approve user'}), 500

    # System health
    @app.route('/api/founder/health', methods=['GET'])
    def system_health():
        """Get system health metrics"""
        try:
            health = dashboard.get_system_health()
            return jsonify(health)
        except Exception as e:
            logger.error(f"Error in system_health: {e}")
            return jsonify({'error': 'Failed to retrieve system health'}), 500

    # Risk management
    @app.route('/api/founder/risk/events', methods=['GET'])
    def risk_events():
        """Get risk events"""
        try:
            hours = int(request.args.get('hours', 24))
            risk_level = request.args.get('risk_level')
            events = dashboard.get_risk_events(hours=hours, risk_level=risk_level)
            return jsonify({'events': events, 'count': len(events)})
        except Exception as e:
            logger.error(f"Error in risk_events: {e}")
            return jsonify({'error': 'Failed to retrieve risk events'}), 500

    # Emergency controls
    @app.route('/api/founder/emergency/shutdown', methods=['POST'])
    def emergency_shutdown():
        """Trigger emergency shutdown"""
        try:
            data = request.get_json()
            reason = data.get('reason', 'No reason provided')
            result = dashboard.trigger_emergency_shutdown(reason)
            return jsonify(result)
        except Exception as e:
            logger.error(f"Error in emergency_shutdown: {e}")
            return jsonify({'error': 'Failed to trigger emergency shutdown'}), 500

    # Revenue metrics
    @app.route('/api/founder/revenue', methods=['GET'])
    def revenue_metrics():
        """Get revenue metrics"""
        try:
            metrics = dashboard.get_revenue_metrics()
            return jsonify(metrics)
        except Exception as e:
            logger.error(f"Error in revenue_metrics: {e}")
            return jsonify({'error': 'Failed to retrieve revenue metrics'}), 500

    # Production observability endpoints
    @app.route('/api/founder/critical-status', methods=['GET'])
    def critical_status():
        """Get critical status (adoption failures, broker health, trading threads)"""
        try:
            from bot.health_check import get_health_manager
            health_mgr = get_health_manager()
            status = health_mgr.get_critical_status()
            return jsonify(status)
        except Exception as e:
            logger.error(f"Error in critical_status: {e}")
            return jsonify({'error': 'Failed to retrieve critical status'}), 500
    
    @app.route('/api/founder/adoption-failures', methods=['GET'])
    def adoption_failures():
        """Get adoption failure history"""
        try:
            from bot.health_check import get_health_manager
            health_mgr = get_health_manager()
            status = health_mgr.get_critical_status()
            return jsonify(status['adoption'])
        except Exception as e:
            logger.error(f"Error in adoption_failures: {e}")
            return jsonify({'error': 'Failed to retrieve adoption failures'}), 500
    
    @app.route('/api/founder/broker-health', methods=['GET'])
    def broker_health_status():
        """Get broker health status"""
        try:
            from bot.health_check import get_health_manager
            health_mgr = get_health_manager()
            status = health_mgr.get_critical_status()
            return jsonify(status['broker_health'])
        except Exception as e:
            logger.error(f"Error in broker_health_status: {e}")
            return jsonify({'error': 'Failed to retrieve broker health'}), 500
    
    @app.route('/api/founder/trading-threads', methods=['GET'])
    def trading_threads_status():
        """Get trading thread status"""
        try:
            from bot.health_check import get_health_manager
            health_mgr = get_health_manager()
            status = health_mgr.get_critical_status()
            return jsonify(status['trading_threads'])
        except Exception as e:
            logger.error(f"Error in trading_threads_status: {e}")
            return jsonify({'error': 'Failed to retrieve trading thread status'}), 500

    return app


if __name__ == '__main__':
    import os

    app = create_app({'update_interval': int(os.getenv('UPDATE_INTERVAL', '5'))})
    port = int(os.getenv('PORT', '5001'))

    logger.info(f"🚀 Starting Founder Dashboard on port {port}")
    app.run(host='0.0.0.0', port=port, debug=False)
