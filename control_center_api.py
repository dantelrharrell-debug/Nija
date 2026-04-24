"""
NIJA Control Center API
========================

Consolidated API for the NIJA Control Center dashboard.
Provides unified access to all trading data, metrics, and actions.

Features:
- Real-time balances and positions across all users
- Trading status and alerts
- Performance metrics and snapshots
- Quick action endpoints (pause, resume, emergency stop)
- WebSocket support for live updates

Author: NIJA Trading Systems
Version: 1.0
Date: February 7, 2026
"""

import logging
import json
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
from pathlib import Path
from flask import Flask, jsonify, request, Response
from flask_cors import CORS
import threading
import time

logger = logging.getLogger(__name__)

# Import database models
try:
    from database.db_connection import init_database, get_db_session, check_database_health
    from database.models import User, Position, BrokerCredential, Trade
    DATABASE_AVAILABLE = True
except ImportError as e:
    logger.warning(f"Database not available: {e}")
    DATABASE_AVAILABLE = False

# Import controls
try:
    from controls import get_hard_controls
    CONTROLS_AVAILABLE = True
except ImportError:
    CONTROLS_AVAILABLE = False

# Import user management
try:
    from bot.user_pnl_tracker import get_user_pnl_tracker
    PNL_TRACKER_AVAILABLE = True
except ImportError:
    PNL_TRACKER_AVAILABLE = False

try:
    from bot.user_risk_manager import get_user_risk_manager
    RISK_MANAGER_AVAILABLE = True
except ImportError:
    RISK_MANAGER_AVAILABLE = False

# Import command center metrics
try:
    from bot.command_center_metrics import get_command_center_metrics
    COMMAND_CENTER_AVAILABLE = True
except ImportError:
    COMMAND_CENTER_AVAILABLE = False


class ControlCenterState:
    """Manages control center state"""
    
    def __init__(self):
        self.alerts = []
        self.max_alerts = 100
        self.alert_file = Path("/tmp/nija_control_center_alerts.json")
        self.load_alerts()
    
    def add_alert(self, severity: str, message: str, source: str = "system"):
        """Add a new alert"""
        alert = {
            'id': len(self.alerts) + 1,
            'timestamp': datetime.now().isoformat(),
            'severity': severity,
            'message': message,
            'source': source,
            'acknowledged': False
        }
        
        self.alerts.insert(0, alert)  # Newest first
        
        # Keep only max_alerts
        if len(self.alerts) > self.max_alerts:
            self.alerts = self.alerts[:self.max_alerts]
        
        self.save_alerts()
        return alert
    
    def acknowledge_alert(self, alert_id: int):
        """Mark alert as acknowledged"""
        for alert in self.alerts:
            if alert['id'] == alert_id:
                alert['acknowledged'] = True
                self.save_alerts()
                return True
        return False
    
    def clear_alerts(self):
        """Clear all alerts"""
        self.alerts = []
        self.save_alerts()
    
    def get_alerts(self, limit: int = 50, unacknowledged_only: bool = False):
        """Get alerts"""
        alerts = self.alerts
        
        if unacknowledged_only:
            alerts = [a for a in alerts if not a.get('acknowledged', False)]
        
        return alerts[:limit]
    
    def save_alerts(self):
        """Save alerts to file"""
        try:
            self.alert_file.parent.mkdir(parents=True, exist_ok=True)
            with open(self.alert_file, 'w') as f:
                json.dump(self.alerts, f, indent=2)
        except Exception as e:
            logger.error(f"Error saving alerts: {e}")
    
    def load_alerts(self):
        """Load alerts from file"""
        try:
            if self.alert_file.exists():
                with open(self.alert_file, 'r') as f:
                    self.alerts = json.load(f)
        except Exception as e:
            logger.error(f"Error loading alerts: {e}")
            self.alerts = []


# Global state
_state = ControlCenterState()
_state_lock = threading.Lock()


