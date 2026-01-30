"""
NIJA Simple Web Dashboard

Lightweight Flask dashboard for real-time bot monitoring.
- Live balance tracking
- Trade history
- Performance metrics
- Alert notifications
- Health status
- Active trading status

Author: NIJA Trading Systems
Version: 1.1
Date: January 9, 2026
"""

from flask import Flask, render_template, jsonify, request
import json
import logging
import os
import sys
from pathlib import Path
from datetime import datetime, timedelta
import psutil
import signal as sig

# Add bot directory to path for imports
sys.path.insert(0, os.path.dirname(__file__))

app = Flask(__name__)
logger = logging.getLogger(__name__)

# Data directory
DATA_DIR = Path("/tmp/nija_monitoring")

# Import user management modules
try:
    from user_pnl_tracker import get_user_pnl_tracker
    from user_risk_manager import get_user_risk_manager
    from user_nonce_manager import get_user_nonce_manager
    from trade_webhook_notifier import get_webhook_notifier
    from activity_feed import get_activity_feed
    from position_mirror import get_position_mirror
except ImportError:
    logger.warning("User management modules not available - some endpoints will not work")
    get_user_pnl_tracker = None
    get_user_risk_manager = None
    get_user_nonce_manager = None
    get_webhook_notifier = None
    get_activity_feed = None
    get_position_mirror = None

try:
    sys.path.append(os.path.join(os.path.dirname(__file__), '..'))
    from controls import get_hard_controls
except ImportError:
    logger.warning("Hard controls module not available")
    get_hard_controls = None

# Import Command Center API
try:
    from command_center_api import register_command_center_routes
except ImportError:
    try:
        from bot.command_center_api import register_command_center_routes
    except ImportError:
        logger.warning("Command Center API not available")
        register_command_center_routes = None
# Auto-refresh interval in seconds
AUTO_REFRESH_INTERVAL = 10  # 10 seconds


def _ensure_repo_in_path():
    """
    Ensure repository root is in sys.path for imports.
    Helper function to avoid code duplication.
    """
    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if repo_root not in sys.path:
        sys.path.insert(0, repo_root)


def _get_account_manager():
    """
    Get the multi-account broker manager instance.
    Helper function to avoid code duplication.

    Returns:
        MultiAccountBrokerManager instance
    """
    try:
        from bot.multi_account_broker_manager import MultiAccountBrokerManager

        # Check if there's a global instance in the running bot
        if 'nija_bot' in sys.modules:
            nija_bot = sys.modules['nija_bot']
            if hasattr(nija_bot, 'account_manager'):
                return nija_bot.account_manager

        # Create new instance
        return MultiAccountBrokerManager()
    except Exception as e:
        logger.debug(f"Could not get account manager: {e}")
        return None


@app.route('/')
def index():
    """Main dashboard page"""
    return render_template('dashboard.html')


@app.route('/users')
def users_dashboard():
    """Users dashboard page with cards"""
    return render_template('users_dashboard.html')


@app.route('/trades')
def trades_dashboard():
    """Trades ledger dashboard page"""
    return render_template('trades_dashboard.html')


@app.route('/command-center')
def command_center_dashboard():
    """Command Center dashboard page with live metrics"""
    return render_template('command_center.html')


