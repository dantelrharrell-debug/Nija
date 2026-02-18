#!/usr/bin/env python3
"""
Legacy Exit Protocol Dashboard Integration
==========================================

Adds Legacy Exit Protocol metrics to existing dashboard APIs.

Provides:
- Cleanup progress percentage
- Positions remaining counter
- Capital freed tracker
- Zombie position count
- Clean state status

Integrates with:
- bot/dashboard_api.py
- bot/kpi_dashboard_api.py
"""

from flask import Blueprint, jsonify, request
from datetime import datetime
from typing import Dict, Any, Optional
import logging

logger = logging.getLogger("nija.legacy_dashboard")

# Create Blueprint for legacy exit routes
legacy_exit_bp = Blueprint('legacy_exit', __name__, url_prefix='/api/legacy-exit')


def get_legacy_exit_protocol(broker_name: str = 'coinbase', dry_run: bool = True):
    """
    Get or create legacy exit protocol instance.
    
    Args:
        broker_name: Broker name (default: coinbase)
        dry_run: Run in dry-run mode (default: True)
        
    Returns:
        LegacyPositionExitProtocol instance
    """
    try:
        from bot.legacy_position_exit_protocol import LegacyPositionExitProtocol
        from bot.broker_integration import get_broker
        
        broker = get_broker(broker_name)
        protocol = LegacyPositionExitProtocol(
            broker_integration=broker,
            dry_run=dry_run
        )
        
        return protocol
    except Exception as e:
        logger.error(f"Failed to initialize legacy exit protocol: {e}")
        return None


