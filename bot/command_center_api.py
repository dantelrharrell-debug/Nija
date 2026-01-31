"""
NIJA Command Center API

Flask API endpoints for the NIJA Command Center dashboard.
Provides real-time access to all 8 key performance metrics.

Endpoints:
- GET /api/command-center/metrics - Get all metrics
- GET /api/command-center/equity-curve - Get equity curve data
- GET /api/command-center/risk-heat - Get risk heat metrics
- GET /api/command-center/trade-quality - Get trade quality metrics
- GET /api/command-center/signal-accuracy - Get signal accuracy metrics
- GET /api/command-center/slippage - Get slippage metrics
- GET /api/command-center/fee-impact - Get fee impact metrics
- GET /api/command-center/strategy-efficiency - Get strategy efficiency metrics
- GET /api/command-center/growth-velocity - Get growth velocity metrics

Author: NIJA Trading Systems
Version: 1.0
Date: January 30, 2026
"""

from flask import Blueprint, jsonify, request
from datetime import datetime
from typing import Dict, Any
import logging
from dataclasses import asdict

try:
    from command_center_metrics import get_command_center_metrics
except ImportError:
    from bot.command_center_metrics import get_command_center_metrics

logger = logging.getLogger(__name__)

# Create Flask blueprint
command_center_bp = Blueprint('command_center', __name__, url_prefix='/api/command-center')


@command_center_bp.route('/metrics', methods=['GET'])
def get_all_metrics():
    """
    Get all Command Center metrics.
    
    Returns:
        JSON with complete metrics snapshot
    """
    try:
        metrics = get_command_center_metrics()
        snapshot = metrics.get_snapshot()
        
        return jsonify({
            'success': True,
            'data': asdict(snapshot),
            'timestamp': datetime.now().isoformat()
        })
    except Exception as e:
        logger.error(f"Error getting Command Center metrics: {e}", exc_info=True)
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@command_center_bp.route('/equity-curve', methods=['GET'])
def get_equity_curve():
    """
    Get equity curve data.
    
    Query params:
        hours: Number of hours of data (default: 24)
    
    Returns:
        JSON with equity curve data points
    """
    try:
        hours = request.args.get('hours', default=24, type=int)
        
        metrics = get_command_center_metrics()
        equity_data = metrics.get_equity_curve_data(hours=hours)
        equity_metrics = metrics.calculate_equity_curve_metrics()
        
        return jsonify({
            'success': True,
            'data': {
                'current': equity_metrics,
                'history': equity_data
            },
            'timestamp': datetime.now().isoformat()
        })
    except Exception as e:
        logger.error(f"Error getting equity curve: {e}", exc_info=True)
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@command_center_bp.route('/risk-heat', methods=['GET'])
def get_risk_heat():
    """
    Get risk heat metrics.
    
    Returns:
        JSON with risk heat data
    """
    try:
        metrics = get_command_center_metrics()
        risk_data = metrics.calculate_risk_heat()
        
        return jsonify({
            'success': True,
            'data': risk_data,
            'timestamp': datetime.now().isoformat()
        })
    except Exception as e:
        logger.error(f"Error getting risk heat: {e}", exc_info=True)
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@command_center_bp.route('/trade-quality', methods=['GET'])
def get_trade_quality():
    """
    Get trade quality score metrics.
    
    Returns:
        JSON with trade quality data
    """
    try:
        metrics = get_command_center_metrics()
        quality_data = metrics.calculate_trade_quality_score()
        
        return jsonify({
            'success': True,
            'data': quality_data,
            'timestamp': datetime.now().isoformat()
        })
    except Exception as e:
        logger.error(f"Error getting trade quality: {e}", exc_info=True)
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@command_center_bp.route('/signal-accuracy', methods=['GET'])
def get_signal_accuracy():
    """
    Get signal accuracy metrics.
    
    Returns:
        JSON with signal accuracy data
    """
    try:
        metrics = get_command_center_metrics()
        signal_data = metrics.calculate_signal_accuracy()
        
        return jsonify({
            'success': True,
            'data': signal_data,
            'timestamp': datetime.now().isoformat()
        })
    except Exception as e:
        logger.error(f"Error getting signal accuracy: {e}", exc_info=True)
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@command_center_bp.route('/slippage', methods=['GET'])
def get_slippage():
    """
    Get slippage metrics.
    
    Returns:
        JSON with slippage data
    """
    try:
        metrics = get_command_center_metrics()
        slippage_data = metrics.calculate_slippage_metrics()
        
        return jsonify({
            'success': True,
            'data': slippage_data,
            'timestamp': datetime.now().isoformat()
        })
    except Exception as e:
        logger.error(f"Error getting slippage: {e}", exc_info=True)
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@command_center_bp.route('/fee-impact', methods=['GET'])
def get_fee_impact():
    """
    Get fee impact metrics.
    
    Returns:
        JSON with fee impact data
    """
    try:
        metrics = get_command_center_metrics()
        fee_data = metrics.calculate_fee_impact()
        
        return jsonify({
            'success': True,
            'data': fee_data,
            'timestamp': datetime.now().isoformat()
        })
    except Exception as e:
        logger.error(f"Error getting fee impact: {e}", exc_info=True)
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@command_center_bp.route('/strategy-efficiency', methods=['GET'])
def get_strategy_efficiency():
    """
    Get strategy efficiency metrics.
    
    Returns:
        JSON with strategy efficiency data
    """
    try:
        metrics = get_command_center_metrics()
        efficiency_data = metrics.calculate_strategy_efficiency()
        
        return jsonify({
            'success': True,
            'data': efficiency_data,
            'timestamp': datetime.now().isoformat()
        })
    except Exception as e:
        logger.error(f"Error getting strategy efficiency: {e}", exc_info=True)
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@command_center_bp.route('/growth-velocity', methods=['GET'])
def get_growth_velocity():
    """
    Get capital growth velocity metrics.
    
    Returns:
        JSON with growth velocity data
    """
    try:
        metrics = get_command_center_metrics()
        growth_data = metrics.calculate_growth_velocity()
        
        return jsonify({
            'success': True,
            'data': growth_data,
            'timestamp': datetime.now().isoformat()
        })
    except Exception as e:
        logger.error(f"Error getting growth velocity: {e}", exc_info=True)
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@command_center_bp.route('/tier-floors', methods=['GET'])
def get_tier_floors():
    """
    Get tier floor configuration for dashboard display.
    
    Returns tier floor information including:
    - All tier names and capital ranges
    - Floor percentages (position size minimums)
    - Maximum positions per tier
    - Minimum trade sizes
    - Special notes (e.g., INVESTOR tier 22% fix)
    
    This endpoint provides visibility into tier floor enforcement,
    particularly useful for verifying the INVESTOR tier 22% floor fix.
    
    Returns:
        JSON with complete tier floor configuration
    """
    try:
        # Import here to avoid circular dependency
        try:
            from tier_config import get_tier_floors_for_api
        except ImportError:
            from bot.tier_config import get_tier_floors_for_api
        
        tier_data = get_tier_floors_for_api()
        
        return jsonify({
            'success': True,
            'data': tier_data,
            'timestamp': datetime.now().isoformat()
        })
    except Exception as e:
        logger.error(f"Error getting tier floors: {e}", exc_info=True)
        return jsonify({
            'success': False,
            'error': str(e),
            'message': 'Failed to retrieve tier floor configuration'
        }), 500