def create_control_center_api(app: Optional[Flask] = None) -> Flask:
    """Create or configure Flask app with Control Center API"""
    
    if app is None:
        app = Flask(__name__)
        CORS(app)
    
    @app.route('/api/control-center/overview', methods=['GET'])
    def get_overview():
        """Get platform overview"""
        try:
            overview = {
                'timestamp': datetime.now().isoformat(),
                'platform': {
                    'total_users': 0,
                    'active_users': 0,
                    'total_capital': 0.0,
                    'total_positions': 0,
                    'unrealized_pnl': 0.0,
                    'daily_pnl': 0.0,
                    'trading_enabled': False,
                    'database_healthy': False
                },
                'system': {
                    'uptime': 0,
                    'memory_usage': 0,
                    'cpu_usage': 0
                }
            }
            
            if DATABASE_AVAILABLE:
                with get_db_session() as session:
                    # Get user counts
                    users = session.query(User).all()
                    overview['platform']['total_users'] = len(users)
                    overview['platform']['active_users'] = sum(1 for u in users if u.is_active)

                    # Get positions
                    positions = session.query(Position).filter(Position.is_open == True).all()
                    overview['platform']['total_positions'] = len(positions)
                    overview['platform']['unrealized_pnl'] = sum(p.unrealized_pnl or 0 for p in positions)

                    # Calculate total capital
                    for user in users:
                        if PNL_TRACKER_AVAILABLE:
                            try:
                                tracker = get_user_pnl_tracker()
                                stats = tracker.get_stats(str(user.user_id))
                                overview['platform']['total_capital'] += stats.get('total_pnl', 0.0)
                                overview['platform']['daily_pnl'] += stats.get('daily_pnl', 0.0)
                            except Exception:
                                pass

                # Check health
                overview['platform']['database_healthy'] = check_database_health()
            
            # Check trading status
            if CONTROLS_AVAILABLE:
                try:
                    controls = get_hard_controls()
                    overview['platform']['trading_enabled'] = controls.is_live_capital_verified()
                except Exception:
                    pass
            
            # System metrics
            try:
                import psutil
                overview['system']['memory_usage'] = psutil.virtual_memory().percent
                overview['system']['cpu_usage'] = psutil.cpu_percent(interval=1)
            except Exception:
                pass
            
            return jsonify({'success': True, 'data': overview})
            
        except Exception as e:
            logger.error(f"Error getting overview: {e}", exc_info=True)
            return jsonify({'success': False, 'error': str(e)}), 500
    
    @app.route('/api/control-center/users', methods=['GET'])
    def get_users():
        """Get all user summaries"""
        try:
            summaries = []
            
            if not DATABASE_AVAILABLE:
                return jsonify({'success': True, 'data': summaries})
            
            with get_db_session() as session:
                users = session.query(User).all()

                for user in users:
                    summary = {
                        'user_id': user.user_id,
                        'email': user.email or 'N/A',
                        'tier': user.subscription_tier or 'basic',
                        'is_active': user.is_active,
                        'balance': 0.0,
                        'broker_balances': {},
                        'positions': 0,
                        'unrealized_pnl': 0.0,
                        'daily_pnl': 0.0,
                        'can_trade': False,
                        'status': 'unknown',
                        'risk_level': 'unknown'
                    }

                    # Get positions
                    positions = session.query(Position).filter(
                        Position.user_id == user.user_id,
                        Position.is_open == True
                    ).all()
                    summary['positions'] = len(positions)
                    summary['unrealized_pnl'] = sum(p.unrealized_pnl or 0 for p in positions)

                    # Get broker balances
                    credentials = session.query(BrokerCredential).filter(
                        BrokerCredential.user_id == user.user_id
                    ).all()
                    summary['configured_brokers'] = [c.broker_name for c in credentials]

                    # Get PnL tracker data
                    if PNL_TRACKER_AVAILABLE:
                        try:
                            tracker = get_user_pnl_tracker()
                            stats = tracker.get_stats(str(user.user_id))
                            summary['balance'] = stats.get('total_pnl', 0.0)
                            summary['daily_pnl'] = stats.get('daily_pnl', 0.0)
                            summary['broker_balances'] = {}
                        except Exception:
                            pass

                    # Get risk status
                    if RISK_MANAGER_AVAILABLE:
                        try:
                            risk_mgr = get_user_risk_manager()
                            can_trade_result, _ = risk_mgr.can_trade(str(user.user_id), 0.0)
                            summary['can_trade'] = can_trade_result
                            state = risk_mgr.get_state(str(user.user_id))
                            summary['status'] = 'circuit_breaker' if state.circuit_breaker_triggered else 'active'
                            summary['risk_level'] = 'high' if state.circuit_breaker_triggered else 'normal'
                        except Exception:
                            pass
                
                    summaries.append(summary)
            
            return jsonify({'success': True, 'data': summaries})
            
        except Exception as e:
            logger.error(f"Error getting users: {e}", exc_info=True)
            return jsonify({'success': False, 'error': str(e)}), 500
    
    @app.route('/api/control-center/alerts', methods=['GET'])
    def get_alerts():
        """Get recent alerts"""
        try:
            limit = request.args.get('limit', default=50, type=int)
            unacknowledged_only = request.args.get('unacknowledged', default=False, type=bool)
            
            with _state_lock:
                alerts = _state.get_alerts(limit=limit, unacknowledged_only=unacknowledged_only)
            
            return jsonify({'success': True, 'data': alerts})
            
        except Exception as e:
            logger.error(f"Error getting alerts: {e}", exc_info=True)
            return jsonify({'success': False, 'error': str(e)}), 500
    
    @app.route('/api/control-center/alerts', methods=['POST'])
    def add_alert():
        """Add a new alert"""
        try:
            data = request.get_json()
            severity = data.get('severity', 'info')
            message = data.get('message', '')
            source = data.get('source', 'manual')
            
            if not message:
                return jsonify({'success': False, 'error': 'Message is required'}), 400
            
            with _state_lock:
                alert = _state.add_alert(severity, message, source)
            
            return jsonify({'success': True, 'data': alert})
            
        except Exception as e:
            logger.error(f"Error adding alert: {e}", exc_info=True)
            return jsonify({'success': False, 'error': str(e)}), 500
    
    @app.route('/api/control-center/alerts/<int:alert_id>/acknowledge', methods=['POST'])
    def acknowledge_alert(alert_id: int):
        """Acknowledge an alert"""
        try:
            with _state_lock:
                success = _state.acknowledge_alert(alert_id)
            
            if success:
                return jsonify({'success': True, 'message': 'Alert acknowledged'})
            else:
                return jsonify({'success': False, 'error': 'Alert not found'}), 404
                
        except Exception as e:
            logger.error(f"Error acknowledging alert: {e}", exc_info=True)
            return jsonify({'success': False, 'error': str(e)}), 500
    
    @app.route('/api/control-center/alerts/clear', methods=['POST'])
    def clear_alerts():
        """Clear all alerts"""
        try:
            with _state_lock:
                _state.clear_alerts()
            
            return jsonify({'success': True, 'message': 'All alerts cleared'})
            
        except Exception as e:
            logger.error(f"Error clearing alerts: {e}", exc_info=True)
            return jsonify({'success': False, 'error': str(e)}), 500
    
    @app.route('/api/control-center/positions', methods=['GET'])
    def get_positions():
        """Get all open positions"""
        try:
            positions = []
            
            if not DATABASE_AVAILABLE:
                return jsonify({'success': True, 'data': positions})
            
            with get_db_session() as session:
                # Get all open positions
                db_positions = session.query(Position).filter(Position.is_open == True).all()

                for pos in db_positions:
                    positions.append({
                        'id': pos.id,
                        'user_id': pos.user_id,
                        'symbol': pos.symbol,
                        'side': pos.side,
                        'size': float(pos.size or 0),  # type: ignore[arg-type]
                        'entry_price': float(pos.entry_price or 0),  # type: ignore[arg-type]
                        'current_price': float(pos.current_price or 0),  # type: ignore[arg-type]
                        'unrealized_pnl': float(pos.unrealized_pnl or 0),  # type: ignore[arg-type]
                        'broker': pos.broker,
                        'opened_at': pos.opened_at.isoformat() if pos.opened_at is not None else None  # type: ignore[union-attr]
                    })

            return jsonify({'success': True, 'data': positions})
            
        except Exception as e:
            logger.error(f"Error getting positions: {e}", exc_info=True)
            return jsonify({'success': False, 'error': str(e)}), 500
    
    @app.route('/api/control-center/trades/recent', methods=['GET'])
    def get_recent_trades():
        """Get recent trades"""
        try:
            limit = request.args.get('limit', default=50, type=int)
            trades = []
            
            if not DATABASE_AVAILABLE:
                return jsonify({'success': True, 'data': trades})
            
            with get_db_session() as session:
                # Get recent trades
                db_trades = session.query(Trade).order_by(
                    Trade.executed_at.desc()
                ).limit(limit).all()

                for trade in db_trades:
                    trades.append({
                        'id': trade.id,
                        'user_id': trade.user_id,
                        'symbol': trade.symbol,
                        'side': trade.side,
                        'size': float(trade.size or 0),  # type: ignore[arg-type]
                        'price': float(trade.price) if trade.price else 0,
                        'pnl': float(trade.pnl or 0),  # type: ignore[arg-type]
                        'broker': trade.broker,
                        'executed_at': trade.executed_at.isoformat() if trade.executed_at else None
                    })

            return jsonify({'success': True, 'data': trades})
            
        except Exception as e:
            logger.error(f"Error getting trades: {e}", exc_info=True)
            return jsonify({'success': False, 'error': str(e)}), 500
    
    @app.route('/api/control-center/metrics', methods=['GET'])
    def get_metrics():
        """Get performance metrics"""
        try:
            metrics = {}
            
            if COMMAND_CENTER_AVAILABLE:
                try:
                    cc_metrics = get_command_center_metrics()
                    snapshot = cc_metrics.get_snapshot()
                    metrics = {
                        'equity': {
                            'equity': snapshot.equity,
                            'equity_peak': snapshot.equity_peak,
                            'equity_change_24h': snapshot.equity_change_24h,
                            'equity_change_pct_24h': snapshot.equity_change_pct_24h,
                        },
                        'risk': {
                            'risk_heat': snapshot.risk_heat,
                            'risk_level': snapshot.risk_level,
                            'max_drawdown_pct': snapshot.max_drawdown_pct,
                            'current_drawdown_pct': snapshot.current_drawdown_pct,
                        },
                        'quality': {
                            'trade_quality_score': snapshot.trade_quality_score,
                            'trade_quality_grade': snapshot.trade_quality_grade,
                            'win_rate': snapshot.win_rate,
                            'profit_factor': snapshot.profit_factor,
                        }
                    }
                except Exception as e:
                    logger.error(f"Error getting command center metrics: {e}")
            
            return jsonify({'success': True, 'data': metrics})
            
        except Exception as e:
            logger.error(f"Error getting metrics: {e}", exc_info=True)
            return jsonify({'success': False, 'error': str(e)}), 500
    
    @app.route('/api/control-center/actions/emergency-stop', methods=['POST'])
    def emergency_stop():
        """Emergency stop all trading"""
        try:
            if not CONTROLS_AVAILABLE:
                return jsonify({
                    'success': False,
                    'error': 'Controls not available'
                }), 500
            
            controls = get_hard_controls()
            controls.trigger_global_kill_switch('Emergency stop activated via control center')

            # Add alert
            with _state_lock:
                _state.add_alert('error', 'Emergency stop activated', 'control_center')
            
            return jsonify({
                'success': True,
                'message': 'Emergency stop activated - all trading disabled'
            })
            
        except Exception as e:
            logger.error(f"Error in emergency stop: {e}", exc_info=True)
            return jsonify({'success': False, 'error': str(e)}), 500
    
    @app.route('/api/control-center/actions/pause-trading', methods=['POST'])
    def pause_trading():
        """Pause trading"""
        try:
            if not CONTROLS_AVAILABLE:
                return jsonify({
                    'success': False,
                    'error': 'Controls not available'
                }), 500
            
            controls = get_hard_controls()
            controls.trigger_global_kill_switch('Trading paused via control center')

            with _state_lock:
                _state.add_alert('warning', 'Trading paused', 'control_center')
            
            return jsonify({
                'success': True,
                'message': 'Trading paused'
            })
            
        except Exception as e:
            logger.error(f"Error pausing trading: {e}", exc_info=True)
            return jsonify({'success': False, 'error': str(e)}), 500
    
    @app.route('/api/control-center/actions/resume-trading', methods=['POST'])
    def resume_trading():
        """Resume trading"""
        try:
            if not CONTROLS_AVAILABLE:
                return jsonify({
                    'success': False,
                    'error': 'Controls not available'
                }), 500
            
            controls = get_hard_controls()
            controls.reset_global_kill_switch()

            with _state_lock:
                _state.add_alert('info', 'Trading resumed', 'control_center')
            
            return jsonify({
                'success': True,
                'message': 'Trading resumed'
            })
            
        except Exception as e:
            logger.error(f"Error resuming trading: {e}", exc_info=True)
            return jsonify({'success': False, 'error': str(e)}), 500
    
    @app.route('/api/control-center/health', methods=['GET'])
    def health_check():
        """Health check endpoint"""
        health = {
            'status': 'healthy',
            'timestamp': datetime.now().isoformat(),
            'components': {
                'database': DATABASE_AVAILABLE and check_database_health() if DATABASE_AVAILABLE else False,
                'controls': CONTROLS_AVAILABLE,
                'pnl_tracker': PNL_TRACKER_AVAILABLE,
                'risk_manager': RISK_MANAGER_AVAILABLE,
                'command_center': COMMAND_CENTER_AVAILABLE
            }
        }
        
        # Overall health
        if not all(health['components'].values()):
            health['status'] = 'degraded'
        
        return jsonify(health)
    
    return app


if __name__ == '__main__':
    # Run standalone server
    # Note: debug=False for security in production
    app = create_control_center_api()
    app.run(host='0.0.0.0', port=5002, debug=False)
