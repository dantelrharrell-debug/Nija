"""
NIJA KPI Dashboard API

Flask API for KPI dashboards, performance tracking, and risk alarms.
Provides REST endpoints for accessing all performance and risk data.

Features:
- KPI metrics endpoints
- Performance tracking endpoints
- Risk alarm endpoints
- Dashboard data aggregation
- Real-time updates
- Export capabilities
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

from flask import Flask, jsonify, request
from datetime import datetime
from typing import Dict, Any
import logging

try:
    from kpi_tracker import get_kpi_tracker
    from risk_alarm_system import get_risk_alarm_system
    from performance_tracking_service import get_tracking_service
except ImportError:
    from bot.kpi_tracker import get_kpi_tracker
    from bot.risk_alarm_system import get_risk_alarm_system
    from bot.performance_tracking_service import get_tracking_service

logger = logging.getLogger(__name__)


def create_kpi_dashboard_api(app: Flask = None) -> Flask:
    """
    Create or configure Flask app with KPI dashboard routes.
    
    Args:
        app: Existing Flask app (optional)
        
    Returns:
        Configured Flask app
    """
    if app is None:
        app = Flask(__name__)
    
    # Initialize services
    kpi_tracker = get_kpi_tracker()
    alarm_system = get_risk_alarm_system()
    tracking_service = get_tracking_service()
    
    @app.route('/api/v1/kpi/summary', methods=['GET'])
    def get_kpi_summary():
        """Get current KPI summary"""
        try:
            summary = kpi_tracker.get_kpi_summary()
            return jsonify({
                'success': True,
                'data': summary,
                'timestamp': datetime.now().isoformat()
            })
        except Exception as e:
            logger.error(f"Error getting KPI summary: {e}")
            return jsonify({
                'success': False,
                'error': 'Internal server error'
            }), 500
    
    @app.route('/api/v1/kpi/trends', methods=['GET'])
    def get_kpi_trends():
        """Get KPI trends over time"""
        try:
            days = int(request.args.get('days', 30))
            # Validate days parameter
            if days < 1 or days > 365:
                return jsonify({
                    'success': False,
                    'error': 'Days parameter must be between 1 and 365'
                }), 400
            
            trends = kpi_tracker.get_kpi_trends(days=days)
            return jsonify({
                'success': True,
                'data': trends,
                'timestamp': datetime.now().isoformat()
            })
        except ValueError:
            return jsonify({
                'success': False,
                'error': 'Invalid days parameter - must be an integer'
            }), 400
        except Exception as e:
            logger.error(f"Error getting KPI trends: {e}")
            return jsonify({
                'success': False,
                'error': 'Internal server error'
            }), 500
    
    @app.route('/api/v1/kpi/export', methods=['POST'])
    def export_kpis():
        """Export KPIs to file"""
        try:
            filepath = kpi_tracker.export_kpis()
            return jsonify({
                'success': True,
                'filepath': filepath,
                'timestamp': datetime.now().isoformat()
            })
        except Exception as e:
            logger.error(f"Error exporting KPIs: {e}")
            return jsonify({
                'success': False,
                'error': str(e)
            }), 500
    
    @app.route('/api/v1/alarms/active', methods=['GET'])
    def get_active_alarms():
        """Get active alarms"""
        try:
            severity = request.args.get('severity')
            category = request.args.get('category')
            
            alarms = alarm_system.get_active_alarms(severity=severity, category=category)
            
            return jsonify({
                'success': True,
                'data': [
                    {
                        'alarm_id': a.alarm_id,
                        'timestamp': a.timestamp,
                        'severity': a.severity,
                        'category': a.category,
                        'name': a.name,
                        'message': a.message,
                        'current_value': a.current_value,
                        'threshold_value': a.threshold_value,
                        'acknowledged': a.acknowledged
                    }
                    for a in alarms
                ],
                'count': len(alarms),
                'timestamp': datetime.now().isoformat()
            })
        except Exception as e:
            logger.error(f"Error getting active alarms: {e}")
            return jsonify({
                'success': False,
                'error': str(e)
            }), 500
    
    @app.route('/api/v1/alarms/summary', methods=['GET'])
    def get_alarm_summary():
        """Get alarm summary"""
        try:
            summary = alarm_system.get_alarm_summary()
            return jsonify({
                'success': True,
                'data': summary,
                'timestamp': datetime.now().isoformat()
            })
        except Exception as e:
            logger.error(f"Error getting alarm summary: {e}")
            return jsonify({
                'success': False,
                'error': str(e)
            }), 500
    
    @app.route('/api/v1/alarms/<alarm_id>/acknowledge', methods=['POST'])
    def acknowledge_alarm(alarm_id: str):
        """Acknowledge an alarm"""
        try:
            alarm_system.acknowledge_alarm(alarm_id)
            return jsonify({
                'success': True,
                'message': f'Alarm {alarm_id} acknowledged',
                'timestamp': datetime.now().isoformat()
            })
        except Exception as e:
            logger.error(f"Error acknowledging alarm: {e}")
            return jsonify({
                'success': False,
                'error': str(e)
            }), 500
    
    @app.route('/api/v1/alarms/<alarm_id>/clear', methods=['POST'])
    def clear_alarm(alarm_id: str):
        """Clear an alarm"""
        try:
            alarm_system.clear_alarm(alarm_id)
            return jsonify({
                'success': True,
                'message': f'Alarm {alarm_id} cleared',
                'timestamp': datetime.now().isoformat()
            })
        except Exception as e:
            logger.error(f"Error clearing alarm: {e}")
            return jsonify({
                'success': False,
                'error': str(e)
            }), 500
    
    @app.route('/api/v1/performance/status', methods=['GET'])
    def get_performance_status():
        """Get performance tracking service status"""
        try:
            status = tracking_service.get_status()
            return jsonify({
                'success': True,
                'data': status,
                'timestamp': datetime.now().isoformat()
            })
        except Exception as e:
            logger.error(f"Error getting performance status: {e}")
            return jsonify({
                'success': False,
                'error': str(e)
            }), 500
    
    @app.route('/api/v1/performance/summary', methods=['GET'])
    def get_performance_summary():
        """Get comprehensive performance summary"""
        try:
            summary = tracking_service.get_current_summary()
            return jsonify({
                'success': True,
                'data': summary,
                'timestamp': datetime.now().isoformat()
            })
        except Exception as e:
            logger.error(f"Error getting performance summary: {e}")
            return jsonify({
                'success': False,
                'error': str(e)
            }), 500
    
    @app.route('/api/v1/performance/export', methods=['POST'])
    def export_performance_report():
        """Export comprehensive performance report"""
        try:
            filepath = tracking_service.export_report()
            return jsonify({
                'success': True,
                'filepath': filepath,
                'timestamp': datetime.now().isoformat()
            })
        except Exception as e:
            logger.error(f"Error exporting performance report: {e}")
            return jsonify({
                'success': False,
                'error': str(e)
            }), 500
    
    @app.route('/api/v1/dashboard', methods=['GET'])
    def get_dashboard_data():
        """Get complete dashboard data (KPIs + Alarms + Performance)"""
        try:
            kpi_summary = kpi_tracker.get_kpi_summary()
            alarm_summary = alarm_system.get_alarm_summary()
            active_alarms = alarm_system.get_active_alarms()
            service_status = tracking_service.get_status()
            
            dashboard_data = {
                'kpis': kpi_summary,
                'alarms': {
                    'summary': alarm_summary,
                    'active': [
                        {
                            'alarm_id': a.alarm_id,
                            'severity': a.severity,
                            'category': a.category,
                            'message': a.message,
                            'timestamp': a.timestamp
                        }
                        for a in active_alarms[:10]  # Top 10 most recent
                    ]
                },
                'service': service_status
            }
            
            return jsonify({
                'success': True,
                'data': dashboard_data,
                'timestamp': datetime.now().isoformat()
            })
        except Exception as e:
            logger.error(f"Error getting dashboard data: {e}")
            return jsonify({
                'success': False,
                'error': str(e)
            }), 500
    
    @app.route('/api/v1/health', methods=['GET'])
    def health_check():
        """Health check endpoint"""
        try:
            return jsonify({
                'success': True,
                'status': 'healthy',
                'service': 'NIJA KPI Dashboard API',
                'version': '1.0',
                'timestamp': datetime.now().isoformat()
            })
        except Exception as e:
            return jsonify({
                'success': False,
                'status': 'unhealthy',
                'error': str(e)
            }), 500
    
    logger.info("✅ KPI Dashboard API routes registered")
    return app


def register_kpi_dashboard_routes(app: Flask):
    """
    Register KPI dashboard routes to an existing Flask app.
    
    Args:
        app: Flask application
    """
    create_kpi_dashboard_api(app)


if __name__ == '__main__':
    # Run standalone server for testing
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
    
    app = create_kpi_dashboard_api()
    
    print("="*70)
    print("NIJA KPI Dashboard API")
    print("="*70)
    print("\nAvailable Endpoints:")
    print("  GET  /api/v1/kpi/summary         - Get current KPI summary")
    print("  GET  /api/v1/kpi/trends          - Get KPI trends (param: days)")
    print("  POST /api/v1/kpi/export          - Export KPIs to file")
    print("  GET  /api/v1/alarms/active       - Get active alarms")
    print("  GET  /api/v1/alarms/summary      - Get alarm summary")
    print("  POST /api/v1/alarms/<id>/acknowledge - Acknowledge alarm")
    print("  POST /api/v1/alarms/<id>/clear   - Clear alarm")
    print("  GET  /api/v1/performance/status  - Get service status")
    print("  GET  /api/v1/performance/summary - Get performance summary")
    print("  POST /api/v1/performance/export  - Export performance report")
    print("  GET  /api/v1/dashboard           - Get complete dashboard data")
    print("  GET  /api/v1/health              - Health check")
    print("\n" + "="*70)
    print("\n🚀 Starting server on http://localhost:5000\n")
    
    # NOTE: debug=True is for development/testing only
    # In production, set debug=False for security
    app.run(host='0.0.0.0', port=5000, debug=False)
    # Create Flask app
    app = Flask(__name__)
    CORS(app)  # Enable CORS
    
    # Register routes
    register_kpi_dashboard_routes(app)
    
    # Run server
    logger.info("Starting KPI Dashboard API server...")
    app.run(host='0.0.0.0', port=5001, debug=True)
