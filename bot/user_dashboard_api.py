"""
NIJA User Dashboard API
=======================

REST API for user management, PnL dashboards, and controls.

Endpoints:
- GET /api/users - List all users
- GET /api/user/{user_id}/pnl - Get user PnL dashboard
- GET /api/user/{user_id}/risk - Get user risk status
- POST /api/user/{user_id}/risk - Update user risk limits
- POST /api/killswitch/global - Trigger global kill switch
- POST /api/killswitch/user/{user_id} - Trigger user kill switch
- GET /api/stats - Get system statistics
"""

import os
import json
import logging
from typing import Dict, List, Optional
from datetime import datetime
from flask import Flask, jsonify, request

# Import our new modules
try:
    from bot.user_pnl_tracker import get_user_pnl_tracker
    from bot.user_risk_manager import get_user_risk_manager
    from bot.user_nonce_manager import get_user_nonce_manager
    from bot.trade_webhook_notifier import get_webhook_notifier
    from controls import get_hard_controls
except ImportError:
    from user_pnl_tracker import get_user_pnl_tracker
    from user_risk_manager import get_user_risk_manager
    from user_nonce_manager import get_user_nonce_manager
    from trade_webhook_notifier import get_webhook_notifier
    import sys
    sys.path.append(os.path.join(os.path.dirname(__file__), '..'))
    from controls import get_hard_controls

logger = logging.getLogger('nija.dashboard_api')

# Initialize Flask app
app = Flask(__name__)
app.config['JSON_SORT_KEYS'] = False


@app.route('/api/health', methods=['GET'])
def health_check():
    """Health check endpoint."""
    return jsonify({
        'status': 'healthy',
        'timestamp': datetime.now().isoformat(),
        'service': 'NIJA User Dashboard API'
    })


