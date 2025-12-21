#!/usr/bin/env python3
"""
Diagnose why NIJA is holding 13 trades instead of 8
and calculate current profit/loss
"""
import os
import sys
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()
sys.path.insert(0, '/workspaces/Nija/bot')

from broker_manager import CoinbaseAdvancedTradeBroker
import logging

logging.basicConfig(level=logging.ERROR)

print("\n" + "="*100)
print("🔍 NIJA DIAGNOSTIC: 13 TRADES ISSUE")
print("="*100)
print(f"⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")

try:
    # Initialize broker
    broker = CoinbaseAdvancedTradeBroker()
    if not broker.connect():
        print("❌ Failed to connect to Coinbase")
        sys.exit(1)
    
    # Get balance
    balance = broker.get_account_balance()
    print(f"📊 Current USD Balance: ${balance:.2f}\n")
    
    # Get positions
    positions = broker.get_positions()
    num_positions = len(positions)
    
    print(f"🚨 OPEN POSITIONS: {num_positions} (Expected max: 8)")
    if num_positions > 8:
        print(f"   ⚠️  OVERAGE: {num_positions - 8} positions over limit")
    print("="*100)
    
    # Analyze each position
    total_crypto_value = 0
    position_details = []
    
    for i, pos in enumerate(positions, 1):
        symbol = pos['symbol']
        quantity = pos['quantity']
        
        try:
            # Get current price
            product = broker.client.get_product(symbol)
            current_price = float(product.price)
            position_value = quantity * current_price
            total_crypto_value += position_value
            
            position_details.append({
                'num': i,
                'symbol': symbol,
                'quantity': quantity,
                'price': current_price,
                'value': position_value
            })
            
            print(f"{i:2}. {symbol:15} | {quantity:16.8f} | @ ${current_price:12.4f} | = ${position_value:12.2f}")
            
        except Exception as e:
            print(f"{i:2}. {symbol:15} | {quantity:16.8f} | @ {'ERROR':>12} | = {'?':>12}")
            position_details.append({
                'num': i,
                'symbol': symbol,
                'quantity': quantity,
                'price': 0,
                'value': 0,
                'error': str(e)
            })
    
    print("="*100)
    
    # Calculate portfolio summary
    print(f"\n💰 PORTFOLIO SUMMARY:")
    print(f"   USD Cash:       ${balance:12.2f}")
    print(f"   Crypto Value:   ${total_crypto_value:12.2f}")
    print(f"   Total Portfolio: ${balance + total_crypto_value:12.2f}")
    print(f"   Positions:      {num_positions}")
    
    # Check for positions trading at a loss
    print(f"\n📉 POSITIONS IN LOSS (if entry prices known):")
    loss_positions = []
    
    try:
        # Check recent orders for entry prices
        orders_response = broker.client.list_orders(order_status="FILLED", limit=100)
        filled_orders = []
        if hasattr(orders_response, 'orders'):
            filled_orders = orders_response.orders
        
        # Build entry price map
        entry_prices = {}
        for order in filled_orders:
            product_id = getattr(order, 'product_id', '')
            side = getattr(order, 'side', '').upper()
            price = getattr(order, 'price', '0')
            
            if side == 'BUY' and product_id not in entry_prices:
                try:
                    entry_prices[product_id] = float(price)
                except:
                    pass
        
        # Check for losses
        for pos_detail in position_details:
            symbol = pos_detail['symbol']
            if symbol in entry_prices:
                entry_price = entry_prices[symbol]
                current_price = pos_detail['price']
                pnl_pct = ((current_price - entry_price) / entry_price) * 100
                
                if pnl_pct < 0:
                    loss_positions.append({
                        'symbol': symbol,
                        'entry': entry_price,
                        'current': current_price,
                        'loss_pct': pnl_pct
                    })
        
        if loss_positions:
            loss_positions.sort(key=lambda x: x['loss_pct'])  # Worst first
            for lp in loss_positions:
                print(f"   {lp['symbol']:12} | Entry: ${lp['entry']:8.2f} | Current: ${lp['current']:8.2f} | P&L: {lp['loss_pct']:+7.2f}%")
        else:
            print("   ✅ No losses detected (or entry prices not found)")
    except Exception as e:
        print(f"   ⚠️  Could not analyze losses: {e}")
    
    # Check why positions aren't closing
    print(f"\n🔍 WHY AREN'T POSITIONS CLOSING?")
    print("="*100)
    
    try:
        # Check for pending sell orders
        orders_response = broker.client.list_orders(order_status="OPEN")
        open_orders = []
        if hasattr(orders_response, 'orders'):
            open_orders = orders_response.orders
        
        sell_orders = [o for o in open_orders if getattr(o, 'side', '').upper() == 'SELL']
        
        if sell_orders:
            print(f"\n⚠️  {len(sell_orders)} SELL orders are PENDING (not filled):")
            for order in sell_orders[:10]:
                product = getattr(order, 'product_id', 'Unknown')
                created = getattr(order, 'created_time', 'Unknown')
                print(f"   • {product}: Created {created}")
        else:
            print(f"\n❌ NO PENDING SELL ORDERS")
            if num_positions > 0:
                print(f"   ⚠️  {num_positions} positions open but no sell orders")
                print(f"   Reasons:")
                print(f"   1. Positions haven't hit profit targets (+6%)")
                print(f"   2. Positions are in losses (-2% stop loss)")
                print(f"   3. Bot is NOT running / monitoring positions")
                print(f"   4. Bot crashed or lost connection")
    except Exception as e:
        print(f"Error checking orders: {e}")
    
    # Check bot status
    print(f"\n⚙️  BOT STATUS CHECK:")
    print("="*100)
    
    positions_file = '/workspaces/Nija/data/open_positions.json'
    if os.path.exists(positions_file):
        try:
            import json
            with open(positions_file, 'r') as f:
                saved_positions = json.load(f)
            
            if saved_positions:
                print(f"\n✅ Bot has {len(saved_positions)} positions in memory")
                print(f"   These positions SHOULD be monitored by the bot")
                
                # Compare with actual positions
                saved_symbols = set(saved_positions.keys())
                actual_symbols = set([p['symbol'] for p in positions])
                
                if saved_symbols == actual_symbols:
                    print(f"   ✅ Memory and actual positions match")
                else:
                    print(f"   ⚠️  Mismatch between saved and actual!")
                    missing = actual_symbols - saved_symbols
                    extra = saved_symbols - actual_symbols
                    if missing:
                        print(f"      Actual but not in memory: {missing}")
                    if extra:
                        print(f"      In memory but not actual: {extra}")
            else:
                print(f"\n⚠️  No saved positions found")
                print(f"   Bot will create new position tracking")
        except Exception as e:
            print(f"\n⚠️  Could not read saved positions: {e}")
    else:
        print(f"\n⚠️  No position file at {positions_file}")
        print(f"   Bot will create this on startup")
    
    # Check logs
    print(f"\n📋 RECENT BOT ACTIVITY:")
    print("="*100)
    
    nija_log = '/workspaces/Nija/nija.log'
    if os.path.exists(nija_log):
        try:
            with open(nija_log, 'r') as f:
                lines = f.readlines()
            
            # Get last 20 lines
            recent_lines = lines[-20:]
            
            # Look for key events
            sell_count = sum(1 for l in recent_lines if 'SELL' in l)
            buy_count = sum(1 for l in recent_lines if 'BUY' in l)
            error_count = sum(1 for l in recent_lines if 'ERROR' in l or 'Failed' in l)
            close_count = sum(1 for l in recent_lines if 'Closing' in l or 'closed' in l)
            
            print(f"\nLast 20 log entries summary:")
            print(f"   BUY signals:    {buy_count}")
            print(f"   SELL signals:   {sell_count}")
            print(f"   Closures:       {close_count}")
            print(f"   Errors:         {error_count}")
            
            if error_count > 0:
                print(f"\n   Recent errors:")
                for line in recent_lines:
                    if 'ERROR' in line or 'Failed' in line:
                        print(f"   {line.strip()}")
            
            # Check last activity time
            if recent_lines:
                last_line = recent_lines[-1]
                print(f"\n   Last activity: {last_line.strip()[:80]}")
                
        except Exception as e:
            print(f"Could not read logs: {e}")
    else:
        print(f"\n⚠️  No bot log file found at {nija_log}")
        print(f"   Bot may not be running")
    
    print("\n" + "="*100)
    print("💡 SUMMARY:")
    print("="*100)
    
    if num_positions > 8:
        print(f"\n🚨 PROBLEM: {num_positions} positions (max should be 8)")
        print(f"\n   ROOT CAUSES:")
        print(f"   1. Bot opened too many positions before limit was enforced")
        print(f"   2. Bot is running but positions aren't hitting exit targets")
        print(f"   3. Bot stopped running after opening positions")
        
        print(f"\n   TO FIX:")
        print(f"   1. Run 'python FORCE_SELL_ALL_POSITIONS.py' to liquidate all immediately")
        print(f"   2. Restart bot with fresh position tracking")
        print(f"   3. Or wait for positions to hit +6% profit targets")
    
    if total_crypto_value == 0:
        print(f"\n✅ All positions are at $0 value (already closed)")
    elif total_crypto_value > 0 and num_positions <= 8:
        print(f"\n✅ Holding optimal {num_positions} positions")
        print(f"   Total exposure: ${total_crypto_value:.2f}")
        
        # Calculate loss percentage
        total_portfolio = balance + total_crypto_value
        if total_portfolio > 0:
            loss_pct = ((balance - (balance + total_crypto_value)) / (balance + total_crypto_value)) * 100
            if loss_pct < 0:
                print(f"\n   📈 Overall: +${abs((balance + total_crypto_value) - balance):.2f}")
            else:
                print(f"\n   📉 Overall: -${loss_pct:.2f} loss potential")
    
    print("\n" + "="*100 + "\n")

except Exception as e:
    print(f"❌ Error: {e}")
    import traceback
    traceback.print_exc()
