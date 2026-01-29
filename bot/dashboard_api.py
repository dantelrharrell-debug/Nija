"""
NIJA Dashboard API

Flask API endpoints for performance dashboard and investor reporting.
Includes security measures to prevent path traversal attacks.

Author: NIJA Trading Systems
Date: January 29, 2026
"""

from flask import Blueprint, jsonify, request
from typing import Dict, Any
import logging

# Import dashboard and validation utilities
from bot.performance_dashboard import get_performance_dashboard
from bot.path_validator import PathValidationError

logger = logging.getLogger(__name__)

# Create Flask Blueprint
dashboard_bp = Blueprint('dashboard', __name__, url_prefix='/api/dashboard')


@dashboard_bp.route('/health', methods=['GET'])
def health_check():
    """
    Health check endpoint.
    
    Returns:
        JSON response with health status
    """
    return jsonify({
        'status': 'healthy',
        'service': 'NIJA Dashboard API',
        'timestamp': 'now'
    })


@dashboard_bp.route('/portfolio/summary', methods=['GET'])
def get_portfolio_summary():
    """
    Get portfolio summary.
    
    Returns:
        JSON with portfolio metrics
    """
    try:
        dashboard = get_performance_dashboard()
        summary = dashboard.get_portfolio_summary()
        
        return jsonify({
            'success': True,
            'data': summary
        })
    except Exception as e:
        logger.error(f"Error getting portfolio summary: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@dashboard_bp.route('/analytics', methods=['GET'])
def get_analytics():
    """
    Get trade analytics.
    
    Returns:
        JSON with trade analytics
    """
    try:
        dashboard = get_performance_dashboard()
        analytics = dashboard.get_trade_analytics()
        
        return jsonify({
            'success': True,
            'data': analytics
        })
    except Exception as e:
        logger.error(f"Error getting analytics: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@dashboard_bp.route('/risk', methods=['GET'])
def get_risk_metrics():
    """
    Get risk metrics.
    
    Returns:
        JSON with risk metrics
    """
    try:
        dashboard = get_performance_dashboard()
        risk_metrics = dashboard.get_risk_metrics()
        
        return jsonify({
            'success': True,
            'data': risk_metrics
        })
    except Exception as e:
        logger.error(f"Error getting risk metrics: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@dashboard_bp.route('/investor/summary', methods=['GET'])
def get_investor_summary():
    """
    Get comprehensive investor summary.
    
    Returns:
        JSON with complete investor report
    """
    try:
        dashboard = get_performance_dashboard()
        summary = dashboard.get_investor_summary()
        
        return jsonify({
            'success': True,
            'data': summary
        })
    except Exception as e:
        logger.error(f"Error getting investor summary: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@dashboard_bp.route('/export/investor-report', methods=['POST'])
def export_investor_report():
    """
    Export investor report to file.
    
    Request body (JSON):
        {
            "output_dir": "./reports"  # Optional, defaults to ./reports
        }
    
    Returns:
        JSON with filepath to saved report
    """
    try:
        # Get request data with safe defaults
        # SECURITY NOTE: This is where user input enters the system
        data = request.get_json() or {}
        output_dir = data.get('output_dir', './reports')
        
        # Get dashboard instance
        dashboard = get_performance_dashboard()
        
        # Export report - path validation happens inside export_investor_report()
        # This prevents path traversal attacks like output_dir="../../../etc"
        filepath = dashboard.export_investor_report(output_dir=output_dir)
        
        return jsonify({
            'success': True,
            'filepath': filepath,
            'message': 'Investor report exported successfully'
        })
        
    except PathValidationError as e:
        # Security validation failed - log and return error
        logger.warning(f"Path validation error in export_investor_report: {e}")
        return jsonify({
            'success': False,
            'error': 'Invalid output directory path',
            'details': str(e)
        }), 400
        
    except Exception as e:
        logger.error(f"Error exporting investor report: {e}")
        return jsonify({
            'success': False,
            'error': 'Failed to export report',
            'details': str(e)
        }), 500


@dashboard_bp.route('/export/csv', methods=['POST'])
def export_csv_report():
    """
    Export trade data as CSV.
    
    Request body (JSON):
        {
            "output_dir": "./reports"  # Optional, defaults to ./reports
        }
    
    Returns:
        JSON with filepath to saved CSV
    """
    try:
        data = request.get_json() or {}
        output_dir = data.get('output_dir', './reports')
        
        dashboard = get_performance_dashboard()
        filepath = dashboard.export_csv_report(output_dir=output_dir)
        
        return jsonify({
            'success': True,
            'filepath': filepath,
            'message': 'CSV report exported successfully'
        })
        
    except PathValidationError as e:
        logger.warning(f"Path validation error in export_csv_report: {e}")
        return jsonify({
            'success': False,
            'error': 'Invalid output directory path',
            'details': str(e)
        }), 400
        
    except Exception as e:
        logger.error(f"Error exporting CSV report: {e}")
        return jsonify({
            'success': False,
            'error': 'Failed to export CSV',
            'details': str(e)
        }), 500


# For standalone testing
if __name__ == '__main__':
    from flask import Flask
    app = Flask(__name__)
    app.register_blueprint(dashboard_bp)
    app.run(debug=True, port=5001)
