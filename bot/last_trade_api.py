"""
Last Evaluated Trade API
Provides real-time access to the most recent trade signal evaluation
for UI display panels and monitoring dashboards.
"""

from flask import Flask, jsonify
import logging
import os
from typing import Optional

logger = logging.getLogger("nija.last_trade_api")

# Global reference to trading strategy instance
_strategy_instance: Optional[object] = None


def register_strategy(strategy):
    """
    Register the trading strategy instance for API access.
    
    Args:
        strategy: TradingStrategy instance with get_last_evaluated_trade() method
    """
    global _strategy_instance
    _strategy_instance = strategy
    logger.info("✅ Trading strategy registered with Last Evaluated Trade API")


def create_last_trade_api(port: int = None) -> Flask:
    """
    Create Flask API for accessing last evaluated trade information.
    
    Args:
        port: Port to run API on (default: from PORT env var or 5001)
        
    Returns:
        Flask app instance
    """
    app = Flask(__name__)
    
    if port is None:
        port = int(os.getenv('LAST_TRADE_API_PORT', '5001'))
    
    @app.route('/api/last-trade', methods=['GET'])
    def get_last_trade():
        """
        Get the last evaluated trade.
        
        Returns:
            JSON with trade details or error message
        """
        if _strategy_instance is None:
            return jsonify({
                'error': 'Strategy not initialized',
                'message': 'Trading strategy has not been registered with API'
            }), 503
        
        try:
            trade_data = _strategy_instance.get_last_evaluated_trade()
            return jsonify({
                'success': True,
                'data': trade_data
            })
        except Exception as e:
            logger.error(f"Error getting last evaluated trade: {e}")
            return jsonify({
                'error': 'Internal error',
                'message': str(e)
            }), 500
    
    @app.route('/api/health', methods=['GET'])
    def health():
        """Health check endpoint."""
        return jsonify({
            'status': 'healthy',
            'api': 'last-trade',
            'strategy_registered': _strategy_instance is not None
        })
    
    @app.route('/api/dry-run-status', methods=['GET'])
    def dry_run_status():
        """
        Check if bot is in dry-run mode.
        
        Returns:
            JSON with dry-run mode status
        """
        if _strategy_instance is None:
            return jsonify({
                'error': 'Strategy not initialized'
            }), 503
        
        dry_run = getattr(_strategy_instance, 'dry_run_mode', False)
        return jsonify({
            'dry_run_mode': dry_run,
            'message': 'Simulated trading - no real orders' if dry_run else 'Live trading mode'
        })
    
    return app


def start_last_trade_api_server(strategy, port: int = None, background: bool = True):
    """
    Start the Last Trade API server.
    
    Args:
        strategy: TradingStrategy instance
        port: Port to run on (default: 5001)
        background: If True, run in background thread
    """
    register_strategy(strategy)
    app = create_last_trade_api(port)
    
    if port is None:
        port = int(os.getenv('LAST_TRADE_API_PORT', '5001'))
    
    if background:
        import threading
        def run_server():
            app.run(host='0.0.0.0', port=port, debug=False)
        
        thread = threading.Thread(target=run_server, daemon=True)
        thread.start()
        logger.info(f"🌐 Last Trade API server started on port {port} (background)")
    else:
        logger.info(f"🌐 Starting Last Trade API server on port {port}...")
        app.run(host='0.0.0.0', port=port, debug=False)


# Example usage for testing
if __name__ == '__main__':
    # Mock strategy for testing
    class MockStrategy:
        def __init__(self):
            self.dry_run_mode = False
            self.last_evaluated_trade = {
                'timestamp': '2026-02-02T23:30:00',
                'symbol': 'BTC-USD',
                'signal': 'BUY',
                'action': 'vetoed',
                'veto_reasons': ['Insufficient balance ($15.00 < $25.00)'],
                'entry_price': 42500.00,
                'position_size': 50.00,
                'broker': 'KRAKEN',
                'confidence': 0.85,
                'rsi_9': 35.2,
                'rsi_14': 38.7
            }
        
        def get_last_evaluated_trade(self):
            return self.last_evaluated_trade
    
    # Start test server
    mock_strategy = MockStrategy()
    print("Starting test server on http://localhost:5001")
    print("Test endpoints:")
    print("  - GET http://localhost:5001/api/last-trade")
    print("  - GET http://localhost:5001/api/health")
    print("  - GET http://localhost:5001/api/dry-run-status")
    start_last_trade_api_server(mock_strategy, port=5001, background=False)