@app.route('/api/status')
def get_status():
    """Get current bot status"""
    try:
        health_file = DATA_DIR / "health_status.json"
        if health_file.exists():
            with open(health_file, 'r') as f:
                return jsonify(json.load(f))
        return jsonify({"status": "unknown", "message": "No health data available"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/metrics')
def get_metrics():
    """Get performance metrics"""
    try:
        metrics_file = DATA_DIR / "metrics.json"
        if metrics_file.exists():
            with open(metrics_file, 'r') as f:
                return jsonify(json.load(f))
        return jsonify({"total_trades": 0})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/alerts')
def get_alerts():
    """Get recent alerts"""
    try:
        alerts_file = DATA_DIR / "alerts.json"
        if alerts_file.exists():
            with open(alerts_file, 'r') as f:
                alerts = json.load(f)
                # Return last 20 alerts
                return jsonify(alerts[-20:])
        return jsonify([])
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/trades')
def get_trades():
    """Get recent trades"""
    try:
        # Try to load from trade history (uses APP_DIR env var, defaults to /app)
        base_dir = Path(os.getenv("APP_DIR", "/app"))
        trade_file = base_dir / "data" / "trade_history.json"
        if trade_file.exists():
            with open(trade_file, 'r') as f:
                trades = json.load(f)
                # Return last 50 trades
                return jsonify(trades[-50:])
        return jsonify([])
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/health')
def health_check():
    """Simple health check endpoint"""
    return "OK", 200


@app.route('/api/live_capital_status')
def get_live_capital_status():
    """
    Get LIVE CAPITAL VERIFIED status.

    This endpoint returns the current status of the LIVE CAPITAL VERIFIED
    kill-switch, which is the master safety control that must be enabled
    for live trading.

    Returns:
        JSON with verification status and details
    """
    try:
        if not get_hard_controls:
            return jsonify({
                'error': 'Hard controls not available',
                'live_capital_verified': False,
                'can_trade': False,
                'status': 'error'
            }), 503

        hard_controls = get_hard_controls()
        status = hard_controls.get_verification_status()

        # Add human-readable status
        if status['live_capital_verified']:
            status['status'] = 'LIVE TRADING ENABLED'
            status['status_class'] = 'danger'
            status['icon'] = '🔴'
            status['message'] = 'REAL MONEY TRADING IS ACTIVE'
        else:
            status['status'] = 'SAFE MODE (Trading Disabled)'
            status['status_class'] = 'success'
            status['icon'] = '🟢'
            status['message'] = 'Live trading is disabled. Set LIVE_CAPITAL_VERIFIED=true in .env to enable.'

        return jsonify(status)

    except Exception as e:
        logger.error(f"Error getting live capital status: {e}")
        return jsonify({
            'error': 'Failed to retrieve live capital status',
            'live_capital_verified': False,
            'can_trade': False,
            'status': 'error'
        }), 500


@app.route('/api/users', methods=['GET'])
def list_users():
    """List all users with basic stats."""
    try:
        if not all([get_user_pnl_tracker, get_user_risk_manager, get_hard_controls]):
            return jsonify({'error': 'User management modules not available'}), 503

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
        return jsonify({'error': 'Failed to list users'}), 500


@app.route('/api/user/<user_id>/pnl', methods=['GET'])
def get_user_pnl(user_id: str):
    """Get detailed PnL dashboard for a user."""
    try:
        if not get_user_pnl_tracker:
            return jsonify({'error': 'PnL tracker not available'}), 503

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


@app.route('/api/master/pnl', methods=['GET'])
def get_master_pnl():
    """Get detailed PnL dashboard for the master account."""
    return get_user_pnl('master')
@app.route('/api/users')
def get_users():
    """
    Get list of all users with their account information.

    Returns:
        JSON with user list including balances, positions, and trading stats
    """
    try:
        _ensure_repo_in_path()
        from config.user_loader import get_user_config_loader

        users_data = []

        # Load user configurations
        user_loader = get_user_config_loader()
        all_user_configs = user_loader.all_users

        # Get account manager
        account_mgr = _get_account_manager()
        if not account_mgr:
            return jsonify({
                "error": "Account manager not available",
                "users": [],
                "total_users": 0,
                "timestamp": datetime.now().isoformat()
            }), 500

        # Get data for each user
        for user_config in all_user_configs:
            user_id = user_config.user_id
            if not user_id or user_id == 'master':
                continue

            # Get balance
            try:
                user_balance = account_mgr.get_user_balance(user_id)
            except Exception as e:
                logger.debug(f"Could not get balance for {user_id}: {e}")
                user_balance = 0.0

            # Get positions
            user_positions = []
            user_positions_count = 0
            try:
                for broker_type in account_mgr.user_brokers.get(user_id, {}).keys():
                    broker = account_mgr.get_user_broker(user_id, broker_type)
                    if broker and broker.connected:
                        positions = broker.get_positions()
                        if positions:
                            user_positions.extend(positions)
                            user_positions_count += len(positions)
            except Exception as e:
                logger.debug(f"Could not get positions for {user_id}: {e}")

            # Get trading stats
            total_pnl = 0.0
            daily_pnl = 0.0
            win_rate = 0.0
            total_trades = 0
            recent_trades = []
            try:
                from bot.user_pnl_tracker import get_user_pnl_tracker
                pnl_tracker = get_user_pnl_tracker()
                stats = pnl_tracker.get_stats(user_id)
                recent_trades_data = pnl_tracker.get_recent_trades(user_id, limit=10)
                recent_trades = [
                    {
                        "symbol": t.symbol,
                        "side": t.side,
                        "quantity": t.quantity,
                        "price": t.price,
                        "size_usd": t.size_usd,
                        "pnl_usd": t.pnl_usd,
                        "pnl_pct": t.pnl_pct,
                        "timestamp": t.timestamp,
                        "broker": t.broker
                    }
                    for t in recent_trades_data
                ]
                total_pnl = stats.get('total_pnl', 0.0)
                daily_pnl = stats.get('daily_pnl', 0.0)
                win_rate = stats.get('win_rate', 0.0)
                total_trades = stats.get('completed_trades', 0)
            except Exception as e:
                logger.debug(f"Could not get stats for {user_id}: {e}")

            users_data.append({
                "user_id": user_id,
                "name": user_config.name,
                "enabled": user_config.enabled,
                "account_type": user_config.account_type,
                "broker_type": user_config.broker_type,
                "balance": user_balance,
                "positions_count": user_positions_count,
                "positions": user_positions[:5],  # First 5 positions
                "total_pnl": total_pnl,
                "daily_pnl": daily_pnl,
                "win_rate": win_rate,
                "total_trades": total_trades,
                "recent_trades": recent_trades
            })

        return jsonify({
            "users": users_data,
            "total_users": len(users_data),
            "timestamp": datetime.now().isoformat()
        })

    except ImportError as e:
        logger.exception("Import error in get_users")
        return jsonify({
            "error": f"Import error: {str(e)}",
            "users": [],
            "total_users": 0,
            "timestamp": datetime.now().isoformat()
        }), 500
    except Exception as e:
        logger.exception("Error in get_users")
        return jsonify({
            "error": str(e),
            "users": [],
            "total_users": 0,
            "timestamp": datetime.now().isoformat()
        }), 500


@app.route('/api/trading_status')
def get_trading_status():
    """
    Get comprehensive trading status for NIJA and all users.

    Returns:
        JSON with:
        - is_trading: boolean indicating if bot is actively trading
        - active_brokers: list of brokers with open positions
        - total_positions: total number of open positions
        - trading_balance: available balance for trading
        - recent_activity: trading activity in last 24 hours
        - bot_status: overall bot health status
        - users: per-user trading status (if multi-user system active)
    """
    try:
        status = {
            "timestamp": datetime.now().isoformat(),
            "is_trading": False,
            "bot_running": False,
            "active_brokers": [],
            "total_positions": 0,
            "trading_balance": 0.0,
            "recent_activity": {
                "trades_24h": 0,
                "last_trade_time": None
            },
            "bot_status": "unknown",
            "users": [],
            "errors": []
        }

        # Check 1: Is bot process running (check log file activity)
        try:
            base_dir = Path(os.getenv("APP_DIR", "/app"))
            log_file = base_dir / "nija.log"
            alt_log_file = Path("../nija.log")

            for lf in [log_file, alt_log_file]:
                if lf.exists():
                    last_modified = datetime.fromtimestamp(lf.stat().st_mtime)
                    time_since_update = datetime.now() - last_modified

                    if time_since_update.total_seconds() < 300:  # 5 minutes
                        status["bot_running"] = True
                        status["bot_status"] = "running"
                        status["last_log_update"] = last_modified.isoformat()
                        status["log_age_seconds"] = int(time_since_update.total_seconds())
                    break
        except Exception as e:
            status["errors"].append(f"Log check failed: {str(e)}")

        # Check 2: Get broker positions and balances
        try:
            from broker_manager import CoinbaseBroker, KrakenBroker, OKXBroker

            brokers_to_check = [
                ("Coinbase Advanced Trade", CoinbaseBroker),
                ("Kraken Pro", KrakenBroker),
                ("OKX", OKXBroker),
            ]

            for broker_name, broker_class in brokers_to_check:
                try:
                    broker = broker_class()
                    if broker.connect():
                        # Get positions
                        positions = broker.get_positions()
                        if positions and len(positions) > 0:
                            status["is_trading"] = True
                            status["active_brokers"].append({
                                "name": broker_name,
                                "positions": len(positions),
                                "position_details": positions[:5]  # First 5 positions
                            })
                            status["total_positions"] += len(positions)

                        # Get balance
                        try:
                            balance_data = broker.get_account_balance()
                            if isinstance(balance_data, dict):
                                balance = balance_data.get('trading_balance', 0)
                            else:
                                balance = float(balance_data) if balance_data else 0

                            status["trading_balance"] += balance

                            # Add broker balance info
                            for broker_info in status["active_brokers"]:
                                if broker_info["name"] == broker_name:
                                    broker_info["balance"] = balance
                                    break
                            else:
                                # Broker connected but no positions
                                if broker_name not in [b["name"] for b in status["active_brokers"]]:
                                    status["active_brokers"].append({
                                        "name": broker_name,
                                        "positions": 0,
                                        "balance": balance,
                                        "status": "connected_idle"
                                    })
                        except Exception as e:
                            logger.warning(f"Could not get balance from {broker_name}: {e}")
                except Exception as e:
                    logger.debug(f"Could not check {broker_name}: {e}")
                    continue
        except ImportError as e:
            status["errors"].append(f"Broker import failed: {str(e)}")
        except Exception as e:
            status["errors"].append(f"Broker check failed: {str(e)}")

        # Check 3: Recent trading activity from trade journal
        try:
            base_dir = Path(os.getenv("APP_DIR", "/app"))
            journal_file = Path("../trade_journal.jsonl")
            alt_journal = base_dir / "trade_journal.jsonl"

            for jf in [journal_file, alt_journal]:
                if jf.exists():
                    trades_24h = 0
                    last_trade = None
                    cutoff_time = datetime.now() - timedelta(hours=24)

                    with open(jf, 'r') as f:
                        for line in f:
                            if not line.strip():
                                continue
                            try:
                                trade = json.loads(line)
                                trade_time = datetime.fromisoformat(trade.get('timestamp', ''))

                                if trade_time >= cutoff_time:
                                    trades_24h += 1
                                    if not last_trade or trade_time > datetime.fromisoformat(last_trade):
                                        last_trade = trade.get('timestamp')
                            except:
                                continue

                    status["recent_activity"]["trades_24h"] = trades_24h
                    status["recent_activity"]["last_trade_time"] = last_trade

                    if trades_24h > 0:
                        status["is_trading"] = True
                    break
        except Exception as e:
            status["errors"].append(f"Trade journal check failed: {str(e)}")

        # Check 4: User-specific trading status from multi-account broker manager
        try:
            _ensure_repo_in_path()
            from config.user_loader import get_user_config_loader

            # Load user configurations
            user_loader = get_user_config_loader()
            all_user_configs = user_loader.all_users

            # Get account manager
            account_mgr = _get_account_manager()

            if account_mgr:
                # Get user data from configuration files
                for user_config in all_user_configs:
                    user_id = user_config.user_id
                    if not user_id or user_id == 'master':
                        continue

                    # Get balance for this user across all brokers
                    try:
                        user_balance = account_mgr.get_user_balance(user_id)
                    except Exception as e:
                        logger.debug(f"Could not get balance for {user_id}: {e}")
                        user_balance = 0.0

                    # Get positions for this user
                    user_positions = 0
                    try:
                        for broker_type in account_mgr.user_brokers.get(user_id, {}).keys():
                            broker = account_mgr.get_user_broker(user_id, broker_type)
                            if broker and broker.connected:
                                positions = broker.get_positions()
                                if positions:
                                    user_positions += len(positions)
                    except Exception as e:
                        logger.debug(f"Could not get positions for {user_id}: {e}")

                    # Get recent trades from user PnL tracker
                    recent_trades = []
                    total_pnl = 0.0
                    daily_pnl = 0.0
                    win_rate = 0.0
                    total_trades = 0
                    try:
                        from bot.user_pnl_tracker import get_user_pnl_tracker
                        pnl_tracker = get_user_pnl_tracker()
                        stats = pnl_tracker.get_stats(user_id)
                        recent_trades_data = pnl_tracker.get_recent_trades(user_id, limit=5)
                        recent_trades = [
                            {
                                "symbol": t.symbol,
                                "side": t.side,
                                "pnl_usd": t.pnl_usd,
                                "timestamp": t.timestamp
                            }
                            for t in recent_trades_data
                        ]
                        total_pnl = stats.get('total_pnl', 0.0)
                        daily_pnl = stats.get('daily_pnl', 0.0)
                        win_rate = stats.get('win_rate', 0.0)
                        total_trades = stats.get('completed_trades', 0)
                    except Exception as e:
                        logger.debug(f"Could not get PnL for {user_id}: {e}")

                    status["users"].append({
                        "user_id": user_id,
                        "name": user_config.name,
                        "enabled": user_config.enabled,
                        "account_type": user_config.account_type,
                        "broker_type": user_config.broker_type,
                        "balance": user_balance,
                        "positions": user_positions,
                        "total_pnl": total_pnl,
                        "daily_pnl": daily_pnl,
                        "win_rate": win_rate,
                        "total_trades": total_trades,
                        "recent_trades": recent_trades
                    })
        except ImportError as e:
            # Multi-user system not available
            logger.debug(f"Multi-user system import failed: {e}")
            status["errors"].append(f"Multi-user system import failed: {str(e)}")
            status["users"] = []
        except Exception as e:
            logger.exception(f"User check failed: {e}")
            status["errors"].append(f"User check failed: {str(e)}")
            status["users"] = []

        # Determine overall trading status
        if status["is_trading"]:
            status["trading_status"] = "ACTIVE"
            status["message"] = f"NIJA is actively trading with {status['total_positions']} open positions across {len([b for b in status['active_brokers'] if b.get('positions', 0) > 0])} broker(s)"
        elif status["bot_running"]:
            status["trading_status"] = "READY"
            status["message"] = "NIJA is running and monitoring markets, waiting for entry signals"
        else:
            status["trading_status"] = "STOPPED"
            status["message"] = "NIJA bot does not appear to be running"

        return jsonify(status)

    except Exception as e:
        logger.exception("Error in get_trading_status")
        return jsonify({
            "error": str(e),
            "timestamp": datetime.now().isoformat(),
            "is_trading": False,
            "trading_status": "ERROR"
        }), 500


@app.route('/status')
def human_readable_status():
    """Human-readable trading status page"""
    try:
        # Get trading status data by calling the function directly
        # to avoid circular HTTP requests
        with app.test_request_context():
            status_response = get_trading_status()
            data = status_response.get_json()

        # Build HTML
        html = """<!DOCTYPE html>
<html>
<head>
    <title>NIJA Trading Status</title>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <style>
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: #0f1419;
            color: #e7e9ea;
            padding: 40px;
            line-height: 1.6;
        }
        .container { max-width: 900px; margin: 0 auto; }
        h1 { color: #1d9bf0; margin-bottom: 10px; }
        .timestamp { color: #71767b; font-size: 14px; margin-bottom: 30px; }
        .status-box {
            background: #16181c;
            border: 2px solid #2f3336;
            border-radius: 12px;
            padding: 30px;
            margin-bottom: 20px;
        }
        .status-active { border-color: #00ba7c; }
        .status-ready { border-color: #ffd400; }
        .status-stopped { border-color: #f91880; }
        .status-indicator {
            font-size: 48px;
            margin-bottom: 20px;
        }
        .status-text {
            font-size: 24px;
            font-weight: bold;
            margin-bottom: 10px;
        }
        .active { color: #00ba7c; }
        .ready { color: #ffd400; }
        .stopped { color: #f91880; }
        .info-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 20px;
            margin-top: 20px;
        }
        .info-card {
            background: #16181c;
            border: 1px solid #2f3336;
            border-radius: 8px;
            padding: 20px;
        }
        .info-label { color: #71767b; font-size: 12px; margin-bottom: 5px; }
        .info-value { font-size: 24px; font-weight: bold; }
        .broker-list { margin-top: 15px; }
        .broker-item {
            background: #16181c;
            border: 1px solid #2f3336;
            border-radius: 8px;
            padding: 15px;
            margin-bottom: 10px;
        }
        .user-list { margin-top: 15px; }
        .user-item {
            background: #16181c;
            border: 1px solid #2f3336;
            border-radius: 8px;
            padding: 12px;
            margin-bottom: 8px;
        }
    </style>
</head>
<body>
    <div class="container">
        <h1>🤖 NIJA Trading Status</h1>
        <div class="timestamp">Last updated: """ + data.get('timestamp', '') + """</div>

        <div class="status-box status-""" + data.get('trading_status', 'stopped').lower() + """">
            <div class="status-indicator">"""

        if data.get('trading_status') == 'ACTIVE':
            html += "🟢"
        elif data.get('trading_status') == 'READY':
            html += "🟡"
        else:
            html += "🔴"

        html += """</div>
            <div class="status-text """ + data.get('trading_status', 'stopped').lower() + """">
                """ + data.get('trading_status', 'UNKNOWN') + """
            </div>
            <p>""" + data.get('message', 'No status message available') + """</p>
        </div>

        <div class="info-grid">
            <div class="info-card">
                <div class="info-label">Open Positions</div>
                <div class="info-value">""" + str(data.get('total_positions', 0)) + """</div>
            </div>
            <div class="info-card">
                <div class="info-label">Trading Balance</div>
                <div class="info-value">$""" + f"{data.get('trading_balance', 0):.2f}" + """</div>
            </div>
            <div class="info-card">
                <div class="info-label">Trades (24h)</div>
                <div class="info-value">""" + str(data.get('recent_activity', {}).get('trades_24h', 0)) + """</div>
            </div>
            <div class="info-card">
                <div class="info-label">Active Brokers</div>
                <div class="info-value">""" + str(len([b for b in data.get('active_brokers', []) if b.get('positions', 0) > 0])) + """</div>
            </div>
        </div>"""

        # Broker details
        if data.get('active_brokers'):
            html += """
        <h2 style="margin-top: 30px; color: #1d9bf0;">Connected Brokers</h2>
        <div class="broker-list">"""
            for broker in data['active_brokers']:
                html += """
            <div class="broker-item">
                <strong>""" + broker.get('name', 'Unknown') + """</strong><br>
                Positions: """ + str(broker.get('positions', 0)) + """<br>
                Balance: $""" + f"{broker.get('balance', 0):.2f}" + """
            </div>"""
            html += "</div>"

        # User details (if available)
        if data.get('users') and len(data.get('users', [])) > 0:
            html += """
        <h2 style="margin-top: 30px; color: #1d9bf0;">👥 User Accounts & Trading Activity</h2>
        <div style="background: #16181c; border: 2px solid #1d9bf0; border-radius: 8px; padding: 15px; margin-bottom: 20px;">
            <div style="font-size: 14px; font-weight: bold; color: #1d9bf0; margin-bottom: 8px;">🔄 Copy Trading Active</div>
            <div style="font-size: 13px; color: #e7e9ea; line-height: 1.6;">
                All user trades are <strong>automatically copied</strong> from the NIJA master account. Users <strong>cannot initiate their own trades</strong>.
                Position sizes are scaled proportionally to each user's account balance.
            </div>
        </div>
        <div class="user-list">"""
            for user in data['users']:
                status_icon = "✅" if user.get('enabled') else "❌"
                pnl_color = "color: #00ba7c;" if user.get('total_pnl', 0) >= 0 else "color: #f91880;"
                daily_pnl_color = "color: #00ba7c;" if user.get('daily_pnl', 0) >= 0 else "color: #f91880;"

                html += """
            <div class="user-item" style="padding: 20px;">
                <div style="display: flex; justify-content: space-between; align-items: start; margin-bottom: 15px;">
                    <div>
                        <div style="font-size: 18px; font-weight: bold; margin-bottom: 5px;">
                            """ + status_icon + """ """ + user.get('name', user.get('user_id', 'Unknown')) + """ <span style="font-size: 12px; color: #71767b; font-weight: normal;">(Copy Trading)</span>
                        </div>
                        <div style="font-size: 13px; color: #71767b;">
                            """ + user.get('user_id', '') + """ • """ + user.get('broker_type', 'N/A').upper() + """ • """ + user.get('account_type', 'N/A').title() + """
                        </div>
                    </div>
                    <div style="text-align: right;">
                        <div style="font-size: 24px; font-weight: bold;">$""" + f"{user.get('balance', 0):.2f}" + """</div>
                        <div style="font-size: 12px; color: #71767b;">Account Balance</div>
                    </div>
                </div>

                <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 15px; margin-top: 15px; padding-top: 15px; border-top: 1px solid #2f3336;">
                    <div>
                        <div style="font-size: 11px; color: #71767b; margin-bottom: 3px;">Open Positions</div>
                        <div style="font-size: 16px; font-weight: bold;">""" + str(user.get('positions', 0)) + """</div>
                    </div>
                    <div>
                        <div style="font-size: 11px; color: #71767b; margin-bottom: 3px;">Total Trades</div>
                        <div style="font-size: 16px; font-weight: bold;">""" + str(user.get('total_trades', 0)) + """</div>
                    </div>
                    <div>
                        <div style="font-size: 11px; color: #71767b; margin-bottom: 3px;">Win Rate</div>
                        <div style="font-size: 16px; font-weight: bold;">""" + f"{user.get('win_rate', 0):.1f}" + """%</div>
                    </div>
                    <div>
                        <div style="font-size: 11px; color: #71767b; margin-bottom: 3px;">Total P&L</div>
                        <div style="font-size: 16px; font-weight: bold; """ + pnl_color + """">$""" + f"{user.get('total_pnl', 0):.2f}" + """</div>
                    </div>
                    <div>
                        <div style="font-size: 11px; color: #71767b; margin-bottom: 3px;">Daily P&L</div>
                        <div style="font-size: 16px; font-weight: bold; """ + daily_pnl_color + """">$""" + f"{user.get('daily_pnl', 0):.2f}" + """</div>
                    </div>
                </div>"""

                # Show recent trades if available
                if user.get('recent_trades') and len(user.get('recent_trades', [])) > 0:
                    html += """
                <div style="margin-top: 15px; padding-top: 15px; border-top: 1px solid #2f3336;">
                    <div style="font-size: 12px; color: #71767b; margin-bottom: 8px;">Recent Trades:</div>"""
                    for trade in user.get('recent_trades', [])[:3]:
                        trade_pnl = trade.get('pnl_usd', 0)
                        trade_color = "#00ba7c" if trade_pnl >= 0 else "#f91880"
                        html += """
                    <div style="font-size: 11px; margin-bottom: 4px; display: flex; justify-content: space-between;">
                        <span>""" + trade.get('symbol', 'N/A') + """ (""" + trade.get('side', 'N/A').upper() + """)</span>
                        <span style="color: """ + trade_color + """;">$""" + f"{trade_pnl:.2f}" + """</span>
                    </div>"""
                    html += """
                </div>"""

                html += """
            </div>"""
            html += "</div>"
        else:
            html += """
        <h2 style="margin-top: 30px; color: #1d9bf0;">👥 User Accounts</h2>
        <div style="padding: 30px; text-align: center; color: #71767b; background: #16181c; border-radius: 8px; margin-top: 15px;">
            <p>No user accounts configured or unable to fetch user data.</p>
            <p style="margin-top: 10px; font-size: 13px;">Configure users in <code>config/users/*.json</code> and set credentials in <code>.env</code></p>
        </div>"""

        html += """
        <div style="margin-top: 30px; padding: 20px; background: #16181c; border-radius: 8px; font-size: 13px; color: #71767b;">
            <strong>Auto-refresh:</strong> This page refreshes every 10 seconds<br>
            <strong>API Endpoint:</strong> <a href="/api/trading_status" style="color: #1d9bf0;">/api/trading_status</a>
        </div>

        <script>
            setTimeout(function() { location.reload(); }, 10000);
        </script>
    </div>
</body>
</html>"""

        return html

    except Exception as e:
        return f"""<!DOCTYPE html>
<html>
<head><title>NIJA Status - Error</title></head>
<body style="font-family: sans-serif; padding: 40px; background: #0f1419; color: #e7e9ea;">
    <h1>Error Loading Status</h1>
    <p>{str(e)}</p>
    <p><a href="/api/trading_status" style="color: #1d9bf0;">Try API endpoint directly</a></p>
</body>
</html>""", 500


def create_dashboard_html():
    """Create the dashboard HTML template"""
    templates_dir = Path(__file__).parent / "templates"
    templates_dir.mkdir(exist_ok=True)

    html_content = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>NIJA Bot Dashboard</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
            background: #0f1419;
            color: #e7e9ea;
            padding: 20px;
        }
        .container { max-width: 1400px; margin: 0 auto; }
        .header {
            background: linear-gradient(135deg, #1d4ed8 0%, #7c3aed 100%);
            padding: 30px;
            border-radius: 12px;
            margin-bottom: 20px;
            box-shadow: 0 4px 6px rgba(0,0,0,0.3);
        }
        .header h1 { font-size: 32px; margin-bottom: 5px; }
        .header .subtitle { opacity: 0.9; font-size: 14px; }
        .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 20px; margin-bottom: 20px; }
        .card {
            background: #16181c;
            border: 1px solid #2f3336;
            border-radius: 12px;
            padding: 20px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.2);
        }
        .card h2 { font-size: 18px; margin-bottom: 15px; color: #1d9bf0; }
        .metric { margin-bottom: 12px; }
        .metric-label { font-size: 13px; color: #71767b; margin-bottom: 4px; }
        .metric-value { font-size: 24px; font-weight: bold; }
        .metric-change { font-size: 14px; margin-left: 8px; }
        .positive { color: #00ba7c; }
        .negative { color: #f91880; }
        .neutral { color: #ffd400; }
        .status-indicator {
            display: inline-block;
            width: 10px;
            height: 10px;
            border-radius: 50%;
            margin-right: 8px;
        }
        .status-healthy { background: #00ba7c; }
        .status-warning { background: #ffd400; }
        .status-critical { background: #f91880; }
        .alert {
            background: #16181c;
            border-left: 3px solid #1d9bf0;
            padding: 12px;
            margin-bottom: 10px;
            border-radius: 4px;
            font-size: 13px;
        }
        .alert-WARNING { border-left-color: #ffd400; }
        .alert-CRITICAL { border-left-color: #f91880; }
        .alert-INFO { border-left-color: #1d9bf0; }
        .trade-row {
            display: flex;
            justify-content: space-between;
            padding: 10px;
            border-bottom: 1px solid #2f3336;
            font-size: 13px;
        }
        .trade-row:last-child { border-bottom: none; }
        .refresh-indicator {
            position: fixed;
            top: 20px;
            right: 20px;
            background: #16181c;
            padding: 8px 16px;
            border-radius: 20px;
            font-size: 12px;
            border: 1px solid #2f3336;
        }
        table { width: 100%; border-collapse: collapse; }
        th, td { text-align: left; padding: 10px; border-bottom: 1px solid #2f3336; }
        th { color: #71767b; font-weight: 600; font-size: 12px; text-transform: uppercase; }
        td { font-size: 13px; }
        .loading { text-align: center; padding: 40px; color: #71767b; }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>🤖 NIJA Trading Bot</h1>
            <div class="subtitle">Real-time monitoring dashboard</div>
        </div>

        <div class="refresh-indicator">
            <span id="refresh-status">Auto-refresh: ON</span>
        </div>

        <!-- Status Cards -->
        <div class="grid">
            <div class="card">
                <h2>💰 Balance</h2>
                <div class="metric">
                    <div class="metric-label">Current Balance</div>
                    <div class="metric-value" id="current-balance">$0.00</div>
                    <span class="metric-change" id="balance-change">+$0.00 (0%)</span>
                </div>
                <div class="metric">
                    <div class="metric-label">Peak Balance</div>
                    <div class="metric-value" id="peak-balance">$0.00</div>
                </div>
            </div>

            <div class="card">
                <h2>📊 Performance</h2>
                <div class="metric">
                    <div class="metric-label">Win Rate</div>
                    <div class="metric-value" id="win-rate">0%</div>
                </div>
                <div class="metric">
                    <div class="metric-label">Total Trades</div>
                    <div class="metric-value" id="total-trades">0</div>
                </div>
                <div class="metric">
                    <div class="metric-label">Net Profit</div>
                    <div class="metric-value" id="net-profit">$0.00</div>
                </div>
            </div>

            <div class="card">
                <h2>🔧 Health Status</h2>
                <div class="metric">
                    <div class="metric-label">Status</div>
                    <div class="metric-value">
                        <span class="status-indicator status-healthy" id="status-dot"></span>
                        <span id="status-text">Healthy</span>
                    </div>
                </div>
                <div class="metric">
                    <div class="metric-label">Uptime</div>
                    <div class="metric-value" id="uptime">0h</div>
                </div>
                <div class="metric">
                    <div class="metric-label">Error Rate</div>
                    <div class="metric-value" id="error-rate">0%</div>
                </div>
            </div>
        </div>

        <!-- Alerts -->
        <div class="card" style="margin-bottom: 20px;">
            <h2>🚨 Recent Alerts</h2>
            <div id="alerts-container" class="loading">Loading alerts...</div>
        </div>

        <!-- Recent Trades -->
        <div class="card">
            <h2>📈 Recent Trades</h2>
            <div id="trades-container" class="loading">Loading trades...</div>
        </div>
    </div>

    <script>
        // Auto-refresh every ${AUTO_REFRESH_INTERVAL} seconds
        const REFRESH_INTERVAL = """ + str(AUTO_REFRESH_INTERVAL * 1000) + """;  // milliseconds
        let lastUpdate = Date.now();

        async function fetchData(endpoint) {
            try {
                const response = await fetch(`/api/${endpoint}`);
                return await response.json();
            } catch (error) {
                console.error(`Error fetching ${endpoint}:`, error);
                return null;
            }
        }

        function formatCurrency(value) {
            return new Intl.NumberFormat('en-US', {
                style: 'currency',
                currency: 'USD'
            }).format(value);
        }

        function formatPercent(value) {
            return `${value >= 0 ? '+' : ''}${value.toFixed(1)}%`;
        }

        function updateStatus(data) {
            if (!data) return;

            // Balance
            document.getElementById('current-balance').textContent = formatCurrency(data.balance?.current || 0);
            document.getElementById('peak-balance').textContent = formatCurrency(data.balance?.peak || 0);

            const changeValue = (data.balance?.current || 0) - (data.balance?.start || 0);
            const changePct = data.balance?.change_pct || 0;
            const changeEl = document.getElementById('balance-change');
            changeEl.textContent = `${formatCurrency(changeValue)} (${formatPercent(changePct)})`;
            changeEl.className = `metric-change ${changeValue >= 0 ? 'positive' : 'negative'}`;

            // Performance
            document.getElementById('win-rate').textContent = `${(data.performance?.win_rate || 0).toFixed(1)}%`;
            document.getElementById('total-trades').textContent = data.performance?.total_trades || 0;

            const netProfit = data.performance?.net_profit || 0;
            const netProfitEl = document.getElementById('net-profit');
            netProfitEl.textContent = formatCurrency(netProfit);
            netProfitEl.className = `metric-value ${netProfit >= 0 ? 'positive' : 'negative'}`;

            // Health
            const status = data.status || 'unknown';
            document.getElementById('status-text').textContent = status.charAt(0).toUpperCase() + status.slice(1);

            const statusDot = document.getElementById('status-dot');
            statusDot.className = 'status-indicator';
            if (status === 'healthy') statusDot.classList.add('status-healthy');
            else if (status === 'warning') statusDot.classList.add('status-warning');
            else statusDot.classList.add('status-critical');

            const uptimeHours = (data.uptime_seconds || 0) / 3600;
            document.getElementById('uptime').textContent = `${uptimeHours.toFixed(1)}h`;
            document.getElementById('error-rate').textContent = `${(data.errors?.rate || 0).toFixed(1)}%`;
        }

        function updateAlerts(alerts) {
            const container = document.getElementById('alerts-container');
            if (!alerts || alerts.length === 0) {
                container.innerHTML = '<div style="padding: 20px; text-align: center; color: #71767b;">No alerts</div>';
                return;
            }

            container.innerHTML = alerts.slice(-10).reverse().map(alert => `
                <div class="alert alert-${alert.level}">
                    <strong>${alert.level}</strong> - ${alert.message}
                    <div style="font-size: 11px; color: #71767b; margin-top: 4px;">
                        ${new Date(alert.timestamp).toLocaleString()}
                    </div>
                </div>
            `).join('');
        }

        function updateTrades(trades) {
            const container = document.getElementById('trades-container');
            if (!trades || trades.length === 0) {
                container.innerHTML = '<div style="padding: 20px; text-align: center; color: #71767b;">No trades yet</div>';
                return;
            }

            container.innerHTML = `
                <table>
                    <thead>
                        <tr>
                            <th>Time</th>
                            <th>Symbol</th>
                            <th>Type</th>
                            <th>Entry</th>
                            <th>Exit</th>
                            <th>P&L</th>
                            <th>Fees</th>
                        </tr>
                    </thead>
                    <tbody>
                        ${trades.slice(-20).reverse().map(trade => `
                            <tr>
                                <td>${trade.entry_time ? new Date(trade.entry_time).toLocaleTimeString() : 'N/A'}</td>
                                <td>${trade.symbol || 'N/A'}</td>
                                <td>${trade.direction || 'N/A'}</td>
                                <td>${formatCurrency(trade.entry_price || 0)}</td>
                                <td>${formatCurrency(trade.exit_price || 0)}</td>
                                <td class="${(trade.net_profit || 0) >= 0 ? 'positive' : 'negative'}">
                                    ${formatCurrency(trade.net_profit || 0)}
                                </td>
                                <td>${formatCurrency(trade.total_fees || 0)}</td>
                            </tr>
                        `).join('')}
                    </tbody>
                </table>
            `;
        }

        async function refreshAll() {
            const [status, alerts, trades] = await Promise.all([
                fetchData('status'),
                fetchData('alerts'),
                fetchData('trades')
            ]);

            updateStatus(status);
            updateAlerts(alerts);
            updateTrades(trades);

            lastUpdate = Date.now();
            document.getElementById('refresh-status').textContent =
                `Last update: ${new Date().toLocaleTimeString()}`;
        }

        // Initial load
        refreshAll();

        // Auto-refresh
        setInterval(refreshAll, REFRESH_INTERVAL);
    </script>
</body>
</html>
"""

    (templates_dir / "dashboard.html").write_text(html_content)
    logger.info(f"✅ Dashboard template created at {templates_dir / 'dashboard.html'}")


def create_users_dashboard_html():
    """Create the users dashboard HTML template"""
    templates_dir = Path(__file__).parent / "templates"
    templates_dir.mkdir(exist_ok=True)

    html_content = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>NIJA Users Dashboard</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
            background: #0f1419;
            color: #e7e9ea;
            padding: 20px;
        }
        .container { max-width: 1600px; margin: 0 auto; }
        .header {
            background: linear-gradient(135deg, #1d4ed8 0%, #7c3aed 100%);
            padding: 30px;
            border-radius: 12px;
            margin-bottom: 20px;
            box-shadow: 0 4px 6px rgba(0,0,0,0.3);
        }
        .header h1 { font-size: 32px; margin-bottom: 5px; }
        .header .subtitle { opacity: 0.9; font-size: 14px; }
        .nav-links {
            margin-top: 15px;
        }
        .nav-links a {
            color: #e7e9ea;
            text-decoration: none;
            padding: 8px 16px;
            background: rgba(255,255,255,0.1);
            border-radius: 6px;
            margin-right: 10px;
            display: inline-block;
            font-size: 14px;
        }
        .nav-links a:hover {
            background: rgba(255,255,255,0.2);
        }
        .user-cards-grid {
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(380px, 1fr));
            gap: 20px;
            margin-bottom: 20px;
        }
        .user-card {
            background: #16181c;
            border: 2px solid #2f3336;
            border-radius: 12px;
            padding: 24px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.2);
            transition: transform 0.2s, border-color 0.2s;
        }
        .user-card:hover {
            transform: translateY(-2px);
            border-color: #1d9bf0;
        }
        .user-card.master-card {
            border: 2px solid #7c3aed;
            background: linear-gradient(135deg, rgba(29, 78, 216, 0.1) 0%, rgba(124, 58, 237, 0.1) 100%);
        }
        .user-card.master-card:hover {
            border-color: #7c3aed;
        }
        .user-card-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 20px;
            padding-bottom: 15px;
            border-bottom: 1px solid #2f3336;
        }
        .user-id {
            font-size: 20px;
            font-weight: bold;
            color: #1d9bf0;
        }
        .master-badge {
            background: linear-gradient(135deg, #7c3aed 0%, #1d4ed8 100%);
            color: white;
            padding: 4px 12px;
            border-radius: 12px;
            font-size: 11px;
            font-weight: bold;
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }
        .status-badge {
            display: inline-block;
            padding: 4px 10px;
            border-radius: 12px;
            font-size: 11px;
            font-weight: 600;
            text-transform: uppercase;
        }
        .status-active { background: #00ba7c; color: white; }
        .status-inactive { background: #f91880; color: white; }
        .metric-row {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 15px;
            margin-bottom: 12px;
        }
        .metric {
            background: #1c1f23;
            padding: 12px;
            border-radius: 8px;
        }
        .metric-label {
            font-size: 11px;
            color: #71767b;
            text-transform: uppercase;
            margin-bottom: 6px;
            font-weight: 600;
            letter-spacing: 0.5px;
        }
        .metric-value {
            font-size: 18px;
            font-weight: bold;
        }
        .metric-balance { color: #1d9bf0; }
        .metric-trades { color: #ffd400; }
        .metric-winrate { color: #00ba7c; }
        .metric-pnl-positive { color: #00ba7c; }
        .metric-pnl-negative { color: #f91880; }
        .metric-pnl-neutral { color: #71767b; }
        .recent-trades-section {
            margin-top: 20px;
            padding-top: 15px;
            border-top: 1px solid #2f3336;
        }
        .section-title {
            font-size: 13px;
            color: #71767b;
            text-transform: uppercase;
            margin-bottom: 10px;
            font-weight: 600;
            letter-spacing: 0.5px;
        }
        .trade-item {
            display: flex;
            justify-content: space-between;
            padding: 8px 0;
            font-size: 13px;
            border-bottom: 1px solid #2f3336;
        }
        .trade-item:last-child {
            border-bottom: none;
        }
        .trade-symbol {
            color: #e7e9ea;
            font-weight: 500;
        }
        .trade-pnl {
            font-weight: 600;
        }
        .loading {
            text-align: center;
            padding: 60px 20px;
            color: #71767b;
            font-size: 16px;
        }
        .error {
            background: rgba(249, 24, 128, 0.1);
            border: 1px solid #f91880;
            border-radius: 8px;
            padding: 20px;
            color: #f91880;
            text-align: center;
            margin: 20px 0;
        }
        .refresh-indicator {
            position: fixed;
            top: 20px;
            right: 20px;
            background: #16181c;
            padding: 8px 16px;
            border-radius: 20px;
            font-size: 12px;
            border: 1px solid #2f3336;
            z-index: 1000;
        }
        .no-data {
            text-align: center;
            padding: 40px;
            color: #71767b;
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>👥 NIJA Users Dashboard</h1>
            <div class="subtitle">Real-time user performance monitoring</div>
            <div class="nav-links">
                <a href="/">← Main Dashboard</a>
                <a href="/status">System Status</a>
            </div>
        </div>

        <div class="refresh-indicator">
            <span id="refresh-status">Auto-refresh: ON</span>
        </div>

        <div id="users-container">
            <div class="loading">⏳ Loading user data...</div>
        </div>
    </div>

    <script>
        const REFRESH_INTERVAL = 10000; // 10 seconds

        function formatCurrency(value) {
            return new Intl.NumberFormat('en-US', {
                style: 'currency',
                currency: 'USD',
                minimumFractionDigits: 2,
                maximumFractionDigits: 2
            }).format(value);
        }

        function formatPercent(value) {
            return `${value.toFixed(1)}%`;
        }

        function getPnLClass(value) {
            if (value > 0) return 'metric-pnl-positive';
            if (value < 0) return 'metric-pnl-negative';
            return 'metric-pnl-neutral';
        }

        function createUserCard(user) {
            const isMaster = user.is_master || user.user_id === 'master';
            const cardClass = isMaster ? 'user-card master-card' : 'user-card';

            return `
                <div class="${cardClass}">
                    <div class="user-card-header">
                        <div class="user-id">
                            ${user.user_id}
                            ${isMaster ? '<span class="master-badge">👑 Master</span>' : ''}
                        </div>
                        <span class="status-badge status-${user.can_trade ? 'active' : 'inactive'}">
                            ${user.can_trade ? '✓ Active' : '✗ Inactive'}
                        </span>
                    </div>

                    <div class="metric-row">
                        <div class="metric">
                            <div class="metric-label">Balance</div>
                            <div class="metric-value metric-balance">
                                ${formatCurrency(user.balance || 0)}
                            </div>
                        </div>
                        <div class="metric">
                            <div class="metric-label">Total Trades</div>
                            <div class="metric-value metric-trades">
                                ${user.total_trades || 0}
                            </div>
                        </div>
                    </div>

                    <div class="metric-row">
                        <div class="metric">
                            <div class="metric-label">Win Rate</div>
                            <div class="metric-value metric-winrate">
                                ${formatPercent(user.win_rate || 0)}
                            </div>
                        </div>
                        <div class="metric">
                            <div class="metric-label">Daily P&L</div>
                            <div class="metric-value ${getPnLClass(user.daily_pnl || 0)}">
                                ${formatCurrency(user.daily_pnl || 0)}
                            </div>
                        </div>
                    </div>

                    <div class="metric-row">
                        <div class="metric" style="grid-column: 1 / -1;">
                            <div class="metric-label">Total P&L</div>
                            <div class="metric-value ${getPnLClass(user.total_pnl || 0)}">
                                ${formatCurrency(user.total_pnl || 0)}
                            </div>
                        </div>
                    </div>

                    <div class="recent-trades-section" id="trades-${user.user_id}">
                        <div class="section-title">Recent Trades</div>
                        <div class="no-data">Loading trades...</div>
                    </div>
                </div>
            `;
        }

        async function loadRecentTrades(userId) {
            try {
                const response = await fetch(`/api/user/${userId}/pnl`);
                const data = await response.json();

                const tradesContainer = document.getElementById(`trades-${userId}`);
                if (!tradesContainer) return;

                const recentTrades = data.recent_trades || [];

                if (recentTrades.length === 0) {
                    tradesContainer.innerHTML = `
                        <div class="section-title">Recent Trades</div>
                        <div class="no-data">No recent trades</div>
                    `;
                    return;
                }

                const tradesHTML = recentTrades.slice(0, 5).map(trade => `
                    <div class="trade-item">
                        <span class="trade-symbol">${trade.symbol || 'N/A'}</span>
                        <span class="trade-pnl ${getPnLClass(trade.pnl_usd || 0)}">
                            ${formatCurrency(trade.pnl_usd || 0)}
                        </span>
                    </div>
                `).join('');

                tradesContainer.innerHTML = `
                    <div class="section-title">Recent Trades</div>
                    ${tradesHTML}
                `;
            } catch (error) {
                console.error(`Error loading trades for ${userId}:`, error);
            }
        }

        async function refreshUsers() {
            try {
                // Fetch users with master included
                const response = await fetch('/api/users?include_master=true');
                const data = await response.json();

                const container = document.getElementById('users-container');

                if (!data.users || data.users.length === 0) {
                    container.innerHTML = '<div class="no-data">No users found</div>';
                    return;
                }

                // Sort: master first, then alphabetically
                const sortedUsers = data.users.sort((a, b) => {
                    if (a.is_master || a.user_id === 'master') return -1;
                    if (b.is_master || b.user_id === 'master') return 1;
                    return a.user_id.localeCompare(b.user_id);
                });

                container.innerHTML = `
                    <div class="user-cards-grid">
                        ${sortedUsers.map(user => createUserCard(user)).join('')}
                    </div>
                `;

                // Load recent trades for each user
                sortedUsers.forEach(user => loadRecentTrades(user.user_id));

                document.getElementById('refresh-status').textContent =
                    `Last update: ${new Date().toLocaleTimeString()}`;

            } catch (error) {
                console.error('Error loading users:', error);
                document.getElementById('users-container').innerHTML = `
                    <div class="error">
                        <strong>Error loading user data</strong><br>
                        ${error.message}
                    </div>
                `;
            }
        }

        // Initial load
        refreshUsers();

        // Auto-refresh
        setInterval(refreshUsers, REFRESH_INTERVAL);
    </script>
</body>
</html>
"""

    (templates_dir / "users_dashboard.html").write_text(html_content)
    logger.info(f"✅ Users dashboard template created at {templates_dir / 'users_dashboard.html'}")


@app.route('/api/activity/recent')
def get_recent_activity():
    """Get recent activity feed events."""
    try:
        if not get_activity_feed:
            return jsonify({'error': 'Activity feed not available'}), 503

        # Get query parameters
        n = request.args.get('limit', default=100, type=int)
        event_type = request.args.get('type', default=None, type=str)
        symbol = request.args.get('symbol', default=None, type=str)

        activity_feed = get_activity_feed()
        events = activity_feed.get_recent_events(n=n, event_type=event_type, symbol=symbol)

        return jsonify({
            'events': events,
            'count': len(events),
            'timestamp': datetime.now().isoformat()
        })

    except Exception as e:
        logger.error(f"Error getting recent activity: {e}")
        return jsonify({'error': 'Failed to retrieve recent activity'}), 500


@app.route('/api/activity/summary')
def get_activity_summary():
    """Get activity feed summary statistics."""
    try:
        if not get_activity_feed:
            return jsonify({'error': 'Activity feed not available'}), 503

        hours = request.args.get('hours', default=24, type=int)

        activity_feed = get_activity_feed()
        summary = activity_feed.get_activity_summary(hours=hours)

        return jsonify(summary)

    except Exception as e:
        logger.error(f"Error getting activity summary: {e}")
        return jsonify({'error': 'Failed to retrieve activity summary'}), 500


@app.route('/api/activity/rejections')
def get_rejection_reasons():
    """Get reasons why trades were rejected."""
    try:
        if not get_activity_feed:
            return jsonify({'error': 'Activity feed not available'}), 503

        hours = request.args.get('hours', default=24, type=int)

        activity_feed = get_activity_feed()
        reasons = activity_feed.get_rejection_reasons(hours=hours)

        # Convert to sorted list for easier display
        reasons_list = [
            {'reason': reason, 'count': count}
            for reason, count in sorted(reasons.items(), key=lambda x: x[1], reverse=True)
        ]

        return jsonify({
            'rejection_reasons': reasons_list,
            'total_rejections': sum(reasons.values()),
            'period_hours': hours,
            'timestamp': datetime.now().isoformat()
        })

    except Exception as e:
        logger.error(f"Error getting rejection reasons: {e}")
        return jsonify({'error': 'Failed to retrieve rejection reasons'}), 500


@app.route('/api/positions/live')
def get_live_positions():
    """Get live position mirror (real-time positions)."""
    try:
        if not get_position_mirror:
            return jsonify({'error': 'Position mirror not available'}), 503

        position_mirror = get_position_mirror()
        positions = position_mirror.get_all_positions()

        return jsonify({
            'positions': [pos.to_dict() for pos in positions],
            'count': len(positions),
            'timestamp': datetime.now().isoformat()
        })

    except Exception as e:
        logger.error(f"Error getting live positions: {e}")
        return jsonify({'error': 'Failed to retrieve live positions'}), 500


@app.route('/api/positions/summary')
def get_positions_summary():
    """Get portfolio summary from position mirror."""
    try:
        if not get_position_mirror:
            return jsonify({'error': 'Position mirror not available'}), 503

        position_mirror = get_position_mirror()
        summary = position_mirror.get_portfolio_summary()

        return jsonify(summary)

    except Exception as e:
        logger.error(f"Error getting positions summary: {e}")
        return jsonify({'error': 'Failed to retrieve positions summary'}), 500


@app.route('/api/positions/broker/<broker>')
def get_positions_by_broker(broker: str):
    """Get positions for a specific broker."""
    try:
        if not get_position_mirror:
            return jsonify({'error': 'Position mirror not available'}), 503

        position_mirror = get_position_mirror()
        positions = position_mirror.get_positions_by_broker(broker)

        return jsonify({
            'broker': broker,
            'positions': [pos.to_dict() for pos in positions],
            'count': len(positions),
            'timestamp': datetime.now().isoformat()
        })

    except Exception as e:
        logger.error(f"Error getting positions for {broker}: {e}")
        return jsonify({'error': 'Failed to retrieve broker positions'}), 500


@app.route('/reports/aggregated')
def aggregated_report():
    """Aggregated read-only report page for stakeholders."""
    return render_template('aggregated_report.html')


@app.route('/api/aggregated/summary')
def get_aggregated_summary():
    """
    Get aggregated read-only summary of master + all users.

    Returns:
        - Master account performance
        - Combined user performance
        - Total portfolio metrics
        - System-wide statistics
    """
    try:
        if not get_user_pnl_tracker or not get_user_risk_manager:
            return jsonify({'error': 'Required modules not available'}), 503

        pnl_tracker = get_user_pnl_tracker()
        risk_manager = get_user_risk_manager()

        # Get master stats
        master_stats = pnl_tracker.get_stats('master', force_refresh=True)
        master_risk_state = risk_manager.get_state('master')

        # Get all user stats (excluding master)
        all_user_ids = set()
        for user_id in risk_manager._user_states.keys():
            if user_id != 'master':
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

            if get_hard_controls:
                hard_controls = get_hard_controls()
                can_trade, reason = hard_controls.can_trade(user_id)
                if can_trade:
                    users_can_trade += 1
            else:
                can_trade = True
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

        # Portfolio totals
        portfolio_balance = master_risk_state.balance + total_user_balance
        portfolio_pnl = master_stats.get('total_pnl', 0.0) + total_user_pnl

        return jsonify({
            'timestamp': datetime.now().isoformat(),
            'master_account': {
                'balance': master_risk_state.balance,
                'total_pnl': master_stats.get('total_pnl', 0.0),
                'daily_pnl': master_stats.get('daily_pnl', 0.0),
                'win_rate': master_stats.get('win_rate', 0.0),
                'total_trades': master_stats.get('completed_trades', 0),
                'winning_trades': master_stats.get('winning_trades', 0),
                'losing_trades': master_stats.get('losing_trades', 0)
            },
            'users_aggregate': {
                'total_users': total_users,
                'active_users': users_can_trade,
                'total_balance': total_user_balance,
                'total_pnl': total_user_pnl,
                'total_trades': total_user_trades,
                'winning_trades': total_user_wins,
                'losing_trades': total_user_losses,
                'aggregate_win_rate': aggregate_win_rate
            },
            'portfolio_totals': {
                'total_balance': portfolio_balance,
                'total_pnl': portfolio_pnl,
                'total_trades': master_stats.get('completed_trades', 0) + total_user_trades,
                'pnl_return_pct': (portfolio_pnl / portfolio_balance * 100) if portfolio_balance > 0 else 0.0
            },
            'user_details': user_summaries
        })

    except Exception as e:
        logger.error(f"Error getting aggregated summary: {e}")
        return jsonify({'error': 'Failed to retrieve aggregated summary'}), 500


@app.route('/api/restart', methods=['POST'])
def restart_bot():
    """
    Restart the NIJA trading bot.

    This endpoint sends a SIGTERM signal to the bot process, causing it
    to shut down gracefully. The deployment platform (Railway/Render) will
    automatically restart the bot.

    Returns:
        JSON response with restart status
    """
    try:
        # Find the bot.py process
        bot_pid = None
        current_pid = os.getpid()

        for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
            try:
                cmdline = proc.info.get('cmdline', [])
                if cmdline and len(cmdline) > 1:
                    # Look for python process running bot.py specifically (not chatbot.py, mybot.py, etc.)
                    # Check for exact filename match with path separator or as last argument
                    if 'python' in cmdline[0].lower():
                        for arg in cmdline:
                            # Match only if it ends with /bot.py or is exactly bot.py
                            if arg.endswith('/bot.py') or arg == 'bot.py':
                                # Don't kill ourselves (dashboard server)
                                if proc.info['pid'] != current_pid:
                                    bot_pid = proc.info['pid']
                                    break
                        if bot_pid:
                            break
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue

        if bot_pid:
            logger.info(f"🔄 Restart requested - sending SIGTERM to bot process {bot_pid}")
            os.kill(bot_pid, sig.SIGTERM)
            return jsonify({
                'success': True,
                'message': 'Restart signal sent to NIJA bot',
                'pid': bot_pid,
                'timestamp': datetime.now().isoformat()
            })
        else:
            logger.warning("⚠️ Restart requested but bot process not found")
            return jsonify({
                'success': False,
                'message': 'Bot process not found - it may not be running',
                'timestamp': datetime.now().isoformat()
            }), 404

    except Exception as e:
        logger.error(f"Error restarting bot: {e}")
        return jsonify({
            'success': False,
            'error': 'Failed to restart bot',
            'timestamp': datetime.now().isoformat()
        }), 500


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    # Create templates
    create_dashboard_html()
    create_users_dashboard_html()

    # Ensure data directory exists
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    # Register Command Center routes
    if register_command_center_routes:
        register_command_center_routes(app)
        logger.info("✅ Command Center routes registered")
    else:
        logger.warning("⚠️ Command Center routes not available")

    print("🚀 Starting NIJA Dashboard Server...")
    print("📊 Dashboard will be available at: http://localhost:5001")
    print("👥 Users Dashboard: http://localhost:5001/users")
    print("⚡ Command Center: http://localhost:5001/command-center")
    print(f"🔄 Auto-refresh every {AUTO_REFRESH_INTERVAL} seconds")
    print("\nPress Ctrl+C to stop\n")

    app.run(host='0.0.0.0', port=5001, debug=False)
