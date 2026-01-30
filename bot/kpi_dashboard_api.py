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