@command_center_bp.route('/health', methods=['GET'])
def health_check():
    """
    Health check endpoint.
    
    Returns:
        JSON with health status
    """
    try:
        return jsonify({
            'success': True,
            'status': 'healthy',
            'service': 'NIJA Command Center API',
            'version': '1.0',
            'timestamp': datetime.now().isoformat()
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'status': 'unhealthy',
            'error': str(e)
        }), 500


def register_command_center_routes(app):
    """
    Register Command Center routes with Flask app.
    
    Args:
        app: Flask application instance
    """
    app.register_blueprint(command_center_bp)
    logger.info("✅ Command Center API routes registered")


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
    CORS(app)
    
    # Register routes
    register_command_center_routes(app)
    
    print("=" * 70)
    print("NIJA Command Center API")
    print("=" * 70)
    print("\nAvailable Endpoints:")
    print("  GET  /api/command-center/metrics           - All metrics")
    print("  GET  /api/command-center/equity-curve      - Equity curve")
    print("  GET  /api/command-center/risk-heat         - Risk heat")
    print("  GET  /api/command-center/trade-quality     - Trade quality")
    print("  GET  /api/command-center/signal-accuracy   - Signal accuracy")
    print("  GET  /api/command-center/slippage          - Slippage")
    print("  GET  /api/command-center/fee-impact        - Fee impact")
    print("  GET  /api/command-center/strategy-efficiency - Strategy efficiency")
    print("  GET  /api/command-center/growth-velocity   - Growth velocity")
    print("  GET  /api/command-center/health            - Health check")
    print("\n" + "=" * 70)
    print("\n🚀 Starting server on http://localhost:5002\n")
    
    # Run server
    app.run(host='0.0.0.0', port=5002, debug=False)