@legacy_exit_bp.route('/metrics', methods=['GET'])
def get_metrics():
    """
    GET /api/legacy-exit/metrics
    
    Get cleanup metrics for dashboard display.
    
    Response:
    {
        "success": true,
        "data": {
            "cleanup_progress_pct": 75.5,
            "positions_remaining": 2,
            "capital_freed_usd": 1234.56,
            "zombie_count": 0,
            "total_positions_cleaned": 6,
            "zombie_positions_closed": 1,
            "legacy_positions_unwound": 3,
            "stale_orders_cancelled": 5
        },
        "timestamp": "2026-02-18T22:00:00"
    }
    """
    try:
        broker_name = request.args.get('broker', 'coinbase')
        
        protocol = get_legacy_exit_protocol(broker_name, dry_run=True)
        if not protocol:
            return jsonify({
                'success': False,
                'error': 'Failed to initialize protocol'
            }), 500
        
        metrics = protocol.get_metrics()
        
        return jsonify({
            'success': True,
            'data': {
                'cleanup_progress_pct': metrics.cleanup_progress_pct,
                'positions_remaining': metrics.positions_remaining,
                'capital_freed_usd': metrics.capital_freed_usd,
                'zombie_count': metrics.zombie_count,
                'total_positions_cleaned': metrics.total_positions_cleaned,
                'zombie_positions_closed': metrics.zombie_positions_closed,
                'legacy_positions_unwound': metrics.legacy_positions_unwound,
                'stale_orders_cancelled': metrics.stale_orders_cancelled
            },
            'timestamp': datetime.now().isoformat()
        })
        
    except Exception as e:
        logger.error(f"Error getting legacy exit metrics: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@legacy_exit_bp.route('/status', methods=['GET'])
def get_status():
    """
    GET /api/legacy-exit/status
    
    Get current clean state status.
    
    Response:
    {
        "success": true,
        "data": {
            "state": "CLEAN",
            "platform_clean": true,
            "should_enable_trading": true,
            "total_cycles_completed": 5,
            "last_run_timestamp": "2026-02-18T22:00:00"
        },
        "timestamp": "2026-02-18T22:00:00"
    }
    """
    try:
        broker_name = request.args.get('broker', 'coinbase')
        
        protocol = get_legacy_exit_protocol(broker_name, dry_run=True)
        if not protocol:
            return jsonify({
                'success': False,
                'error': 'Failed to initialize protocol'
            }), 500
        
        # Verify state
        state = protocol.verify_only()
        
        return jsonify({
            'success': True,
            'data': {
                'state': state.value,
                'platform_clean': protocol.is_platform_clean(),
                'should_enable_trading': protocol.should_enable_trading(),
                'total_cycles_completed': protocol.state.total_cycles_completed,
                'last_run_timestamp': protocol.state.last_run_timestamp
            },
            'timestamp': datetime.now().isoformat()
        })
        
    except Exception as e:
        logger.error(f"Error getting legacy exit status: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@legacy_exit_bp.route('/verify', methods=['GET'])
def verify():
    """
    GET /api/legacy-exit/verify
    
    Run verification check (non-destructive).
    
    Response:
    {
        "success": true,
        "data": {
            "state": "CLEAN",
            "positions_remaining": 5,
            "zombie_count": 0,
            "cleanup_progress_pct": 100.0
        },
        "timestamp": "2026-02-18T22:00:00"
    }
    """
    try:
        broker_name = request.args.get('broker', 'coinbase')
        account_id = request.args.get('account_id')
        
        protocol = get_legacy_exit_protocol(broker_name, dry_run=True)
        if not protocol:
            return jsonify({
                'success': False,
                'error': 'Failed to initialize protocol'
            }), 500
        
        state = protocol.verify_only(account_id)
        metrics = protocol.get_metrics()
        
        return jsonify({
            'success': True,
            'data': {
                'state': state.value,
                'positions_remaining': metrics.positions_remaining,
                'zombie_count': metrics.zombie_count,
                'cleanup_progress_pct': metrics.cleanup_progress_pct
            },
            'timestamp': datetime.now().isoformat()
        })
        
    except Exception as e:
        logger.error(f"Error verifying legacy exit state: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@legacy_exit_bp.route('/run', methods=['POST'])
def run_protocol():
    """
    POST /api/legacy-exit/run
    
    Run the full cleanup protocol.
    
    Request Body:
    {
        "dry_run": true,
        "account_id": null,
        "broker": "coinbase"
    }
    
    Response:
    {
        "success": true,
        "data": {
            "state": "CLEAN",
            "elapsed_seconds": 2.5,
            "metrics": {...}
        },
        "timestamp": "2026-02-18T22:00:00"
    }
    """
    try:
        data = request.json or {}
        dry_run = data.get('dry_run', True)
        account_id = data.get('account_id')
        broker_name = data.get('broker', 'coinbase')
        
        protocol = get_legacy_exit_protocol(broker_name, dry_run=dry_run)
        if not protocol:
            return jsonify({
                'success': False,
                'error': 'Failed to initialize protocol'
            }), 500
        
        results = protocol.run_full_protocol(account_id)
        
        return jsonify({
            'success': True,
            'data': results,
            'timestamp': datetime.now().isoformat()
        })
        
    except Exception as e:
        logger.error(f"Error running legacy exit protocol: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


def register_legacy_exit_routes(app):
    """
    Register legacy exit protocol routes with Flask app.
    
    Args:
        app: Flask application instance
    """
    app.register_blueprint(legacy_exit_bp)
    logger.info("✅ Legacy Exit Protocol routes registered")
    logger.info("   GET  /api/legacy-exit/metrics")
    logger.info("   GET  /api/legacy-exit/status")
    logger.info("   GET  /api/legacy-exit/verify")
    logger.info("   POST /api/legacy-exit/run")


def add_legacy_metrics_to_dashboard(dashboard_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Add legacy exit metrics to existing dashboard data.
    
    Args:
        dashboard_data: Existing dashboard data dictionary
        
    Returns:
        Updated dashboard data with legacy exit metrics
    """
    try:
        protocol = get_legacy_exit_protocol(dry_run=True)
        if not protocol:
            return dashboard_data
        
        metrics = protocol.get_metrics()
        
        # Add legacy exit section
        dashboard_data['legacy_exit'] = {
            'cleanup_progress_pct': metrics.cleanup_progress_pct,
            'positions_remaining': metrics.positions_remaining,
            'capital_freed_usd': metrics.capital_freed_usd,
            'zombie_count': metrics.zombie_count,
            'state': protocol.state.account_state,
            'platform_clean': protocol.is_platform_clean()
        }
        
        return dashboard_data
        
    except Exception as e:
        logger.error(f"Error adding legacy metrics to dashboard: {e}")
        return dashboard_data


# Example usage in existing dashboard
def enhanced_dashboard_overview():
    """
    Enhanced dashboard overview with legacy exit metrics.
    
    Returns:
        Complete dashboard data including legacy exit metrics
    """
    # Get existing dashboard data (from your existing dashboard API)
    dashboard_data = {
        'performance': {},
        'portfolio': {},
        'risk': {}
    }
    
    # Add legacy exit metrics
    dashboard_data = add_legacy_metrics_to_dashboard(dashboard_data)
    
    return dashboard_data
