#!/usr/bin/env python3
"""
Analyze past trades from bot logs and Coinbase to show profitability
"""
import os
import json
from datetime import datetime, timedelta
from coinbase.rest import RESTClient
from collections import defaultdict

def load_position_history():
    """Load saved position history from bot"""
    positions_file = 'bot/positions.json'
    
    if os.path.exists(positions_file):
        try:
            with open(positions_file, 'r') as f:
                return json.load(f)
        except:
            pass
    
    return {}

def analyze_bot_trades():
    """Analyze trades from bot's perspective"""
    
    print("\n" + "="*80)
    print("🤖 BOT TRADE ANALYSIS")
    print("="*80)
    
    # Check saved positions
    positions = load_position_history()
    
    if positions:
        print(f"\n📂 Found {len(positions)} saved position(s) in bot memory:")
        print("-" * 80)
        
        for symbol, pos in positions.items():
            entry_price = pos.get('entry_price', 0)
            side = pos.get('side', 'UNKNOWN')
            size_usd = pos.get('size_usd', 0)
            timestamp = pos.get('timestamp', 'Unknown')
            
            print(f"\n   Symbol: {symbol}")
            print(f"   Side: {side}")
            print(f"   Entry Price: ${entry_price:.2f}")
            print(f"   Position Size: ${size_usd:.2f}")
            print(f"   Opened: {timestamp}")
    else:
        print("\n   ℹ️ No saved positions found")
        print("   This means either:")
        print("   - Bot never successfully opened any positions")
        print("   - positions.json file was deleted/cleared")
    
    return positions

def analyze_coinbase_trades():
    """Analyze actual trades executed on Coinbase"""
    
    print("\n\n" + "="*80)
    print("💹 COINBASE ACTUAL TRADE PERFORMANCE")
    print("="*80)
    
    try:
        client = RESTClient(
            api_key=os.getenv('COINBASE_API_KEY'),
            api_secret=os.getenv('COINBASE_API_SECRET')
        )
        
        # Get filled orders from last 60 days
        end_date = datetime.utcnow()
        start_date = end_date - timedelta(days=60)
        
        print(f"\n📊 Analyzing trades from {start_date.strftime('%Y-%m-%d')} to {end_date.strftime('%Y-%m-%d')}")
        print("-" * 80)
        
        orders = client.list_orders(
            order_status=['FILLED'],
            limit=100,
            start_date=start_date.isoformat(),
            end_date=end_date.isoformat()
        )
        
        filled_orders = orders.get('orders', [])
        
        if not filled_orders:
            print("\n   ❌ NO TRADES FOUND")
            print("   This confirms: Bot attempted trades but NONE were filled")
            print("   All attempts failed with INSUFFICIENT_FUND error")
            return
        
        print(f"\n   ✅ Found {len(filled_orders)} filled orders")
        
        # Group by product to match buys with sells
        trades_by_product = defaultdict(list)
        
        for order in filled_orders:
            product_id = order.get('product_id', 'UNKNOWN')
            trades_by_product[product_id].append(order)
        
        # Analyze P&L for each product
        print("\n\n📈 PROFIT/LOSS BY ASSET:")
        print("="*80)
        
        total_pnl = 0.0
        winning_trades = 0
        losing_trades = 0
        
        for product_id, product_orders in trades_by_product.items():
            # Sort by time
            product_orders.sort(key=lambda x: x.get('created_time', ''))
            
            print(f"\n{product_id}:")
            print("-" * 80)
            
            buys = [o for o in product_orders if o.get('side') == 'BUY']
            sells = [o for o in product_orders if o.get('side') == 'SELL']
            
            print(f"   Buy orders:  {len(buys)}")
            print(f"   Sell orders: {len(sells)}")
            
            # Calculate basic P&L (simplified - not tracking exact position matching)
            total_buy_value = sum(float(o.get('filled_value', 0)) for o in buys)
            total_sell_value = sum(float(o.get('filled_value', 0)) for o in sells)
            
            if total_buy_value > 0 or total_sell_value > 0:
                pnl = total_sell_value - total_buy_value
                
                print(f"\n   Total bought:  ${total_buy_value:,.2f}")
                print(f"   Total sold:    ${total_sell_value:,.2f}")
                print(f"   Net P&L:       ${pnl:+,.2f}")
                
                if pnl > 0:
                    print(f"   Status: ✅ PROFIT")
                    winning_trades += 1
                elif pnl < 0:
                    print(f"   Status: ❌ LOSS")
                    losing_trades += 1
                else:
                    print(f"   Status: ⚖️ BREAK EVEN")
                
                total_pnl += pnl
            
            # Show individual trades
            if len(product_orders) <= 10:
                print(f"\n   Recent trades:")
                for order in product_orders[-10:]:
                    side = order.get('side', '')
                    filled_value = float(order.get('filled_value', 0))
                    avg_price = float(order.get('average_filled_price', 0))
                    created_time = order.get('created_time', '')[:19]
                    
                    print(f"   {created_time} | {side:4} | ${filled_value:8.2f} @ ${avg_price:.2f}")
        
        # Overall summary
        print("\n\n" + "="*80)
        print("💰 OVERALL TRADING PERFORMANCE")
        print("="*80)
        
        print(f"\n   Total Assets Traded: {len(trades_by_product)}")
        print(f"   Winning Assets: {winning_trades}")
        print(f"   Losing Assets:  {losing_trades}")
        print(f"\n   Net P&L (All Trades): ${total_pnl:+,.2f}")
        
        if total_pnl > 0:
            print(f"   Overall Status: ✅ PROFITABLE")
        elif total_pnl < 0:
            print(f"   Overall Status: ❌ LOSING MONEY")
        else:
            print(f"   Overall Status: ⚖️ BREAK EVEN")
        
        # Calculate win rate
        total_assets = winning_trades + losing_trades
        if total_assets > 0:
            win_rate = (winning_trades / total_assets) * 100
            print(f"   Win Rate: {win_rate:.1f}%")
        
    except Exception as e:
        print(f"\n❌ Error analyzing Coinbase trades: {e}")
        import traceback
        traceback.print_exc()

