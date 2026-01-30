"""
NIJA KPI Dashboard API

RESTful API endpoints for accessing KPI dashboards, performance tracking,
and risk alarms.

Endpoints:
- GET /api/kpi/current - Current KPI snapshot
- GET /api/kpi/history - Historical KPI data
- GET /api/kpi/summary - KPI summary
- GET /api/performance/status - Performance tracker status
- GET /api/alarms/active - Active risk alarms
- GET /api/alarms/history - Alarm history
- POST /api/alarms/acknowledge - Acknowledge an alarm
- GET /api/dashboard/overview - Complete dashboard overview

Author: NIJA Trading Systems
Version: 1.0
Date: January 30, 2026
"""

import logging
from datetime import datetime
from typing import Dict, Any, Optional
from flask import Blueprint, jsonify, request
from dataclasses import asdict

try:
    from kpi_tracker import get_kpi_tracker
    from automated_performance_tracker import get_performance_tracker
    from risk_alarm_system import get_risk_alarm_system
except ImportError:
    from bot.kpi_tracker import get_kpi_tracker
    from bot.automated_performance_tracker import get_performance_tracker
    from bot.risk_alarm_system import get_risk_alarm_system

logger = logging.getLogger(__name__)

# Create Flask blueprint
kpi_dashboard_bp = Blueprint('kpi_dashboard', __name__, url_prefix='/api')


@kpi_dashboard_bp.route('/kpi/current', methods=['GET'])
def get_current_kpi():
    """
    Get current KPI snapshot
    
    Returns:
        JSON with current KPI metrics
    """
    try:
        kpi_tracker = get_kpi_tracker()
        snapshot = kpi_tracker.get_current_kpis()
        
        if snapshot is None:
            return jsonify({
                'success': False,
                'error': 'No KPI data available'
            }), 404
        
        return jsonify({
            'success': True,
            'data': asdict(snapshot)
        })
        
    except Exception as e:
        logger.error(f"Error getting current KPI: {e}", exc_info=True)
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@kpi_dashboard_bp.route('/kpi/history', methods=['GET'])
def get_kpi_history():
    """
    Get KPI history
    
    Query Parameters:
        hours: Number of hours of history (default: 24)
    
    Returns:
        JSON with historical KPI data
    """
    try:
        hours = request.args.get('hours', default=24, type=int)
        
        kpi_tracker = get_kpi_tracker()
        history = kpi_tracker.get_kpi_history(hours=hours)
        
        return jsonify({
            'success': True,
            'data': {
                'period_hours': hours,
                'data_points': len(history),
                'history': [asdict(kpi) for kpi in history]
            }
        })
        
    except Exception as e:
        logger.error(f"Error getting KPI history: {e}", exc_info=True)
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@kpi_dashboard_bp.route('/kpi/summary', methods=['GET'])
def get_kpi_summary():
    """
    Get KPI summary
    
    Returns:
        JSON with summarized KPI metrics
    """
    try:
        kpi_tracker = get_kpi_tracker()
        summary = kpi_tracker.get_kpi_summary()
        
        return jsonify({
            'success': True,
            'data': summary
        })
        
    except Exception as e:
        logger.error(f"Error getting KPI summary: {e}", exc_info=True)
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@kpi_dashboard_bp.route('/performance/status', methods=['GET'])
def get_performance_status():
    """
    Get performance tracker status
    
    Returns:
        JSON with tracker status and statistics
    """
    try:
        tracker = get_performance_tracker()
        status = tracker.get_status()
        
        return jsonify({
            'success': True,
            'data': status
        })
        
    except Exception as e:
        logger.error(f"Error getting performance status: {e}", exc_info=True)
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@kpi_dashboard_bp.route('/alarms/active', methods=['GET'])
def get_active_alarms():
    """
    Get all active risk alarms
    
    Returns:
        JSON with list of active alarms
    """
    try:
        alarm_system = get_risk_alarm_system()
        alarms = alarm_system.get_active_alarms()
        
        return jsonify({
            'success': True,
            'data': {
                'count': len(alarms),
                'alarms': [alarm.to_dict() for alarm in alarms]
            }
        })
        
    except Exception as e:
        logger.error(f"Error getting active alarms: {e}", exc_info=True)
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@kpi_dashboard_bp.route('/alarms/history', methods=['GET'])
def get_alarm_history():
    """
    Get alarm history
    
    Query Parameters:
        hours: Number of hours of history (default: 24)
    
    Returns:
        JSON with historical alarm data
    """
    try:
        hours = request.args.get('hours', default=24, type=int)
        
        alarm_system = get_risk_alarm_system()
        history = alarm_system.get_alarm_history(hours=hours)
        
        return jsonify({
            'success': True,
            'data': {
                'period_hours': hours,
                'count': len(history),
                'alarms': [alarm.to_dict() for alarm in history]
            }
        })
        
    except Exception as e:
        logger.error(f"Error getting alarm history: {e}", exc_info=True)
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@kpi_dashboard_bp.route('/dashboard/overview', methods=['GET'])
def get_dashboard_overview():
    """
    Get complete dashboard overview
    
    Combines KPI summary, performance status, and active alarms
    into a single comprehensive response.
    
    Returns:
        JSON with complete dashboard data
    """
    try:
        kpi_tracker = get_kpi_tracker()
        performance_tracker = get_performance_tracker()
        alarm_system = get_risk_alarm_system()
        
        # Get all data
        kpi_summary = kpi_tracker.get_kpi_summary()
        performance_status = performance_tracker.get_status()
        active_alarms = alarm_system.get_active_alarms()
        
        # Build comprehensive overview
        overview = {
            'timestamp': datetime.now().isoformat(),
            'kpi': kpi_summary,
            'performance_tracking': performance_status,
            'risk_alarms': {
                'active_count': len(active_alarms),
                'active_alarms': [alarm.to_dict() for alarm in active_alarms],
                'has_critical': any(a.level in ['CRITICAL', 'EMERGENCY'] for a in active_alarms),
                'has_warning': any(a.level == 'WARNING' for a in active_alarms)
            },
            'system_health': {
                'kpi_tracking': 'active' if kpi_summary.get('status') == 'active' else 'inactive',
                'performance_tracking': 'active' if performance_status.get('running') else 'inactive',
                'risk_monitoring': 'active'
            }
        }
        
        return jsonify({
            'success': True,
            'data': overview
        })
        
    except Exception as e:
        logger.error(f"Error getting dashboard overview: {e}", exc_info=True)
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@kpi_dashboard_bp.route('/health', methods=['GET'])
def health_check():
    """
    Health check endpoint
    
    Returns:
        JSON with system health status
    """
    try:
        return jsonify({
            'success': True,
            'status': 'healthy',
            'timestamp': datetime.now().isoformat(),
            'service': 'NIJA KPI Dashboard API'
        })
        
    except Exception as e:
        return jsonify({
            'success': False,
            'status': 'unhealthy',
            'error': str(e)
        }), 500


def register_kpi_dashboard_routes(app):
    """
    Register KPI dashboard routes with Flask app
    
    Args:
        app: Flask application instance
    """
    app.register_blueprint(kpi_dashboard_bp)
    logger.info("✅ KPI Dashboard API routes registered")


# Example usage with Flask
if __name__ == "__main__":
    from flask import Flask
    from flask_cors import CORS
    
    # Configure logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    # Create Flask app
    app = Flask(__name__)
    CORS(app)  # Enable CORS
    
    # Register routes
    register_kpi_dashboard_routes(app)
    
    # Run server
    logger.info("Starting KPI Dashboard API server...")
    app.run(host='0.0.0.0', port=5001, debug=True)
