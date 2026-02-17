"""
NIJA MICRO_CAP Production Readiness Dashboard API

Flask API backend for the MICRO_CAP Production Readiness Dashboard.
Provides real-time metrics for monitoring the first 50 trades including:
- Balances (cash, equity, available capital)
- Held capital (open positions value)
- Open orders (active positions)
- Expectancy metrics (win rate, profit factor)
- Drawdown tracking (current/max drawdown)
- Compliance alerts (risk violations, position limits)

Author: NIJA Trading Systems
Version: 1.0
Date: February 17, 2026
"""

from flask import Flask, jsonify, send_file
from flask_cors import CORS
import logging
from typing import Dict, Any, List, Optional
from datetime import datetime
import os

logger = logging.getLogger(__name__)

# Try to import bot components
try:
    from bot.broker_integration import get_broker_integration
    BROKER_AVAILABLE = True
except ImportError:
    logger.warning("broker_integration not available - using mock data")
    BROKER_AVAILABLE = False

try:
    from bot.kpi_tracker import get_kpi_tracker
    KPI_AVAILABLE = True
except ImportError:
    logger.warning("kpi_tracker not available - using mock data")
    KPI_AVAILABLE = False

try:
    from bot.risk_manager import AdaptiveRiskManager
    RISK_MANAGER_AVAILABLE = True
except ImportError:
    logger.warning("risk_manager not available - using mock data")
    RISK_MANAGER_AVAILABLE = False