def main():
    """Main analysis function"""
    
    print("\n" + "="*80)
    print("🔍 COMPREHENSIVE TRADE ANALYSIS")
    print("="*80)
    print(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    # Check credentials
    if not os.getenv('COINBASE_API_KEY') or not os.getenv('COINBASE_API_SECRET'):
        print("\n❌ ERROR: Missing Coinbase API credentials")
        print("Make sure COINBASE_API_KEY and COINBASE_API_SECRET are in .env")
        return
    
    # Analyze bot's saved positions
    bot_positions = analyze_bot_trades()
    
    # Analyze actual Coinbase trades
    analyze_coinbase_trades()
    
    # Final recommendations
    print("\n\n" + "="*80)
    print("💡 WHAT THIS MEANS")
    print("="*80)
    
    print("\n1. If NO trades found on Coinbase:")
    print("   → Bot never successfully executed trades")
    print("   → All attempts failed due to INSUFFICIENT_FUND")
    print("   → You didn't lose money from trading, balance was always too low")
    
    print("\n2. If trades found but LOSING money:")
    print("   → Bot strategy needs adjustment")
    print("   → Entry/exit signals may be triggering at wrong times")
    print("   → Consider reviewing market conditions and timeframes")
    
    print("\n3. If trades found and PROFITABLE:")
    print("   → Bot strategy is working")
    print("   → Need more capital to generate meaningful returns")
    print("   → Consider increasing position sizes")
    
    print("\n4. To improve performance:")
    print("   → Deposit at least $50-$100 for proper position sizing")
    print("   → Monitor first 10-20 trades manually")
    print("   → Adjust strategy parameters based on results")
    print("   → Consider paper trading first to validate strategy")

if __name__ == "__main__":
    main()
