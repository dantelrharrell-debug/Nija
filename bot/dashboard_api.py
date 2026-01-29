"""
NIJA Performance Dashboard API

Flask API endpoints for accessing investor-grade performance data.

Author: NIJA Trading Systems
Version: 1.0
Date: January 29, 2026
"""

from flask import Blueprint, jsonify, request
from typing import Dict, Any
import logging

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
        data = request.get_json() or {}
        output_dir = data.get('output_dir', './reports')
        
        dashboard = get_performance_dashboard()
        filepath = dashboard.export_investor_report(output_dir=output_dir)
        
        return jsonify({
            'success': True,
            'data': {
                'filepath': filepath
            }
        }), 200
        
    except Exception as e:
        logger.error(f"Error exporting investor report: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


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
