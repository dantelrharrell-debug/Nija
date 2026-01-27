"""
NIJA Central Monitoring Dashboard - Enhanced API

Centralized dashboard API for real-time monitoring of all trading accounts,
risk metrics, and system health across the entire NIJA platform.

Features:
- Real-time account monitoring
- Global risk metrics visualization
- WebSocket support for live updates
- Alert management
- System health checks
- Performance analytics

Author: NIJA Trading Systems
Version: 2.0
Date: January 27, 2026
"""

import logging
import json
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
from flask import Flask, jsonify, request, Response
from flask_cors import CORS
import threading
import time

# Import global risk engine
try:
    from core.global_risk_engine import get_global_risk_engine, RiskLevel, RiskEventType
    RISK_ENGINE_AVAILABLE = True
except ImportError:
    RISK_ENGINE_AVAILABLE = False
    logging.warning("Global Risk Engine not available - limited functionality")

# Import existing monitoring system
try:
    from bot.monitoring_system import MonitoringSystem
    MONITORING_SYSTEM_AVAILABLE = True
except ImportError:
    MONITORING_SYSTEM_AVAILABLE = False
    logging.warning("Monitoring System not available")

logger = logging.getLogger(__name__)

app = Flask(__name__)
CORS(app)  # Enable CORS for frontend access

# Global state
_dashboard_state = {
    'accounts': {},
    'portfolio_metrics': {},
    'risk_events': [],
    'system_health': {},
    'last_update': None
}
_state_lock = threading.Lock()


class DashboardUpdateThread(threading.Thread):
    """Background thread for updating dashboard metrics"""
    
    def __init__(self, update_interval: int = 5):
        super().__init__(daemon=True)
        self.update_interval = update_interval
        self.running = False
        
    def run(self):
        """Run the update loop"""
        self.running = True
        logger.info(f"Dashboard update thread started (interval: {self.update_interval}s)")
        
        while self.running:
            try:
                self._update_metrics()
            except Exception as e:
                logger.error(f"Error updating dashboard metrics: {e}")
            
            time.sleep(self.update_interval)
    
    def stop(self):
        """Stop the update thread"""
        self.running = False
        logger.info("Dashboard update thread stopped")
    
    def _update_metrics(self):
        """Update all dashboard metrics"""
        global _dashboard_state
        
        metrics = {}
        
        # Get risk engine metrics
        if RISK_ENGINE_AVAILABLE:
            try:
                risk_engine = get_global_risk_engine()
                status = risk_engine.get_status_summary()
                
                metrics['portfolio'] = status.get('portfolio_metrics', {})
                metrics['risk_events'] = status.get('recent_events', [])
                metrics['accounts'] = status.get('accounts', {})
                
            except Exception as e:
                logger.error(f"Error getting risk engine metrics: {e}")
        
        # Get system health
        try:
            metrics['system_health'] = self._get_system_health()
        except Exception as e:
            logger.error(f"Error getting system health: {e}")
            metrics['system_health'] = {}
        
        # Update global state
        with _state_lock:
            _dashboard_state.update(metrics)
            _dashboard_state['last_update'] = datetime.now().isoformat()
    
    def _get_system_health(self) -> Dict[str, Any]:
        """Get system health metrics"""
        try:
            import psutil
            
            return {
                'cpu_percent': psutil.cpu_percent(interval=1),
                'memory_percent': psutil.virtual_memory().percent,
                'disk_percent': psutil.disk_usage('/').percent,
                'timestamp': datetime.now().isoformat()
            }
        except ImportError:
            # psutil not available
            return {
                'cpu_percent': 0.0,
                'memory_percent': 0.0,
                'disk_percent': 0.0,
                'timestamp': datetime.now().isoformat(),
                'note': 'psutil not available'
            }


# Start background update thread
_update_thread = None


def start_dashboard_updates(interval: int = 5):
    """Start dashboard background updates"""
    global _update_thread
    
    if _update_thread is None or not _update_thread.is_alive():
        _update_thread = DashboardUpdateThread(update_interval=interval)
        _update_thread.start()
        logger.info("Dashboard updates started")


def stop_dashboard_updates():
    """Stop dashboard background updates"""
    global _update_thread
    
    if _update_thread and _update_thread.running:
        _update_thread.stop()
        logger.info("Dashboard updates stopped")