class MicroCapDashboardAPI:
    """
    API for MICRO_CAP Production Readiness Dashboard
    
    Provides real-time metrics for the first 50 trades monitoring.
    """
    
    def __init__(self):
        """Initialize dashboard API"""
        self.broker = None
        self.kpi_tracker = None
        self.risk_manager = None
        
        # Try to initialize components
        if BROKER_AVAILABLE:
            try:
                self.broker = get_broker_integration()
            except Exception as e:
                logger.warning(f"Could not initialize broker: {e}")
        
        if KPI_AVAILABLE:
            try:
                self.kpi_tracker = get_kpi_tracker()
            except Exception as e:
                logger.warning(f"Could not initialize KPI tracker: {e}")
        
        if RISK_MANAGER_AVAILABLE:
            try:
                self.risk_manager = AdaptiveRiskManager()
            except Exception as e:
                logger.warning(f"Could not initialize risk manager: {e}")
        
        logger.info("✅ MICRO_CAP Dashboard API initialized")
    
    def get_balances(self) -> Dict[str, float]:
        """
        Get current account balances
        
        Returns:
            Dictionary with cash, equity, available, and reserved balances
        """
        if self.broker:
            try:
                balance = self.broker.get_balance()
                cash = balance.get('cash', 0.0)
                equity = balance.get('equity', cash)
                
                # Calculate reserved buffer (15% for MICRO_CAP)
                reserved = equity * 0.15
                available = cash - reserved
                
                return {
                    'cash': cash,
                    'equity': equity,
                    'available': max(available, 0.0),
                    'reserved': reserved
                }
            except Exception as e:
                logger.error(f"Error getting balances: {e}")
        
        # Return mock data if broker unavailable
        return {
            'cash': 50.00,
            'equity': 52.50,
            'available': 42.50,
            'reserved': 7.50
        }
    
    def get_held_capital(self) -> Dict[str, Any]:
        """
        Get held capital information (open positions)
        
        Returns:
            Dictionary with positions value, count, unrealized P&L, exposure %
        """
        if self.broker:
            try:
                positions = self.broker.get_open_positions()
                
                total_value = 0.0
                unrealized_pnl = 0.0
                count = len(positions)
                
                for pos in positions:
                    total_value += pos.get('market_value', 0.0)
                    unrealized_pnl += pos.get('unrealized_pnl', 0.0)
                
                balance = self.get_balances()
                equity = balance.get('equity', 0.0)
                exposure_pct = (total_value / equity * 100) if equity > 0 else 0.0
                
                return {
                    'value': total_value,
                    'count': count,
                    'unrealized_pnl': unrealized_pnl,
                    'exposure_pct': exposure_pct
                }
            except Exception as e:
                logger.error(f"Error getting held capital: {e}")
        
        # Return mock data if broker unavailable
        return {
            'value': 10.00,
            'count': 1,
            'unrealized_pnl': 0.50,
            'exposure_pct': 19.0
        }
    
    def get_open_orders(self) -> List[Dict[str, Any]]:
        """
        Get list of open orders/positions
        
        Returns:
            List of position dictionaries
        """
        if self.broker:
            try:
                positions = self.broker.get_open_positions()
                
                orders = []
                for pos in positions:
                    entry_price = pos.get('entry_price', 0.0)
                    current_price = pos.get('current_price', entry_price)
                    size = pos.get('size', 0.0)
                    
                    pnl = (current_price - entry_price) * size
                    pnl_pct = ((current_price - entry_price) / entry_price * 100) if entry_price > 0 else 0.0
                    
                    orders.append({
                        'symbol': pos.get('symbol', 'UNKNOWN'),
                        'side': pos.get('side', 'buy'),
                        'size': size,
                        'entry_price': entry_price,
                        'current_price': current_price,
                        'pnl': pnl,
                        'pnl_pct': pnl_pct
                    })
                
                return orders
            except Exception as e:
                logger.error(f"Error getting open orders: {e}")
        
        # Return mock data if broker unavailable
        return [
            {
                'symbol': 'BTC-USD',
                'side': 'buy',
                'size': 0.0002,
                'entry_price': 50000.00,
                'current_price': 50250.00,
                'pnl': 0.50,
                'pnl_pct': 0.50
            }
        ]
    
    def get_expectancy(self) -> Dict[str, float]:
        """
        Get expectancy metrics
        
        Returns:
            Dictionary with win rate, profit factor, avg win/loss
        """
        if self.kpi_tracker:
            try:
                kpi_summary = self.kpi_tracker.get_kpi_summary()
                
                return {
                    'win_rate': kpi_summary.get('win_rate_pct', 0.0),
                    'profit_factor': kpi_summary.get('profit_factor', 0.0),
                    'avg_win': kpi_summary.get('avg_win', 0.0),
                    'avg_loss': kpi_summary.get('avg_loss', 0.0)
                }
            except Exception as e:
                logger.error(f"Error getting expectancy: {e}")
        
        # Return mock data if KPI tracker unavailable
        return {
            'win_rate': 65.0,
            'profit_factor': 1.85,
            'avg_win': 2.50,
            'avg_loss': -1.35
        }
    
    def get_drawdown(self) -> Dict[str, float]:
        """
        Get drawdown metrics
        
        Returns:
            Dictionary with current drawdown, max drawdown, peak balance
        """
        if self.kpi_tracker:
            try:
                kpi_summary = self.kpi_tracker.get_kpi_summary()
                balances = self.get_balances()
                
                current_drawdown = kpi_summary.get('current_drawdown_pct', 0.0)
                max_drawdown = kpi_summary.get('max_drawdown_pct', 0.0)
                
                # Calculate peak balance from current equity and drawdown
                equity = balances.get('equity', 0.0)
                peak_balance = equity / (1 - abs(current_drawdown) / 100) if current_drawdown < 0 else equity
                
                return {
                    'current': current_drawdown,
                    'max': max_drawdown,
                    'peak_balance': peak_balance
                }
            except Exception as e:
                logger.error(f"Error getting drawdown: {e}")
        
        # Return mock data if KPI tracker unavailable
        return {
            'current': -2.5,
            'max': -4.8,
            'peak_balance': 55.00
        }
    
    def get_trades_info(self) -> Dict[str, int]:
        """
        Get trade count information
        
        Returns:
            Dictionary with total trades, winning trades, losing trades
        """
        if self.kpi_tracker:
            try:
                kpi_summary = self.kpi_tracker.get_kpi_summary()
                
                return {
                    'total_trades': kpi_summary.get('total_trades', 0),
                    'winning_trades': kpi_summary.get('winning_trades', 0),
                    'losing_trades': kpi_summary.get('losing_trades', 0)
                }
            except Exception as e:
                logger.error(f"Error getting trades info: {e}")
        
        # Return mock data if KPI tracker unavailable
        return {
            'total_trades': 8,
            'winning_trades': 5,
            'losing_trades': 3
        }
    
    def get_compliance_alerts(self) -> List[Dict[str, str]]:
        """
        Get compliance alerts
        
        Returns:
            List of alert dictionaries with severity and message
        """
        alerts = []
        
        # Check drawdown limit
        drawdown = self.get_drawdown()
        current_dd = abs(drawdown.get('current', 0.0))
        
        if current_dd > 12.0:
            alerts.append({
                'severity': 'error',
                'message': f'Drawdown limit exceeded: {current_dd:.1f}% (limit: 12.0%)'
            })
        elif current_dd > 10.0:
            alerts.append({
                'severity': 'warning',
                'message': f'Approaching drawdown limit: {current_dd:.1f}% (limit: 12.0%)'
            })
        
        # Check position limits
        held_capital = self.get_held_capital()
        position_count = held_capital.get('count', 0)
        
        if position_count > 2:
            alerts.append({
                'severity': 'error',
                'message': f'Position limit exceeded: {position_count} positions (limit: 2 for MICRO_CAP)'
            })
        
        # Check exposure
        exposure_pct = held_capital.get('exposure_pct', 0.0)
        if exposure_pct > 40.0:
            alerts.append({
                'severity': 'warning',
                'message': f'High exposure: {exposure_pct:.1f}% (recommended max: 40%)'
            })
        
        # Check minimum balance
        balances = self.get_balances()
        cash = balances.get('cash', 0.0)
        
        if cash < 15.0:
            alerts.append({
                'severity': 'error',
                'message': f'Below minimum balance: ${cash:.2f} (minimum: $15.00)'
            })
        elif cash < 20.0:
            alerts.append({
                'severity': 'warning',
                'message': f'Low balance: ${cash:.2f} (minimum: $15.00)'
            })
        
        return alerts
    
    def get_dashboard_data(self) -> Dict[str, Any]:
        """
        Get complete dashboard data
        
        Returns:
            Dictionary with all dashboard metrics
        """
        return {
            'timestamp': datetime.now().isoformat(),
            'balances': self.get_balances(),
            'held_capital': self.get_held_capital(),
            'open_orders': self.get_open_orders(),
            'expectancy': self.get_expectancy(),
            'drawdown': self.get_drawdown(),
            'trades': self.get_trades_info(),
            'compliance_alerts': self.get_compliance_alerts()
        }


