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
- GET /api/positions/open - Get open positions
- GET /api/trades/history - Get trade history
- GET /api/trades/export - Export trades to CSV/PDF

Aggregated Read-Only Reporting Endpoints:
- GET /api/aggregated/summary - Combined master + users overview
- GET /api/aggregated/performance - Performance metrics across all accounts
- GET /api/aggregated/positions - Portfolio-wide position summary
- GET /api/aggregated/statistics - System-wide trading statistics
- GET /api/aggregated/traceability - Master-to-user trade traceability report
"""

import os
import json
import logging
from typing import Dict, List, Optional
from datetime import datetime
from flask import Flask, jsonify, request, send_file
import io

# Import our new modules
try:
    from bot.user_pnl_tracker import get_user_pnl_tracker
    from bot.user_risk_manager import get_user_risk_manager
    from bot.user_nonce_manager import get_user_nonce_manager
    from bot.trade_webhook_notifier import get_webhook_notifier
    from bot.trade_ledger_db import get_trade_ledger_db
    from controls import get_hard_controls
except ImportError:
    from user_pnl_tracker import get_user_pnl_tracker
    from user_risk_manager import get_user_risk_manager
    from user_nonce_manager import get_user_nonce_manager
    from trade_webhook_notifier import get_webhook_notifier
    from trade_ledger_db import get_trade_ledger_db
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
        include_platform = request.args.get('include_platform', 'false').lower() == 'true'

        # Get all users from various sources
        user_ids = set()

        # From hard controls
        for user_id in hard_controls.user_kill_switches.keys():
            if user_id != 'platform' or include_platform:
                user_ids.add(user_id)

        # From risk manager
        for user_id in risk_manager._user_states.keys():
            if user_id != 'platform' or include_platform:
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
                'is_master': user_id == 'platform'
            })

        return jsonify({
            'users': users,
            'total_users': len(users),
            'timestamp': datetime.now().isoformat()
        })

    except Exception as e:
        logger.error(f"Error listing users: {e}")
        return jsonify({'error': 'Failed to list users'}), 500


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
        return jsonify({'error': 'Failed to retrieve PnL data'}), 500


@app.route('/api/platform/pnl', methods=['GET'])
def get_platform_pnl():
    """Get detailed PnL dashboard for the platform account."""
    return get_user_pnl('platform')


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
        return jsonify({'error': 'Failed to retrieve risk data'}), 500


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
        return jsonify({'error': 'Failed to update risk limits'}), 500


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
        return jsonify({'error': 'Failed to trigger global kill switch'}), 500


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
        return jsonify({'error': 'Failed to reset global kill switch'}), 500


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
        return jsonify({'error': 'Failed to trigger user kill switch'}), 500


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
        return jsonify({'error': 'Failed to reset user kill switch'}), 500


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
        return jsonify({'error': 'Failed to retrieve system statistics'}), 500


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
        return jsonify({'error': 'Failed to retrieve nonce statistics'}), 500


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
        return jsonify({'error': 'Failed to reset nonce'}), 500


@app.route('/api/positions/open', methods=['GET'])
def get_open_positions():
    """Get all open positions from trade ledger database."""
    try:
        trade_ledger = get_trade_ledger_db()

        # Get query parameters
        user_id = request.args.get('user_id')
        symbol = request.args.get('symbol')

        # Get open positions
        positions = trade_ledger.get_open_positions(user_id=user_id, symbol=symbol)

        return jsonify({
            'positions': positions,
            'count': len(positions),
            'timestamp': datetime.now().isoformat()
        })

    except Exception as e:
        logger.error(f"Error getting open positions: {e}")
        return jsonify({'error': 'Failed to retrieve open positions'}), 500


@app.route('/api/trades/history', methods=['GET'])
def get_trade_history():
    """Get trade history from trade ledger database."""
    try:
        trade_ledger = get_trade_ledger_db()

        # Get query parameters
        user_id = request.args.get('user_id')
        symbol = request.args.get('symbol')
        limit = int(request.args.get('limit', 100))
        offset = int(request.args.get('offset', 0))

        # Get trade history
        trades = trade_ledger.get_trade_history(
            user_id=user_id,
            symbol=symbol,
            limit=limit,
            offset=offset
        )

        # Get statistics
        stats = trade_ledger.get_statistics(user_id=user_id)

        return jsonify({
            'trades': trades,
            'count': len(trades),
            'statistics': stats,
            'timestamp': datetime.now().isoformat()
        })

    except Exception as e:
        logger.error(f"Error getting trade history: {e}")
        return jsonify({'error': 'Failed to retrieve trade history'}), 500


@app.route('/api/trades/ledger', methods=['GET'])
def get_trade_ledger():
    """Get raw trade ledger (all BUY/SELL transactions)."""
    try:
        trade_ledger = get_trade_ledger_db()

        # Get query parameters
        user_id = request.args.get('user_id')
        symbol = request.args.get('symbol')
        limit = int(request.args.get('limit', 100))

        # Get ledger transactions
        transactions = trade_ledger.get_ledger_transactions(
            user_id=user_id,
            symbol=symbol,
            limit=limit
        )

        return jsonify({
            'transactions': transactions,
            'count': len(transactions),
            'timestamp': datetime.now().isoformat()
        })

    except Exception as e:
        logger.error(f"Error getting trade ledger: {e}")
        return jsonify({'error': 'Failed to retrieve trade ledger'}), 500


@app.route('/api/trades/export', methods=['GET'])
def export_trades():
    """Export trades to CSV or PDF format."""
    try:
        trade_ledger = get_trade_ledger_db()

        # Get query parameters
        format_type = request.args.get('format', 'csv').lower()
        table = request.args.get('table', 'completed_trades')
        user_id = request.args.get('user_id')

        # Validate table name
        valid_tables = ['trade_ledger', 'open_positions', 'completed_trades']
        if table not in valid_tables:
            return jsonify({'error': f'Invalid table. Must be one of: {", ".join(valid_tables)}'}), 400

        if format_type == 'csv':
            # Export to CSV
            csv_data = trade_ledger.export_to_csv(table=table, user_id=user_id)

            # Create a file-like object
            output = io.BytesIO()
            output.write(csv_data.encode('utf-8'))
            output.seek(0)

            # Generate filename
            filename = f'nija_{table}_{datetime.now().strftime("%Y%m%d_%H%M%S")}.csv'

            return send_file(
                output,
                mimetype='text/csv',
                as_attachment=True,
                download_name=filename
            )

        elif format_type == 'pdf':
            # PDF export (basic implementation)
            # For a full PDF implementation, you would use reportlab or similar
            return jsonify({'error': 'PDF export not yet implemented. Use CSV format.'}), 501

        else:
            return jsonify({'error': 'Invalid format. Use "csv" or "pdf"'}), 400

    except Exception as e:
        logger.error(f"Error exporting trades: {e}")
        return jsonify({'error': 'Failed to export trades'}), 500


@app.route('/api/trades/statistics', methods=['GET'])
def get_trade_statistics():
    """Get trading statistics."""
    try:
        trade_ledger = get_trade_ledger_db()

        # Get query parameters
        user_id = request.args.get('user_id')

        # Get statistics
        stats = trade_ledger.get_statistics(user_id=user_id)

        return jsonify({
            'statistics': stats,
            'user_id': user_id or 'all',
            'timestamp': datetime.now().isoformat()
        })

    except Exception as e:
        logger.error(f"Error getting statistics: {e}")
        return jsonify({'error': 'Failed to retrieve statistics'}), 500


@app.route('/api/aggregated/summary', methods=['GET'])
def get_aggregated_summary():
    """
    Get aggregated read-only summary of platform + all users.

    Returns:
        - Platform account performance
        - Combined user performance
        - Total portfolio metrics
        - System-wide statistics
    """
    try:
        pnl_tracker = get_user_pnl_tracker()
        risk_manager = get_user_risk_manager()
        hard_controls = get_hard_controls()
        trade_ledger = get_trade_ledger_db()

        # Get platform stats
        platform_stats = pnl_tracker.get_stats('platform', force_refresh=True)
        platform_risk_state = risk_manager.get_state('platform')

        # Get all user stats (excluding platform)
        all_user_ids = set()
        for user_id in risk_manager._user_states.keys():
            if user_id != 'platform':
                all_user_ids.add(user_id)

        # Aggregate user metrics
        total_users = len(all_user_ids)
        users_can_trade = 0
        total_user_balance = 0.0
        total_user_pnl = 0.0
        total_user_trades = 0
        total_user_wins = 0
        total_user_losses = 0

        user_summaries = []
        for user_id in sorted(all_user_ids):
            user_stats = pnl_tracker.get_stats(user_id)
            user_risk_state = risk_manager.get_state(user_id)
            can_trade, reason = hard_controls.can_trade(user_id)

            if can_trade:
                users_can_trade += 1

            total_user_balance += user_risk_state.balance
            total_user_pnl += user_stats.get('total_pnl', 0.0)
            total_user_trades += user_stats.get('completed_trades', 0)
            total_user_wins += user_stats.get('winning_trades', 0)
            total_user_losses += user_stats.get('losing_trades', 0)

            user_summaries.append({
                'user_id': user_id,
                'balance': user_risk_state.balance,
                'total_pnl': user_stats.get('total_pnl', 0.0),
                'win_rate': user_stats.get('win_rate', 0.0),
                'trades': user_stats.get('completed_trades', 0),
                'can_trade': can_trade
            })

        # Calculate aggregate win rate
        aggregate_win_rate = (total_user_wins / total_user_trades * 100) if total_user_trades > 0 else 0.0

        # Get open positions count
        open_positions = trade_ledger.get_open_positions()
        platform_open_positions = [p for p in open_positions if p.get('user_id') == 'platform']
        user_open_positions = [p for p in open_positions if p.get('user_id') != 'platform']

        # Portfolio totals
        portfolio_balance = platform_risk_state.balance + total_user_balance
        portfolio_pnl = platform_stats.get('total_pnl', 0.0) + total_user_pnl

        return jsonify({
            'timestamp': datetime.now().isoformat(),
            'platform_account': {
                'balance': platform_risk_state.balance,
                'total_pnl': platform_stats.get('total_pnl', 0.0),
                'daily_pnl': platform_stats.get('daily_pnl', 0.0),
                'win_rate': platform_stats.get('win_rate', 0.0),
                'total_trades': platform_stats.get('completed_trades', 0),
                'winning_trades': platform_stats.get('winning_trades', 0),
                'losing_trades': platform_stats.get('losing_trades', 0),
                'open_positions': len(platform_open_positions)
            },
            'users_aggregate': {
                'total_users': total_users,
                'active_users': users_can_trade,
                'total_balance': total_user_balance,
                'total_pnl': total_user_pnl,
                'total_trades': total_user_trades,
                'winning_trades': total_user_wins,
                'losing_trades': total_user_losses,
                'aggregate_win_rate': aggregate_win_rate,
                'open_positions': len(user_open_positions)
            },
            'portfolio_totals': {
                'total_balance': portfolio_balance,
                'total_pnl': portfolio_pnl,
                'total_trades': platform_stats.get('completed_trades', 0) + total_user_trades,
                'total_open_positions': len(open_positions),
                'pnl_return_pct': (portfolio_pnl / portfolio_balance * 100) if portfolio_balance > 0 else 0.0
            },
            'user_details': user_summaries
        })

    except Exception as e:
        logger.error(f"Error getting aggregated summary: {e}")
        return jsonify({'error': 'Failed to retrieve aggregated summary'}), 500


@app.route('/api/aggregated/performance', methods=['GET'])
def get_aggregated_performance():
    """
    Get detailed performance metrics aggregated across master and all users.

    Query params:
        - days: Number of days to include in breakdown (default: 7)
    """
    try:
        pnl_tracker = get_user_pnl_tracker()
        days = int(request.args.get('days', 7))

        # Get master performance
        platform_stats = pnl_tracker.get_stats('platform', force_refresh=True)
        master_daily = pnl_tracker.get_daily_breakdown('platform', days=days)

        # Get all user IDs
        all_user_ids = set()
        for user_id in pnl_tracker._user_pnl.keys():
            if user_id != 'platform':
                all_user_ids.add(user_id)

        # Aggregate daily performance across all users
        daily_aggregate = {}

        for user_id in all_user_ids:
            user_daily = pnl_tracker.get_daily_breakdown(user_id, days=days)
            for day in user_daily:
                date_key = day.date
                if date_key not in daily_aggregate:
                    daily_aggregate[date_key] = {
                        'trades': 0,
                        'pnl': 0.0,
                        'winners': 0,
                        'losers': 0
                    }
                daily_aggregate[date_key]['trades'] += day.trades_count
                daily_aggregate[date_key]['pnl'] += day.total_pnl
                daily_aggregate[date_key]['winners'] += day.winners
                daily_aggregate[date_key]['losers'] += day.losers

        # Format daily breakdown
        users_daily_breakdown = [
            {
                'date': date,
                'trades': stats['trades'],
                'pnl': stats['pnl'],
                'winners': stats['winners'],
                'losers': stats['losers'],
                'win_rate': (stats['winners'] / stats['trades'] * 100) if stats['trades'] > 0 else 0.0
            }
            for date, stats in sorted(daily_aggregate.items())
        ]

        return jsonify({
            'timestamp': datetime.now().isoformat(),
            'period_days': days,
            'master_performance': {
                'stats': platform_stats,
                'daily_breakdown': [
                    {
                        'date': day.date,
                        'trades': day.trades_count,
                        'pnl': day.total_pnl,
                        'win_rate': day.win_rate,
                        'winners': day.winners,
                        'losers': day.losers
                    }
                    for day in master_daily
                ]
            },
            'users_performance': {
                'daily_breakdown': users_daily_breakdown
            }
        })

    except Exception as e:
        logger.error(f"Error getting aggregated performance: {e}")
        return jsonify({'error': 'Failed to retrieve aggregated performance'}), 500


@app.route('/api/aggregated/positions', methods=['GET'])
def get_aggregated_positions():
    """
    Get portfolio-wide position summary (platform + all users).

    Returns position breakdown by:
        - Account (master vs users)
        - Symbol
        - Broker
    """
    try:
        trade_ledger = get_trade_ledger_db()

        # Get all open positions
        all_positions = trade_ledger.get_open_positions()

        # Separate master and user positions
        master_positions = [p for p in all_positions if p.get('user_id') == 'platform']
        user_positions = [p for p in all_positions if p.get('user_id') != 'platform']

        # Aggregate by symbol
        symbol_aggregate = {}
        for position in all_positions:
            symbol = position.get('symbol', 'UNKNOWN')
            if symbol not in symbol_aggregate:
                symbol_aggregate[symbol] = {
                    'total_positions': 0,
                    'master_positions': 0,
                    'user_positions': 0,
                    'total_size': 0.0,
                    'total_unrealized_pnl': 0.0
                }

            symbol_aggregate[symbol]['total_positions'] += 1
            if position.get('user_id') == 'platform':
                symbol_aggregate[symbol]['master_positions'] += 1
            else:
                symbol_aggregate[symbol]['user_positions'] += 1

            symbol_aggregate[symbol]['total_size'] += position.get('size', 0.0)
            symbol_aggregate[symbol]['total_unrealized_pnl'] += position.get('unrealized_pnl', 0.0)

        # Aggregate by broker
        broker_aggregate = {}
        for position in all_positions:
            broker = position.get('broker', 'unknown')
            if broker not in broker_aggregate:
                broker_aggregate[broker] = {
                    'positions': 0,
                    'total_size': 0.0,
                    'unrealized_pnl': 0.0
                }

            broker_aggregate[broker]['positions'] += 1
            broker_aggregate[broker]['total_size'] += position.get('size', 0.0)
            broker_aggregate[broker]['unrealized_pnl'] += position.get('unrealized_pnl', 0.0)

        return jsonify({
            'timestamp': datetime.now().isoformat(),
            'summary': {
                'total_positions': len(all_positions),
                'master_positions': len(master_positions),
                'user_positions': len(user_positions),
                'unique_symbols': len(symbol_aggregate),
                'unique_brokers': len(broker_aggregate)
            },
            'by_symbol': symbol_aggregate,
            'by_broker': broker_aggregate,
            'master_positions_list': master_positions,
            'user_positions_list': user_positions
        })

    except Exception as e:
        logger.error(f"Error getting aggregated positions: {e}")
        return jsonify({'error': 'Failed to retrieve aggregated positions'}), 500


@app.route('/api/aggregated/statistics', methods=['GET'])
def get_aggregated_statistics():
    """
    Get comprehensive system-wide trading statistics.

    Includes:
        - All-time performance metrics
        - Risk metrics
        - Trading activity metrics
        - Success rates and profit factors
    """
    try:
        trade_ledger = get_trade_ledger_db()
        pnl_tracker = get_user_pnl_tracker()
        risk_manager = get_user_risk_manager()

        # Get master statistics
        platform_stats = trade_ledger.get_statistics(user_id='platform')

        # Get all user statistics combined
        all_user_ids = set()
        for user_id in risk_manager._user_states.keys():
            if user_id != 'platform':
                all_user_ids.add(user_id)

        # Aggregate user statistics
        users_total_trades = 0
        users_total_volume = 0.0
        users_total_fees = 0.0
        users_total_pnl = 0.0
        users_winning_trades = 0
        users_losing_trades = 0

        for user_id in all_user_ids:
            user_stats = pnl_tracker.get_stats(user_id)
            users_total_trades += user_stats.get('completed_trades', 0)
            users_total_volume += user_stats.get('total_volume', 0.0)
            users_total_fees += user_stats.get('total_fees', 0.0)
            users_total_pnl += user_stats.get('total_pnl', 0.0)
            users_winning_trades += user_stats.get('winning_trades', 0)
            users_losing_trades += user_stats.get('losing_trades', 0)

        users_win_rate = (users_winning_trades / users_total_trades * 100) if users_total_trades > 0 else 0.0

        # System totals
        system_total_trades = platform_stats.get('total_trades', 0) + users_total_trades
        system_total_pnl = platform_stats.get('total_pnl', 0.0) + users_total_pnl
        system_total_fees = platform_stats.get('total_fees', 0.0) + users_total_fees

        return jsonify({
            'timestamp': datetime.now().isoformat(),
            'master_statistics': platform_stats,
            'users_statistics': {
                'total_trades': users_total_trades,
                'total_volume': users_total_volume,
                'total_fees': users_total_fees,
                'total_pnl': users_total_pnl,
                'winning_trades': users_winning_trades,
                'losing_trades': users_losing_trades,
                'win_rate': users_win_rate,
                'average_pnl_per_trade': users_total_pnl / users_total_trades if users_total_trades > 0 else 0.0
            },
            'system_totals': {
                'total_trades': system_total_trades,
                'total_pnl': system_total_pnl,
                'total_fees': system_total_fees,
                'net_pnl': system_total_pnl - system_total_fees,
                'total_users': len(all_user_ids)
            }
        })

    except Exception as e:
        logger.error(f"Error getting aggregated statistics: {e}")
        return jsonify({'error': 'Failed to retrieve aggregated statistics'}), 500


@app.route('/api/aggregated/traceability', methods=['GET'])
def get_trade_traceability():
    """
    Get master-to-user trade traceability report.

    Shows how user trades correlate to master signals and execution.
    This endpoint helps stakeholders understand copy trading performance.

    Query params:
        - hours: Number of hours to look back (default: 24)
        - limit: Max number of trade groups to return (default: 50)
    """
    try:
        trade_ledger = get_trade_ledger_db()

        hours = int(request.args.get('hours', 24))
        limit = int(request.args.get('limit', 50))

        # Get recent master trades
        platform_trades = trade_ledger.get_trade_history(
            user_id='platform',
            limit=limit
        )

        # For each master trade, find corresponding user trades
        # (trades with same symbol around the same time)
        traceability_report = []

        for master_trade in platform_trades:
            master_time = datetime.fromisoformat(master_trade['entry_time'])
            symbol = master_trade['symbol']

            # Find user trades for same symbol within 5 minutes of master trade
            user_trades_for_symbol = []

            # Get all user trades for this symbol
            all_symbol_trades = trade_ledger.get_trade_history(symbol=symbol, limit=100)

            for trade in all_symbol_trades:
                if trade['user_id'] == 'platform':
                    continue

                trade_time = datetime.fromisoformat(trade['entry_time'])
                time_diff = abs((trade_time - master_time).total_seconds())

                # If trade is within 5 minutes, consider it a copy trade
                if time_diff <= 300:  # 5 minutes
                    user_trades_for_symbol.append({
                        'user_id': trade['user_id'],
                        'entry_time': trade['entry_time'],
                        'entry_price': trade['entry_price'],
                        'exit_price': trade.get('exit_price'),
                        'pnl': trade.get('pnl', 0.0),
                        'size': trade.get('size', 0.0),
                        'time_delay_seconds': time_diff
                    })

            traceability_report.append({
                'master_trade': {
                    'symbol': symbol,
                    'entry_time': master_trade['entry_time'],
                    'entry_price': master_trade['entry_price'],
                    'exit_price': master_trade.get('exit_price'),
                    'pnl': master_trade.get('pnl', 0.0),
                    'size': master_trade.get('size', 0.0),
                    'side': master_trade.get('side', 'UNKNOWN')
                },
                'user_trades': user_trades_for_symbol,
                'replication_count': len(user_trades_for_symbol),
                'average_delay_seconds': sum(t['time_delay_seconds'] for t in user_trades_for_symbol) / len(user_trades_for_symbol) if user_trades_for_symbol else 0
            })

        # Calculate summary statistics
        total_platform_trades = len(platform_trades)
        total_replications = sum(item['replication_count'] for item in traceability_report)
        avg_replications_per_signal = total_replications / total_platform_trades if total_platform_trades > 0 else 0

        return jsonify({
            'timestamp': datetime.now().isoformat(),
            'period_hours': hours,
            'summary': {
                'platform_trades': total_platform_trades,
                'total_user_replications': total_replications,
                'average_replications_per_signal': avg_replications_per_signal
            },
            'traceability': traceability_report
        })

    except Exception as e:
        logger.error(f"Error getting trade traceability: {e}")
        return jsonify({'error': 'Failed to retrieve trade traceability'}), 500


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