# API Routes

@app.route('/api/health', methods=['GET'])
def health_check():
    """Health check endpoint"""
    return jsonify({
        'status': 'healthy',
        'timestamp': datetime.now().isoformat(),
        'services': {
            'risk_engine': RISK_ENGINE_AVAILABLE,
            'monitoring_system': MONITORING_SYSTEM_AVAILABLE
        }
    })


@app.route('/api/dashboard/overview', methods=['GET'])
def get_dashboard_overview():
    """
    Get dashboard overview with all metrics
    
    Returns comprehensive dashboard data including:
    - Portfolio metrics
    - Account summaries
    - Recent risk events
    - System health
    """
    with _state_lock:
        return jsonify({
            'success': True,
            'data': _dashboard_state,
            'timestamp': datetime.now().isoformat()
        })


@app.route('/api/portfolio/metrics', methods=['GET'])
def get_portfolio_metrics():
    """Get portfolio-level risk metrics"""
    if not RISK_ENGINE_AVAILABLE:
        return jsonify({
            'success': False,
            'error': 'Risk engine not available'
        }), 503
    
    try:
        risk_engine = get_global_risk_engine()
        portfolio = risk_engine.calculate_portfolio_metrics()
        
        return jsonify({
            'success': True,
            'data': portfolio.to_dict(),
            'timestamp': datetime.now().isoformat()
        })
    except Exception as e:
        logger.error(f"Error getting portfolio metrics: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@app.route('/api/accounts', methods=['GET'])
def get_accounts():
    """Get all account summaries"""
    with _state_lock:
        accounts = _dashboard_state.get('accounts', {})
    
    return jsonify({
        'success': True,
        'data': {
            'count': len(accounts),
            'accounts': accounts
        },
        'timestamp': datetime.now().isoformat()
    })


@app.route('/api/accounts/<account_id>', methods=['GET'])
def get_account_details(account_id: str):
    """Get detailed metrics for a specific account"""
    if not RISK_ENGINE_AVAILABLE:
        return jsonify({
            'success': False,
            'error': 'Risk engine not available'
        }), 503
    
    try:
        risk_engine = get_global_risk_engine()
        metrics = risk_engine.get_account_metrics(account_id)
        
        if metrics is None:
            return jsonify({
                'success': False,
                'error': f'Account {account_id} not found'
            }), 404
        
        return jsonify({
            'success': True,
            'data': metrics.to_dict(),
            'timestamp': datetime.now().isoformat()
        })
    except Exception as e:
        logger.error(f"Error getting account details: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@app.route('/api/risk/events', methods=['GET'])
def get_risk_events():
    """
    Get risk events with optional filtering
    
    Query parameters:
    - account_id: Filter by account
    - risk_level: Filter by risk level (LOW, MODERATE, HIGH, CRITICAL, EMERGENCY)
    - event_type: Filter by event type
    - hours: Number of hours to look back (default: 24)
    """
    if not RISK_ENGINE_AVAILABLE:
        return jsonify({
            'success': False,
            'error': 'Risk engine not available'
        }), 503
    
    try:
        # Parse query parameters
        account_id = request.args.get('account_id')
        risk_level_str = request.args.get('risk_level')
        event_type_str = request.args.get('event_type')
        hours = int(request.args.get('hours', 24))
        
        # Convert string parameters to enums
        risk_level = None
        if risk_level_str:
            try:
                risk_level = RiskLevel[risk_level_str]
            except KeyError:
                return jsonify({
                    'success': False,
                    'error': f'Invalid risk level: {risk_level_str}'
                }), 400
        
        event_type = None
        if event_type_str:
            try:
                event_type = RiskEventType[event_type_str]
            except KeyError:
                return jsonify({
                    'success': False,
                    'error': f'Invalid event type: {event_type_str}'
                }), 400
        
        # Get events from risk engine
        risk_engine = get_global_risk_engine()
        events = risk_engine.get_risk_events(
            account_id=account_id,
            event_type=event_type,
            risk_level=risk_level,
            hours=hours
        )
        
        return jsonify({
            'success': True,
            'data': {
                'count': len(events),
                'events': [e.to_dict() for e in events]
            },
            'filters': {
                'account_id': account_id,
                'risk_level': risk_level_str,
                'event_type': event_type_str,
                'hours': hours
            },
            'timestamp': datetime.now().isoformat()
        })
    except Exception as e:
        logger.error(f"Error getting risk events: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@app.route('/api/risk/status', methods=['GET'])
def get_risk_status():
    """Get comprehensive risk status summary"""
    if not RISK_ENGINE_AVAILABLE:
        return jsonify({
            'success': False,
            'error': 'Risk engine not available'
        }), 503
    
    try:
        risk_engine = get_global_risk_engine()
        status = risk_engine.get_status_summary()
        
        return jsonify({
            'success': True,
            'data': status,
            'timestamp': datetime.now().isoformat()
        })
    except Exception as e:
        logger.error(f"Error getting risk status: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@app.route('/api/risk/check-position', methods=['POST'])
def check_position():
    """
    Check if a new position can be opened
    
    Request body:
    {
        "account_id": "account_1",
        "position_size": 1000.0
    }
    """
    if not RISK_ENGINE_AVAILABLE:
        return jsonify({
            'success': False,
            'error': 'Risk engine not available'
        }), 503
    
    try:
        data = request.get_json()
        
        if not data or 'account_id' not in data or 'position_size' not in data:
            return jsonify({
                'success': False,
                'error': 'Missing required fields: account_id, position_size'
            }), 400
        
        account_id = data['account_id']
        position_size = float(data['position_size'])
        
        risk_engine = get_global_risk_engine()
        allowed, reason = risk_engine.can_open_position(account_id, position_size)
        
        return jsonify({
            'success': True,
            'data': {
                'allowed': allowed,
                'reason': reason,
                'account_id': account_id,
                'position_size': position_size
            },
            'timestamp': datetime.now().isoformat()
        })
    except Exception as e:
        logger.error(f"Error checking position: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@app.route('/api/system/health', methods=['GET'])
def get_system_health():
    """Get system health metrics"""
    with _state_lock:
        health = _dashboard_state.get('system_health', {})
    
    return jsonify({
        'success': True,
        'data': health,
        'timestamp': datetime.now().isoformat()
    })


@app.route('/api/metrics/stream', methods=['GET'])
def stream_metrics():
    """
    Server-Sent Events (SSE) endpoint for real-time metrics streaming
    
    Usage: EventSource('/api/metrics/stream')
    Note: This endpoint streams indefinitely. Clients should handle connection cleanup.
    """
    def generate():
        """Generate SSE events"""
        try:
            while True:
                with _state_lock:
                    data = {
                        'portfolio': _dashboard_state.get('portfolio', {}),
                        'system_health': _dashboard_state.get('system_health', {}),
                        'timestamp': datetime.now().isoformat()
                    }
                
                yield f"data: {json.dumps(data)}\n\n"
                time.sleep(5)  # Update every 5 seconds
        except GeneratorExit:
            # Client disconnected - cleanup
            logger.debug("SSE client disconnected")
    
    return Response(generate(), mimetype='text/event-stream')


# Startup/Shutdown hooks
# Note: Initialization is handled in create_app() function


def create_app(config: Optional[Dict[str, Any]] = None) -> Flask:
    """
    Create and configure the dashboard application
    
    Args:
        config: Optional configuration dictionary
        
    Returns:
        Configured Flask application
    """
    if config:
        app.config.update(config)
    
    # Start background updates
    start_dashboard_updates(interval=config.get('update_interval', 5) if config else 5)
    
    logger.info("Central Monitoring Dashboard initialized")
    logger.info(f"Risk Engine: {'Available' if RISK_ENGINE_AVAILABLE else 'Not Available'}")
    logger.info(f"Monitoring System: {'Available' if MONITORING_SYSTEM_AVAILABLE else 'Not Available'}")
    
    return app


if __name__ == '__main__':
    # Configure logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    # Create and run app
    app = create_app()
    
    try:
        logger.info("Starting Central Monitoring Dashboard on http://0.0.0.0:5001")
        app.run(host='0.0.0.0', port=5001, debug=False, threaded=True)
    except KeyboardInterrupt:
        logger.info("Shutting down dashboard")
        stop_dashboard_updates()