def create_app() -> Flask:
    """
    Create and configure Flask application
    
    Returns:
        Configured Flask application
    """
    app = Flask(__name__)
    CORS(app)
    
    # Initialize dashboard API
    dashboard_api = MicroCapDashboardAPI()
    
    @app.route('/api/v1/dashboard/micro-cap', methods=['GET'])
    def get_dashboard_data():
        """Get complete dashboard data"""
        try:
            data = dashboard_api.get_dashboard_data()
            return jsonify(data)
        except Exception as e:
            logger.error(f"Error in get_dashboard_data: {e}")
            return jsonify({'error': 'Internal server error'}), 500
    
    @app.route('/api/v1/dashboard/micro-cap/balances', methods=['GET'])
    def get_balances():
        """Get balances only"""
        try:
            data = dashboard_api.get_balances()
            return jsonify(data)
        except Exception as e:
            logger.error(f"Error in get_balances: {e}")
            return jsonify({'error': 'Internal server error'}), 500
    
    @app.route('/api/v1/dashboard/micro-cap/held-capital', methods=['GET'])
    def get_held_capital():
        """Get held capital only"""
        try:
            data = dashboard_api.get_held_capital()
            return jsonify(data)
        except Exception as e:
            logger.error(f"Error in get_held_capital: {e}")
            return jsonify({'error': 'Internal server error'}), 500
    
    @app.route('/api/v1/dashboard/micro-cap/expectancy', methods=['GET'])
    def get_expectancy():
        """Get expectancy metrics only"""
        try:
            data = dashboard_api.get_expectancy()
            return jsonify(data)
        except Exception as e:
            logger.error(f"Error in get_expectancy: {e}")
            return jsonify({'error': 'Internal server error'}), 500
    
    @app.route('/api/v1/dashboard/micro-cap/drawdown', methods=['GET'])
    def get_drawdown():
        """Get drawdown metrics only"""
        try:
            data = dashboard_api.get_drawdown()
            return jsonify(data)
        except Exception as e:
            logger.error(f"Error in get_drawdown: {e}")
            return jsonify({'error': 'Internal server error'}), 500
    
    @app.route('/api/v1/dashboard/micro-cap/compliance', methods=['GET'])
    def get_compliance():
        """Get compliance alerts only"""
        try:
            data = dashboard_api.get_compliance_alerts()
            return jsonify(data)
        except Exception as e:
            logger.error(f"Error in get_compliance: {e}")
            return jsonify({'error': 'Internal server error'}), 500
    
    @app.route('/dashboard', methods=['GET'])
    def serve_dashboard():
        """Serve the dashboard HTML"""
        dashboard_path = os.path.join(os.path.dirname(__file__), 'micro_cap_dashboard.html')
        return send_file(dashboard_path)
    
    @app.route('/health', methods=['GET'])
    def health_check():
        """Health check endpoint"""
        return jsonify({
            'status': 'healthy',
            'timestamp': datetime.now().isoformat()
        })
    
    return app


if __name__ == '__main__':
    import sys
    
    # Set up logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    # Create and run app
    app = create_app()
    port = int(os.getenv('DASHBOARD_PORT', '5002'))
    
    logger.info(f"🚀 Starting MICRO_CAP Dashboard API on port {port}")
    logger.info(f"📊 Dashboard URL: http://localhost:{port}/dashboard")
    logger.info(f"🔌 API URL: http://localhost:{port}/api/v1/dashboard/micro-cap")
    
    app.run(host='0.0.0.0', port=port, debug=False)
