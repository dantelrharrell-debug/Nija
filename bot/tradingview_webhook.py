"""
TradingView Webhook Integration for NIJA
Receives alerts from TradingView and executes trades on Coinbase
"""

from flask import Flask, request, jsonify
import json
import os
import sys
import re
from datetime import datetime

# Add bot directory to path
sys.path.insert(0, os.path.dirname(__file__))

from coinbase.rest import RESTClient
from trading_strategy import TradingStrategy

app = Flask(__name__)

# Security constants
MAX_ORDERS_PER_REQUEST = 5
SYMBOL_PATTERN = re.compile(r'^[A-Z0-9]{1,10}-USD$')

# Initialize Coinbase client and strategy
client = RESTClient(
    api_key=os.getenv('COINBASE_API_KEY'),
    api_secret=os.getenv('COINBASE_API_SECRET')
)
strategy = TradingStrategy(client, paper_mode=False)

# Webhook secret for security - REQUIRED environment variable
WEBHOOK_SECRET = os.getenv('TRADINGVIEW_WEBHOOK_SECRET')
if not WEBHOOK_SECRET:
    raise ValueError(
        "TRADINGVIEW_WEBHOOK_SECRET environment variable is required. "
        "Generate a secure secret: openssl rand -hex 32"
    )
if len(WEBHOOK_SECRET) < 32:
    raise ValueError(
        "TRADINGVIEW_WEBHOOK_SECRET must be at least 32 characters for security."
    )

def validate_position_size(position_size, client):
    """
    Validate position size with three-tier checks.
    Returns (is_valid, error_message)
    """
    # Tier 1: Minimum size check
    if position_size < 0.005:
        return False, f'Position size too small: ${position_size:.4f} (min: $0.005)'
    
    # Tier 2: Hard cap (always enforced)
    if position_size > 10000:
        return False, 'Position size exceeds maximum allowed limit'
    
    # Tier 3: Percentage-based limit (20% of available balance)
    try:
        accounts = client.get_accounts()
        usd_account = next((acc for acc in accounts if acc.get('currency') == 'USD'), None)
        if usd_account:
            available_balance = float(usd_account.get('available_balance', {}).get('value', 0))
            max_position_percentage = available_balance * 0.20
            if position_size > max_position_percentage:
                # Generic error - don't reveal account balance
                return False, 'Position size exceeds account risk limits'
    except Exception as e:
        print(f"⚠️ Could not validate against account balance: {e}")
        # Still enforce hard cap even if balance check fails
    
    return True, None

@app.route('/health', methods=['GET'])
def health():
    """Health check endpoint"""
    return jsonify({
        'status': 'healthy',
        'service': 'NIJA TradingView Webhook',
        'timestamp': datetime.now().isoformat()
    })

