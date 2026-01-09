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

from flask import Flask, render_template, jsonify
import json
import logging
import os
import sys
from pathlib import Path
from datetime import datetime, timedelta

# Add bot directory to path for imports
sys.path.insert(0, os.path.dirname(__file__))

app = Flask(__name__)
logger = logging.getLogger(__name__)

# Data directory
DATA_DIR = Path("/tmp/nija_monitoring")


@app.route('/')
def index():
    """Main dashboard page"""
    return render_template('dashboard.html')


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
        # Try to load from trade history
        trade_file = Path("/usr/src/app/data/trade_history.json")
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
            log_file = Path("/usr/src/app/nija.log")
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
            journal_file = Path("../trade_journal.jsonl")
            alt_journal = Path("/usr/src/app/trade_journal.jsonl")
            
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
        
        # Check 4: User-specific trading status (if multi-user system available)
        try:
            from auth import get_user_manager
            from controls import get_hard_controls
            
            user_mgr = get_user_manager()
            controls = get_hard_controls()
            
            # Get all users
            all_users = user_mgr.list_users() if hasattr(user_mgr, 'list_users') else []
            
            for user_id in all_users:
                user = user_mgr.get_user(user_id)
                if user:
                    can_trade, error = controls.can_trade(user_id)
                    status["users"].append({
                        "user_id": user_id,
                        "email": user.get('email', 'N/A'),
                        "enabled": user.get('enabled', False),
                        "can_trade": can_trade,
                        "tier": user.get('subscription_tier', 'N/A'),
                        "trading_blocked_reason": error if not can_trade else None
                    })
        except ImportError:
            # Multi-user system not available
            status["users"] = None
        except Exception as e:
            status["errors"].append(f"User check failed: {str(e)}")
        
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
        <h2 style="margin-top: 30px; color: #1d9bf0;">User Trading Status</h2>
        <div class="user-list">"""
            for user in data['users']:
                status_icon = "✅" if user.get('can_trade') and user.get('enabled') else "❌"
                html += """
            <div class="user-item">
                """ + status_icon + """ <strong>""" + user.get('user_id', 'Unknown') + """</strong> (""" + user.get('email', 'N/A') + """)<br>
                Tier: """ + user.get('tier', 'N/A') + """ | Enabled: """ + str(user.get('enabled', False)) + """ | Can Trade: """ + str(user.get('can_trade', False)) + """
            </div>"""
            html += "</div>"
        
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
        // Auto-refresh every 5 seconds
        const REFRESH_INTERVAL = 5000;
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


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    
    # Create template
    create_dashboard_html()
    
    # Ensure data directory exists
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    
    print("🚀 Starting NIJA Dashboard Server...")
    print("📊 Dashboard will be available at: http://localhost:5001")
    print("🔄 Auto-refresh every 5 seconds")
    print("\nPress Ctrl+C to stop\n")
    
    app.run(host='0.0.0.0', port=5001, debug=False)
