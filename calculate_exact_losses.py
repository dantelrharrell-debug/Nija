#!/usr/bin/env python3
"""
Calculate exact P&L on all 13 open positions
Including entry prices, fees, and current losses
"""
import os
import sys
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()
sys.path.insert(0, '/workspaces/Nija/bot')

from coinbase.rest import RESTClient

print("\n" + "="*120)
print("💥 NIJA LOSS CALCULATION - ALL 13 POSITIONS")
print("="*120)
print(f"⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S UTC')}\n")

try:
    client = RESTClient(
        api_key=os.getenv('COINBASE_API_KEY'),
        api_secret=os.getenv('COINBASE_API_SECRET')
    )
    
    # Step 1: Get current positions
    print("📊 STEP 1: FETCHING CURRENT POSITIONS")
    print("-"*120)
    
    accounts = client.get_accounts()
    positions = []
    cash_balance = 0
    
    for acc in accounts.accounts:
        curr = acc.currency
        bal = float(acc.available_balance.value)
        acc_type = acc.type
        
        if curr in ['USD', 'USDC']:
            cash_balance += bal
        elif bal > 0.00000001 and curr not in ['USDT']:
            positions.append({
                'symbol': f"{curr}-USD",
                'currency': curr,
                'balance': bal,
                'type': acc_type
            })
    
    print(f"✅ Found {len(positions)} open positions")
    print(f"   Cash available: ${cash_balance:.2f}\n")
    
    if len(positions) == 0:
        print("✅ No positions open - no losses!")
        sys.exit(0)
    
    # Step 2: Get entry prices from recent filled orders
    print("📋 STEP 2: FETCHING ENTRY PRICES FROM ORDER HISTORY")
    print("-"*120)
    
    entry_prices = {}
    fees_paid = {}
    
    filled_orders = client.list_orders(order_status='FILLED', limit=200)
    
    for order in filled_orders.orders:
        product_id = order.product_id
        side = order.side.upper()
        price = float(order.price)
        qty = float(order.filled_size if hasattr(order, 'filled_size') else order.size)
        filled_value = float(order.filled_value if hasattr(order, 'filled_value') else qty * price)
        
        # Track BUY prices (entry prices)
        if side == 'BUY' and product_id not in entry_prices:
            entry_prices[product_id] = {
                'price': price,
                'qty': qty,
                'filled_value': filled_value,
                'fee': filled_value * 0.01  # ~1% average fee
            }
    
    print(f"✅ Found entry data for {len(entry_prices)} positions\n")
    
    # Step 3: Calculate P&L for each position
    print("💰 STEP 3: POSITION-BY-POSITION P&L ANALYSIS")
    print("="*120)
    
    total_entry_value = 0
    total_current_value = 0
    total_fees = 0
    total_unrealized_loss = 0
    worst_position = None
    worst_loss_pct = 0
    
    position_analysis = []
    
    for i, pos in enumerate(positions, 1):
        symbol = pos['symbol']
        qty = pos['balance']
        
        # Get current price
        try:
            product = client.get_product(symbol)
            current_price = float(product.price)
        except:
            current_price = 0
        
        # Get entry data
        entry_data = entry_prices.get(symbol, {})
        entry_price = entry_data.get('price', 0)
        entry_fee = entry_data.get('fee', 0)
        
        if entry_price == 0:
            print(f"\n{i:2}. {symbol:12} | Entry: UNKNOWN | Current: ${current_price:10.4f}")
            print(f"     Balance: {qty:16.8f}")
            continue
        
        # Calculate values
        entry_value = qty * entry_price
        current_value = qty * current_price
        unrealized_pnl = current_value - entry_value
        pnl_pct = (unrealized_pnl / entry_value * 100) if entry_value > 0 else 0
        
        # Include fee impact (fees reduce profits or increase losses)
        exit_fee = current_value * 0.01  # 1% exit fee estimate
        total_fee_impact = entry_fee + exit_fee
        net_pnl = unrealized_pnl - total_fee_impact
        net_pnl_pct = (net_pnl / entry_value * 100) if entry_value > 0 else 0
        
        # Accumulate totals
        total_entry_value += entry_value
        total_current_value += current_value
        total_fees += total_fee_impact
        total_unrealized_loss += net_pnl
        
        # Track worst position
        if net_pnl_pct < worst_loss_pct:
            worst_loss_pct = net_pnl_pct
            worst_position = symbol
        
        position_analysis.append({
            'num': i,
            'symbol': symbol,
            'qty': qty,
            'entry_price': entry_price,
            'current_price': current_price,
            'entry_value': entry_value,
            'current_value': current_value,
            'unrealized_pnl': unrealized_pnl,
            'pnl_pct': pnl_pct,
            'fees': total_fee_impact,
            'net_pnl': net_pnl,
            'net_pnl_pct': net_pnl_pct
        })
        
        # Print position
        pnl_emoji = "📈" if net_pnl >= 0 else "📉"
        print(f"\n{i:2}. {symbol:12} | {pnl_emoji} P&L: {net_pnl_pct:+7.2f}%")
        print(f"     Entry: ${entry_price:10.4f} → Current: ${current_price:10.4f}")
        print(f"     Value: ${entry_value:12.2f} → ${current_value:12.2f} | Change: ${unrealized_pnl:+10.2f}")
        print(f"     Fees: ${total_fee_impact:8.2f} | Net P&L: ${net_pnl:+10.2f}")
    
    print("\n" + "="*120)
    print("📊 PORTFOLIO SUMMARY")
    print("="*120)
    
    # Sort by worst losses
    position_analysis.sort(key=lambda x: x['net_pnl_pct'])
    
    print(f"\n🔴 WORST 5 POSITIONS (Biggest Losses):")
    for pos in position_analysis[:5]:
        print(f"   {pos['num']:2}. {pos['symbol']:12} | {pos['net_pnl_pct']:+7.2f}% | Loss: ${pos['net_pnl']:+10.2f}")
    
    print(f"\n🟢 BEST 5 POSITIONS (Biggest Gains):")
    for pos in reversed(position_analysis[-5:]):
        print(f"   {pos['num']:2}. {pos['symbol']:12} | {pos['net_pnl_pct']:+7.2f}% | Gain: ${pos['net_pnl']:+10.2f}")
    
    print(f"\n" + "-"*120)
    print(f"💵 TOTAL INVESTMENT:     ${total_entry_value:>15.2f}")
    print(f"💰 CURRENT VALUE:        ${total_current_value:>15.2f}")
    print(f"⚠️  TOTAL FEES PAID:      ${total_fees:>15.2f}")
    print(f"📉 UNREALIZED P&L:       ${total_unrealized_loss:>15.2f} ({(total_unrealized_loss/total_entry_value*100):+.2f}%)")
    print(f"💸 CASH BALANCE:         ${cash_balance:>15.2f}")
    print(f"📊 TOTAL PORTFOLIO:      ${cash_balance + total_current_value:>15.2f}")
    print("-"*120)
    
    # Analysis
    print(f"\n🔍 ANALYSIS:")
    
    if total_unrealized_loss < 0:
        loss_abs = abs(total_unrealized_loss)
        loss_pct = abs(total_unrealized_loss / total_entry_value * 100)
        print(f"\n   🚨 YOU ARE LOSING: ${loss_abs:.2f} ({loss_pct:.2f}%)")
        print(f"\n   REASONS:")
        print(f"   1. Positions fell below entry prices")
        print(f"   2. Fees (${total_fees:.2f}) eating into gains")
        print(f"   3. Holding losses waiting for recovery")
        
        if worst_position:
            worst_pos = next((p for p in position_analysis if p['symbol'] == worst_position), None)
            if worst_pos:
                print(f"\n   WORST POSITION: {worst_position}")
                print(f"      Loss: {worst_pos['net_pnl_pct']:.2f}% = ${worst_pos['net_pnl']:.2f}")
    else:
        print(f"\n   ✅ POSITIONS ARE PROFITABLE: ${total_unrealized_loss:.2f} gains")
        print(f"   → Let bot run to hit +6% take profit targets")
        print(f"   → Positions will auto-close when targets hit")
    
    print(f"\n" + "="*120)
    print("⚠️  NEXT STEPS:")
    print("="*120)
    
    if total_unrealized_loss < -50:
        print(f"\n1. FORCE SELL ALL (bleeding money):")
        print(f"   python FORCE_SELL_ALL_POSITIONS.py")
    elif total_unrealized_loss < 0:
        print(f"\n1. OPTIONS:")
        print(f"   A) Force sell now to stop losses: python FORCE_SELL_ALL_POSITIONS.py")
        print(f"   B) Let bot monitor for recovery (+2-3% moves)")
    else:
        print(f"\n1. KEEP POSITIONS (they're profitable):")
        print(f"   → Restart bot: ./start.sh")
        print(f"   → Wait for +6% targets to hit auto-sell")
    
    print(f"\n2. REDUCE TO 8 POSITIONS:")
    print(f"   Currently holding: {len(positions)} (limit is 8)")
    print(f"   Bot will close weakest {len(positions) - 8} when monitoring resumes")
    
    print(f"\n3. MONITOR PROGRESS:")
    print(f"   python verify_nija_selling_now.py  # Check if selling")
    
    print("\n" + "="*120 + "\n")

except Exception as e:
    print(f"❌ Error: {e}")
    import traceback
    traceback.print_exc()