@app.route('/webhook', methods=['POST'])
def tradingview_webhook():
    """
    TradingView Webhook Endpoint

    Expected JSON format from TradingView alert:
    {
        "secret": "nija_webhook_2025",
        "action": "buy" or "sell",
        "symbol": "BTC-USD",
        "size": 0.05 (optional, uses dynamic sizing if not provided),
        "message": "Custom alert message (optional)"
    }
    """
    try:
        # 🚨 CRITICAL: Check for emergency stop BEFORE processing ANY orders
        emergency_lock_file = os.path.join(os.path.dirname(__file__), '..', 'TRADING_EMERGENCY_STOP.conf')
        if os.path.exists(emergency_lock_file):
            print(f"\n{'='*70}")
            print(f"🛑 WEBHOOK BLOCKED - EMERGENCY STOP ACTIVE")
            print(f"{'='*70}")
            print(f"TRADING_EMERGENCY_STOP.conf exists")
            print(f"BUY orders are blocked in SELL-ONLY mode")
            print(f"Delete lockfile to resume buying")
            print(f"{'='*70}\n")
            return jsonify({
                'error': 'Trading is in SELL-ONLY mode - no BUY orders allowed',
                'reason': 'TRADING_EMERGENCY_STOP.conf is active',
                'action': 'Delete lockfile to resume buying'
            }), 503

        # Parse incoming data
        data = request.get_json()
        if not data:
            return jsonify({'error': 'No data received'}), 400
        # Verify webhook secret
        if data.get('secret') != WEBHOOK_SECRET:
            print(f"❌ Unauthorized webhook attempt from {request.remote_addr}")
            return jsonify({'error': 'Unauthorized'}), 401

        # Multi-order support: if 'orders' is present, process each order
        orders = data.get('orders')
        results = []
        if orders and isinstance(orders, list):
            # Security: Limit number of orders per request
            if len(orders) > MAX_ORDERS_PER_REQUEST:
                return jsonify({
                    'error': f'Too many orders in single request (max: {MAX_ORDERS_PER_REQUEST}, received: {len(orders)})',
                    'max_allowed': MAX_ORDERS_PER_REQUEST
                }), 400
            
            for order in orders:
                action = order.get('action', '').lower()
                symbol = order.get('symbol', '').upper()
                custom_size = order.get('size')
                message = order.get('message', '')
                if action not in ['buy', 'sell']:
                    results.append({'error': f'Invalid action for {symbol}: {action}'})
                    continue
                if not symbol:
                    results.append({'error': 'Symbol is required'})
                    continue
                if '-' not in symbol:
                    symbol = f"{symbol}-USD"
                
                # Security: Validate symbol format
                if not SYMBOL_PATTERN.match(symbol):
                    results.append({'error': f'Invalid symbol format: {symbol} (must match pattern: XXX-USD)'})
                    continue
                print(f"\n{'='*70}")
                print(f"📡 TRADINGVIEW WEBHOOK RECEIVED - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
                print(f"{'='*70}")
                print(f"   Action: {action.upper()}")
                print(f"   Symbol: {symbol}")
                if custom_size:
                    print(f"   Size: ${custom_size:.2f}")
                if message:
                    print(f"   Message: {message}")
                if action == 'buy':
                    # 🚨 CRITICAL: Block BUY if emergency stop is active
                    if os.path.exists(emergency_lock_file):
                        print(f"🛑 BUY BLOCKED for {symbol} - EMERGENCY STOP ACTIVE (SELL-ONLY MODE)")
                        results.append({
                            'error': f'BUY blocked for {symbol} - EMERGENCY STOP active',
                            'reason': 'TRADING_EMERGENCY_STOP.conf is active (SELL-ONLY mode)',
                            'action': 'Delete lockfile to resume buying'
                        })
                        continue

                    df = strategy.get_product_candles(symbol)
                    if df is None or len(df) < 50:
                        results.append({'error': f'Insufficient data for {symbol}'})
                        continue
                    
                    # Calculate or use custom position size
                    if custom_size:
                        position_size = float(custom_size)
                        # Validate position size with helper function
                        is_valid, error_msg = validate_position_size(position_size, client)
                        if not is_valid:
                            results.append({'error': error_msg})
                            continue
                    else:
                        position_size = strategy.calculate_position_size(symbol, signal_score=5, df=df)
                        # Still validate calculated sizes
                        if position_size < 0.005:
                            results.append({'error': f'Position size too small: ${position_size:.4f} (min: $0.005)'})
                            continue
                    strategy.enter_position(symbol, 'long', position_size, df)
                    results.append({
                        'status': 'success',
                        'action': 'buy',
                        'symbol': symbol,
                        'size': position_size,
                        'message': f'Buy order executed for {symbol}'
                    })
                elif action == 'sell':
                    position_id = None
                    for pid, pos in strategy.nija.positions.items():
                        if pid.startswith(symbol):
                            position_id = pid
                            break
                    if not position_id:
                        results.append({'error': f'No open position found for {symbol}'})
                        continue
                    df = strategy.get_product_candles(symbol)
                    if df is None or len(df) < 1:
                        results.append({'error': f'Cannot get current price for {symbol}'})
                        continue
                    current_price = float(df['close'].iloc[-1])
                    strategy.close_full_position(symbol, position_id, current_price, "TradingView sell signal")
                    results.append({
                        'status': 'success',
                        'action': 'sell',
                        'symbol': symbol,
                        'message': f'Sell order executed for {symbol}'
                    })
            return jsonify({'results': results}), 200
        # Single order fallback (backward compatible)
        action = data.get('action', '').lower()
        symbol = data.get('symbol', '').upper()
        custom_size = data.get('size')
        message = data.get('message', '')
        if action not in ['buy', 'sell']:
            return jsonify({'error': 'Invalid action. Must be "buy" or "sell"'}), 400
        if not symbol:
            return jsonify({'error': 'Symbol is required'}), 400
        if '-' not in symbol:
            symbol = f"{symbol}-USD"
        
        # Security: Validate symbol format
        if not SYMBOL_PATTERN.match(symbol):
            return jsonify({'error': f'Invalid symbol format: {symbol} (must match pattern: XXX-USD)'}), 400
        print(f"\n{'='*70}")
        print(f"📡 TRADINGVIEW WEBHOOK RECEIVED - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"{'='*70}")
        print(f"   Action: {action.upper()}")
        print(f"   Symbol: {symbol}")
        if custom_size:
            print(f"   Size: ${custom_size:.2f}")
        if message:
            print(f"   Message: {message}")
        if action == 'buy':
            # 🚨 CRITICAL: Block BUY if emergency stop is active
            if os.path.exists(emergency_lock_file):
                print(f"\n{'='*70}")
                print(f"🛑 BUY BLOCKED - EMERGENCY STOP ACTIVE (SELL-ONLY MODE)")
                print(f"{'='*70}")
                print(f"Symbol: {symbol}")
                print(f"Reason: TRADING_EMERGENCY_STOP.conf exists")
                print(f"Action: Delete lockfile to resume buying")
                print(f"{'='*70}\n")
                return jsonify({
                    'error': f'BUY blocked for {symbol} - EMERGENCY STOP active',
                    'reason': 'TRADING_EMERGENCY_STOP.conf is active (SELL-ONLY mode)',
                    'action': 'Delete lockfile to resume buying'
                }), 503

            df = strategy.get_product_candles(symbol)
            if df is None or len(df) < 50:
                return jsonify({'error': f'Insufficient data for {symbol}'}), 400
            
            # Position size validation (same as multi-order)
            if custom_size:
                position_size = float(custom_size)
                # Validate position size with helper function
                is_valid, error_msg = validate_position_size(position_size, client)
                if not is_valid:
                    return jsonify({'error': error_msg}), 400
            else:
                position_size = strategy.calculate_position_size(symbol, signal_score=5, df=df)
            
            # Final minimum check for calculated sizes
            if position_size < 0.005:
                return jsonify({'error': f'Position size too small: ${position_size:.4f} (min: $0.005)'}), 400
            strategy.enter_position(symbol, 'long', position_size, df)
            return jsonify({
                'status': 'success',
                'action': 'buy',
                'symbol': symbol,
                'size': position_size,
                'message': f'Buy order executed for {symbol}',
                'nija_features': [
                    '95% profit lock at +0.25%',
                    'Pyramiding at +1%, +2%, +3%',
                    'Extended runners to 20%',
                    'TP0.5/TP1/TP2 partial exits'
                ]
            }), 200
        elif action == 'sell':
            position_id = None
            for pid, pos in strategy.nija.positions.items():
                if pid.startswith(symbol):
                    position_id = pid
                    break
            if not position_id:
                return jsonify({'error': f'No open position found for {symbol}'}), 404
            df = strategy.get_product_candles(symbol)
            if df is None or len(df) < 1:
                return jsonify({'error': f'Cannot get current price for {symbol}'}), 400
            current_price = float(df['close'].iloc[-1])
            strategy.close_full_position(symbol, position_id, current_price, "TradingView sell signal")
            return jsonify({
                'status': 'success',
                'action': 'sell',
                'symbol': symbol,
                'message': f'Sell order executed for {symbol}'
            }), 200
    except ValueError as e:
        # Input validation errors
        print(f"⚠️ Webhook validation error: {str(e)}")
        return jsonify({'error': 'Invalid input data'}), 400
    except KeyError as e:
        # Missing required data
        print(f"⚠️ Webhook missing required field: {str(e)}")
        return jsonify({'error': 'Missing required field'}), 400
    except Exception as e:
        # Unexpected errors - log details internally, return generic message
        import traceback
        print(f"❌ Unexpected webhook error: {str(e)}")
        print(traceback.format_exc())
        return jsonify({'error': 'Internal server error'}), 500

@app.route('/positions', methods=['GET'])
def get_positions():
    """Get all open NIJA positions (for monitoring)"""
    try:
        positions_data = []
        for position_id, position in strategy.nija.positions.items():
            positions_data.append({
                'id': position_id,
                'symbol': position.get('product_id', position_id.split('-')[0]),
                'side': position['side'],
                'entry_price': position['entry_price'],
                'profit_pct': position.get('profit_pct', 0),
                'remaining_size': position['remaining_size'],
                'stop_loss': position['stop_loss'],
                'tsl_active': position.get('tsl_active', False),
                'ttp_active': position.get('ttp_active', False),
                'pyramid_levels': position.get('pyramid_levels', [])
            })

        return jsonify({
            'status': 'success',
            'count': len(positions_data),
            'positions': positions_data
        }), 200

    except Exception as e:
        return jsonify({'error': 'Failed to retrieve positions'}), 500

if __name__ == '__main__':
    port = int(os.getenv('PORT', 8080))
    print(f"\n{'='*70}")
    print(f"🚀 NIJA TRADINGVIEW WEBHOOK SERVICE")
    print(f"{'='*70}")
    print(f"📡 Webhook URL: https://your-railway-app.railway.app/webhook")
    print(f"🔒 Webhook Secret: {WEBHOOK_SECRET}")
    print(f"💰 Trading Mode: LIVE (Coinbase)")
    print(f"🎯 NIJA Features: 95% Profit Lock + Pyramiding + Extended Runners")
    print(f"{'='*70}\n")

    app.run(host='0.0.0.0', port=port, debug=False)