@app.route('/api/users', methods=['GET'])
def list_users():
    """List all users with basic stats."""
    try:
        pnl_tracker = get_user_pnl_tracker()
        risk_manager = get_user_risk_manager()
        hard_controls = get_hard_controls()
        
        # Check if we should include master
        include_master = request.args.get('include_master', 'false').lower() == 'true'
        
        # Get all users from various sources
        user_ids = set()
        
        # From hard controls
        for user_id in hard_controls.user_kill_switches.keys():
            if user_id != 'master' or include_master:
                user_ids.add(user_id)
        
        # From risk manager
        for user_id in risk_manager._user_states.keys():
            if user_id != 'master' or include_master:
                user_ids.add(user_id)
        
        # Build user list
        users = []
        for user_id in sorted(user_ids):
            stats = pnl_tracker.get_stats(user_id)
            risk_state = risk_manager.get_state(user_id)
            
            can_trade, reason = hard_controls.can_trade(user_id)
            
            users.append({
                'user_id': user_id,
                'can_trade': can_trade,
                'trading_status': reason if not can_trade else 'active',
                'total_pnl': stats.get('total_pnl', 0.0),
                'daily_pnl': stats.get('daily_pnl', 0.0),
                'win_rate': stats.get('win_rate', 0.0),
                'total_trades': stats.get('completed_trades', 0),
                'balance': risk_state.balance,
                'circuit_breaker': risk_state.circuit_breaker_triggered,
                'is_master': user_id == 'master'
            })
        
        return jsonify({
            'users': users,
            'total_users': len(users),
            'timestamp': datetime.now().isoformat()
        })
    
    except Exception as e:
        logger.error(f"Error listing users: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/user/<user_id>/pnl', methods=['GET'])
def get_user_pnl(user_id: str):
    """Get detailed PnL dashboard for a user."""
    try:
        pnl_tracker = get_user_pnl_tracker()
        
        # Get overall stats
        stats = pnl_tracker.get_stats(user_id, force_refresh=True)
        
        # Get recent trades
        recent_trades = pnl_tracker.get_recent_trades(user_id, limit=20)
        
        # Get daily breakdown
        daily_breakdown = pnl_tracker.get_daily_breakdown(user_id, days=7)
        
        return jsonify({
            'user_id': user_id,
            'stats': stats,
            'recent_trades': recent_trades,
            'daily_breakdown': [
                {
                    'date': day.date,
                    'trades': day.trades_count,
                    'pnl': day.total_pnl,
                    'win_rate': day.win_rate,
                    'winners': day.winners,
                    'losers': day.losers
                }
                for day in daily_breakdown
            ],
            'timestamp': datetime.now().isoformat()
        })
    
    except Exception as e:
        logger.error(f"Error getting PnL for {user_id}: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/master/pnl', methods=['GET'])
def get_master_pnl():
    """Get detailed PnL dashboard for the master account."""
    return get_user_pnl('master')


@app.route('/api/user/<user_id>/risk', methods=['GET'])
def get_user_risk(user_id: str):
    """Get risk status and limits for a user."""
    try:
        risk_manager = get_user_risk_manager()
        
        # Get limits and state
        limits = risk_manager.get_limits(user_id)
        state = risk_manager.get_state(user_id)
        
        # Check if can trade
        can_trade, reason = risk_manager.can_trade(user_id, 0)
        
        return jsonify({
            'user_id': user_id,
            'can_trade': can_trade,
            'status': reason if not can_trade else 'active',
            'limits': {
                'max_position_pct': limits.max_position_pct,
                'max_daily_loss_usd': limits.max_daily_loss_usd,
                'max_daily_trades': limits.max_daily_trades,
                'max_drawdown_pct': limits.max_drawdown_pct
            },
            'current_state': {
                'balance': state.balance,
                'daily_pnl': state.daily_pnl,
                'daily_trades': state.daily_trades,
                'daily_losses': state.daily_losses,
                'drawdown_pct': state.current_drawdown_pct,
                'circuit_breaker': state.circuit_breaker_triggered
            },
            'timestamp': datetime.now().isoformat()
        })
    
    except Exception as e:
        logger.error(f"Error getting risk for {user_id}: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/user/<user_id>/risk', methods=['POST'])
def update_user_risk(user_id: str):
    """Update risk limits for a user."""
    try:
        risk_manager = get_user_risk_manager()
        
        data = request.get_json()
        if not data:
            return jsonify({'error': 'No data provided'}), 400
        
        # Update limits
        risk_manager.update_limits(user_id, **data)
        
        # Get updated limits
        limits = risk_manager.get_limits(user_id)
        
        return jsonify({
            'user_id': user_id,
            'limits': limits.to_dict(),
            'message': 'Risk limits updated',
            'timestamp': datetime.now().isoformat()
        })
    
    except Exception as e:
        logger.error(f"Error updating risk for {user_id}: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/killswitch/global', methods=['POST'])
def trigger_global_killswitch():
    """Trigger global kill switch."""
    try:
        hard_controls = get_hard_controls()
        
        data = request.get_json() or {}
        reason = data.get('reason', 'Manual trigger via API')
        
        hard_controls.trigger_global_kill_switch(reason)
        
        return jsonify({
            'status': 'triggered',
            'reason': reason,
            'timestamp': datetime.now().isoformat()
        })
    
    except Exception as e:
        logger.error(f"Error triggering global kill switch: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/killswitch/global', methods=['DELETE'])
def reset_global_killswitch():
    """Reset global kill switch."""
    try:
        hard_controls = get_hard_controls()
        hard_controls.reset_global_kill_switch()
        
        return jsonify({
            'status': 'reset',
            'timestamp': datetime.now().isoformat()
        })
    
    except Exception as e:
        logger.error(f"Error resetting global kill switch: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/killswitch/user/<user_id>', methods=['POST'])
def trigger_user_killswitch(user_id: str):
    """Trigger kill switch for a specific user."""
    try:
        hard_controls = get_hard_controls()
        
        data = request.get_json() or {}
        reason = data.get('reason', 'Manual trigger via API')
        
        hard_controls.trigger_user_kill_switch(user_id, reason)
        
        return jsonify({
            'user_id': user_id,
            'status': 'triggered',
            'reason': reason,
            'timestamp': datetime.now().isoformat()
        })
    
    except Exception as e:
        logger.error(f"Error triggering user kill switch: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/killswitch/user/<user_id>', methods=['DELETE'])
def reset_user_killswitch(user_id: str):
    """Reset kill switch for a specific user."""
    try:
        hard_controls = get_hard_controls()
        hard_controls.reset_user_kill_switch(user_id)
        
        return jsonify({
            'user_id': user_id,
            'status': 'reset',
            'timestamp': datetime.now().isoformat()
        })
    
    except Exception as e:
        logger.error(f"Error resetting user kill switch: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/stats', methods=['GET'])
def get_system_stats():
    """Get system-wide statistics."""
    try:
        pnl_tracker = get_user_pnl_tracker()
        webhook_notifier = get_webhook_notifier()
        hard_controls = get_hard_controls()
        
        # Global kill switch status
        global_killswitch = hard_controls.global_kill_switch.value
        
        # Count active users
        active_users = sum(
            1 for status in hard_controls.user_kill_switches.values()
            if status.value == 'active'
        )
        
        # Webhook stats
        webhook_stats = webhook_notifier.get_stats()
        
        return jsonify({
            'global_killswitch': global_killswitch,
            'active_users': active_users,
            'total_users': len(hard_controls.user_kill_switches),
            'webhooks': webhook_stats,
            'timestamp': datetime.now().isoformat()
        })
    
    except Exception as e:
        logger.error(f"Error getting system stats: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/user/<user_id>/nonce', methods=['GET'])
def get_user_nonce_stats(user_id: str):
    """Get nonce statistics for a user."""
    try:
        nonce_manager = get_user_nonce_manager()
        stats = nonce_manager.get_stats(user_id)
        
        return jsonify({
            'user_id': user_id,
            'nonce_stats': stats,
            'timestamp': datetime.now().isoformat()
        })
    
    except Exception as e:
        logger.error(f"Error getting nonce stats for {user_id}: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/user/<user_id>/nonce/reset', methods=['POST'])
def reset_user_nonce(user_id: str):
    """Reset nonce tracking for a user."""
    try:
        nonce_manager = get_user_nonce_manager()
        nonce_manager.reset_user(user_id)
        
        return jsonify({
            'user_id': user_id,
            'status': 'reset',
            'timestamp': datetime.now().isoformat()
        })
    
    except Exception as e:
        logger.error(f"Error resetting nonce for {user_id}: {e}")
        return jsonify({'error': str(e)}), 500


def run_dashboard_api(host: str = '0.0.0.0', port: int = 5001, debug: bool = False):
    """
    Run the dashboard API server.
    
    Args:
        host: Host to bind to
        port: Port to bind to
        debug: Enable debug mode
    """
    logger.info(f"Starting NIJA User Dashboard API on {host}:{port}")
    app.run(host=host, port=port, debug=debug, threaded=True)


if __name__ == '__main__':
    # Configure logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    # Run server
    port = int(os.environ.get('DASHBOARD_PORT', 5001))
    run_dashboard_api(port=port, debug=False)
