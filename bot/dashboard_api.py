"""
NIJA Dashboard API

Flask API endpoints for performance dashboard and reporting.
Implements secure request handling with input validation.

Author: NIJA Trading Systems
Date: January 29, 2026
"""

from flask import Blueprint, jsonify, request
from typing import Dict, Any
import logging

from bot.performance_dashboard import get_performance_dashboard
from bot.path_validator import PathValidator

logger = logging.getLogger(__name__)

# Create Blueprint for dashboard routes
dashboard_bp = Blueprint('dashboard', __name__, url_prefix='/api/dashboard')


@dashboard_bp.route('/health', methods=['GET'])
def health_check():
    """
    Health check endpoint.
    
    Returns:
        JSON with health status
    """
    return jsonify({
        'status': 'healthy',
        'service': 'dashboard_api',
        'timestamp': str(datetime.now())
    })


@dashboard_bp.route('/performance', methods=['GET'])
def get_performance():
    """
    Get performance metrics for a user.
    
    Query Parameters:
        user_id: User identifier (optional, defaults to "default")
    
    Returns:
        JSON with performance metrics
    """
    user_id = request.args.get('user_id', 'default')
    
    try:
        dashboard = get_performance_dashboard(user_id)
        summary = dashboard.get_performance_summary()
        
        return jsonify({
            'success': True,
            'data': summary
        })
    except Exception as e:
        logger.error(f"Error getting performance metrics: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@dashboard_bp.route('/export', methods=['POST'])
def export_report():
    """
    Export investor report to file.
    
    Request Body:
        {
            "user_id": "user123",
            "output_dir": "./reports"  # Optional, validated for security
        }
    
    Security:
        - Validates output_dir to prevent path traversal
        - Sanitizes user_id to prevent injection
        - Uses secure path resolution
    
    Returns:
        JSON with filepath to saved report
    """
    try:
        data = request.get_json() or {}
        output_dir = data.get('output_dir', './reports')
        
        # SECURITY: Validate output_dir before using it
        # This prevents path traversal attacks where malicious users could try:
        # - "../../../etc/passwd"
        # - "../../sensitive_data"
        # - Absolute paths like "/etc" or "C:\Windows"
        
        if not PathValidator.validate_directory_name(output_dir):
            logger.warning(f"Invalid output_dir received: {output_dir}")
            # Sanitize the path
            output_dir = PathValidator.sanitize_directory_name(output_dir)
            logger.info(f"Sanitized output_dir to: {output_dir}")
        
        # Get user_id from request, default to "default"
        user_id = data.get('user_id', 'default')
        
        dashboard = get_performance_dashboard(user_id)
        filepath = dashboard.export_investor_report(output_dir=output_dir)
        
        return jsonify({
            'success': True,
            'filepath': filepath,
            'message': 'Report exported successfully'
        })
    except ValueError as e:
        # Path validation error
        logger.error(f"Path validation error: {e}")
        return jsonify({
            'success': False,
            'error': 'Invalid output directory path'
        }), 400
    except Exception as e:
        logger.error(f"Error exporting report: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@dashboard_bp.route('/performance/summary', methods=['GET'])
def get_summary():
    """
    Get quick performance summary.
    
    Query Parameters:
        user_id: User identifier (optional)
    
    Returns:
        JSON with performance summary
    """
    user_id = request.args.get('user_id', 'default')
    
    try:
        dashboard = get_performance_dashboard(user_id)
        summary = dashboard.get_performance_summary()
        
        return jsonify({
            'success': True,
            'data': {
                'user_id': summary['user_id'],
                'portfolio_value': summary['portfolio_value'],
                'total_pnl': summary['total_pnl'],
                'win_rate': summary['win_rate'],
                'total_trades': summary['total_trades']
            }
        })
    except Exception as e:
        logger.error(f"Error getting summary: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


# Flask app integration (if running standalone)
if __name__ != '__main__':
    from datetime import datetime
else:
    from flask import Flask
    from datetime import datetime
    
    app = Flask(__name__)
    app.register_blueprint(dashboard_bp)
    
    if __name__ == '__main__':
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )
        
        logger.info("Starting Dashboard API on http://0.0.0.0:5002")
        app.run(host='0.0.0.0', port=5002, debug=False)
