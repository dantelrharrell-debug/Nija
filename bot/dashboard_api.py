"""
NIJA Dashboard API

Flask API endpoints for performance dashboard and investor reporting.
Includes security measures to prevent path traversal attacks.
Flask API endpoints for performance dashboard and reporting.
Implements secure request handling with input validation.

Author: NIJA Trading Systems
NIJA Performance Dashboard API

Flask API endpoints for accessing investor-grade performance data.

Author: NIJA Trading Systems
Version: 1.0
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
        }), 200
        
    except Exception as e:
        logger.error(f"Error getting portfolio summary: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


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
        logger.error(f"Error getting portfolio summary: {e}")
        logger.error(f"Error getting performance metrics: {e}")
try:
    from performance_dashboard import get_performance_dashboard
    from strategy_portfolio_manager import MarketRegime
except ImportError:
    from bot.performance_dashboard import get_performance_dashboard
    from bot.strategy_portfolio_manager import MarketRegime

logger = logging.getLogger("nija.dashboard_api")

# Create Blueprint
dashboard_api = Blueprint('dashboard_api', __name__, url_prefix='/api/v1/dashboard')


@dashboard_api.route('/metrics', methods=['GET'])
def get_metrics():
    """
    Get current performance metrics

    Returns:
        JSON with current performance metrics
    """
    try:
        dashboard = get_performance_dashboard()
        metrics = dashboard.get_current_metrics()

        return jsonify({
            'success': True,
            'data': metrics
        }), 200

    except Exception as e:
        logger.error(f"Error getting metrics: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@dashboard_api.route('/equity-curve', methods=['GET'])
def get_equity_curve():
    """
    Get equity curve data

    Query params:
        days (int, optional): Number of days to include

    Returns:
        JSON with equity curve data
    """
    try:
        days = request.args.get('days', type=int)

        dashboard = get_performance_dashboard()
        equity_curve = dashboard.get_equity_curve(days=days)

        return jsonify({
            'success': True,
            'data': equity_curve
        }), 200

    except Exception as e:
        logger.error(f"Error getting equity curve: {e}")
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
@dashboard_api.route('/drawdown-curve', methods=['GET'])
def get_drawdown_curve():
    """
    Get drawdown curve data

    Query params:
        days (int, optional): Number of days to include

    Returns:
        JSON with drawdown curve data
    """
    try:
        days = request.args.get('days', type=int)

        dashboard = get_performance_dashboard()
        drawdown_curve = dashboard.get_drawdown_curve(days=days)

        return jsonify({
            'success': True,
            'data': drawdown_curve
        }), 200

    except Exception as e:
        logger.error(f"Error getting drawdown curve: {e}")
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
@dashboard_api.route('/monthly-report/<int:year>/<int:month>', methods=['GET'])
def get_monthly_report(year: int, month: int):
    """
    Get monthly performance report

    Path params:
        year (int): Year for report
        month (int): Month for report (1-12)

    Returns:
        JSON with monthly report data
    """
    try:
        if not (1 <= month <= 12):
            return jsonify({
                'success': False,
                'error': 'Month must be between 1 and 12'
            }), 400

        dashboard = get_performance_dashboard()
        report = dashboard.get_monthly_report(year, month)

        return jsonify({
            'success': True,
            'data': report
        }), 200

    except Exception as e:
        logger.error(f"Error getting monthly report: {e}")
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
        }), 200
        
    except Exception as e:
        logger.error(f"Error getting investor summary: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@dashboard_api.route('/monthly-reports', methods=['GET'])
def get_all_monthly_reports():
    """
    Get all monthly reports

    Returns:
        JSON with all monthly reports
    """
    try:
        dashboard = get_performance_dashboard()
        reports = dashboard.get_all_monthly_reports()

        return jsonify({
            'success': True,
            'data': reports
        }), 200

    except Exception as e:
        logger.error(f"Error getting monthly reports: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@dashboard_api.route('/strategy-performance', methods=['GET'])
def get_strategy_performance():
    """
    Get performance breakdown by strategy

    Returns:
        JSON with strategy-level performance
    """
    try:
        dashboard = get_performance_dashboard()
        performance = dashboard.get_strategy_performance()

        return jsonify({
            'success': True,
            'data': performance
        }), 200

    except Exception as e:
        logger.error(f"Error getting strategy performance: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@dashboard_api.route('/diversification', methods=['GET'])
def get_diversification_metrics():
    """
    Get portfolio diversification metrics

    Returns:
        JSON with diversification metrics
    """
    try:
        dashboard = get_performance_dashboard()
        diversification = dashboard.get_diversification_metrics()

        return jsonify({
            'success': True,
            'data': diversification
        }), 200

    except Exception as e:
        logger.error(f"Error getting diversification metrics: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@dashboard_api.route('/investor-summary', methods=['GET'])
def get_investor_summary():
    """
    Get comprehensive investor summary

    Returns:
        JSON with investor summary
    """
    try:
        dashboard = get_performance_dashboard()
        summary = dashboard.get_investor_summary()

        return jsonify({
            'success': True,
            'data': summary
        }), 200

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
@dashboard_api.route('/export-report', methods=['POST'])
def export_investor_report():
    """
    Export comprehensive investor report to file

    Request body (optional):
        output_dir (str): Directory to save report

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
        data = request.get_json() or {}
        output_dir = data.get('output_dir', './reports')

        dashboard = get_performance_dashboard()
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
    import os
    app = Flask(__name__)
    app.register_blueprint(dashboard_bp)
    # Only use debug mode in development, not production
    debug_mode = os.getenv('FLASK_DEBUG', 'false').lower() == 'true'
    app.run(debug=debug_mode, port=5001)
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
@dashboard_api.route('/update-snapshot', methods=['POST'])
def update_snapshot():
    """
    Update performance snapshot with current portfolio state

    Request body:
        cash (float): Available cash
        positions_value (float): Market value of open positions
        unrealized_pnl (float): Unrealized profit/loss
        realized_pnl_today (float): Realized P&L for today
        total_trades (int): Cumulative total trades
        winning_trades (int): Cumulative winning trades
        losing_trades (int): Cumulative losing trades

    Returns:
        JSON with success status
    """
    try:
        data = request.get_json()

        if not data:
            return jsonify({
                'success': False,
                'error': 'Request body is required'
            }), 400

        # Validate required fields
        required_fields = [
            'cash', 'positions_value', 'unrealized_pnl',
            'realized_pnl_today', 'total_trades',
            'winning_trades', 'losing_trades'
        ]

        missing_fields = [f for f in required_fields if f not in data]
        if missing_fields:
            return jsonify({
                'success': False,
                'error': f'Missing required fields: {", ".join(missing_fields)}'
            }), 400

        dashboard = get_performance_dashboard()
        dashboard.update_snapshot(
            cash=float(data['cash']),
            positions_value=float(data['positions_value']),
            unrealized_pnl=float(data['unrealized_pnl']),
            realized_pnl_today=float(data['realized_pnl_today']),
            total_trades=int(data['total_trades']),
            winning_trades=int(data['winning_trades']),
            losing_trades=int(data['losing_trades'])
        )

        return jsonify({
            'success': True,
            'message': 'Snapshot updated successfully'
        }), 200

    except Exception as e:
        logger.error(f"Error updating snapshot: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@dashboard_api.route('/update-regime', methods=['POST'])
def update_market_regime():
    """
    Update current market regime

    Request body:
        regime (str): Market regime (bull_trending, bear_trending, ranging, volatile, crisis)

    Returns:
        JSON with success status
    """
    try:
        data = request.get_json()

        if not data or 'regime' not in data:
            return jsonify({
                'success': False,
                'error': 'regime field is required'
            }), 400

        # Validate regime
        regime_str = data['regime'].lower()
        try:
            regime = MarketRegime(regime_str)
        except ValueError:
            return jsonify({
                'success': False,
                'error': f'Invalid regime. Must be one of: {[r.value for r in MarketRegime]}'
            }), 400

        dashboard = get_performance_dashboard()
        dashboard.portfolio_manager.update_market_regime(regime)

        return jsonify({
            'success': True,
            'message': f'Market regime updated to {regime.value}'
        }), 200

    except Exception as e:
        logger.error(f"Error updating market regime: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


def register_dashboard_routes(app):
    """
    Register dashboard API routes with Flask app

    Args:
        app: Flask application instance
    """
    app.register_blueprint(dashboard_api)
    logger.info("✅ Registered Performance Dashboard API routes")
