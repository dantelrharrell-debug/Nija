#!/usr/bin/env python3
"""
COMPREHENSIVE NIJA SELLING & PROFIT CHECK
Verifies NIJA is selling positions and making profit
"""
import os
import sys
from datetime import datetime
from dotenv import load_dotenv
load_dotenv()

sys.path.append('/workspaces/Nija/bot')
from coinbase.rest import RESTClient

print("\n" + "="*80)
print("🚀 NIJA SELLING & PROFIT VERIFICATION")
print("="*80)
print(f"⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S UTC')}")
print()

client = RESTClient(
    api_key=os.getenv('COINBASE_API_KEY'),
    api_secret=os.getenv('COINBASE_API_SECRET')
)

# Step 1: Check current positions
print("STEP 1: Current Account Status")
print("-"*80)

accounts_resp = client.get_accounts()
accounts = getattr(accounts_resp, 'accounts', [])

positions = []
usd_balance = 0
usdc_balance = 0
advanced_trade_positions = []
consumer_positions = []

for acc in accounts:
    curr = getattr(acc, 'currency', None)
    avail_obj = getattr(acc, 'available_balance', None)
    acc_type = getattr(acc, 'type', 'UNKNOWN')
    
    if not curr or not avail_obj:
        continue
    
    bal = float(getattr(avail_obj, 'value', '0'))
    
    if curr == 'USD':
        usd_balance += bal
    elif curr == 'USDC':
        usdc_balance += bal
    elif bal > 0 and curr not in ['USDT']:
        pos_data = {'currency': curr, 'balance': bal, 'type': acc_type}
        positions.append(pos_data)
        
        if 'TRADING' in acc_type or 'DEFAULT' in acc_type:
            advanced_trade_positions.append(pos_data)
        else:
            consumer_positions.append(pos_data)

print(f"💰 Cash: ${usd_balance + usdc_balance:.2f} (USD: ${usd_balance:.2f}, USDC: ${usdc_balance:.2f})")
print(f"📦 Total Positions: {len(positions)}")
print(f"   ├─ Advanced Trade: {len(advanced_trade_positions)} (NIJA manages these)")
print(f"   └─ Consumer Wallet: {len(consumer_positions)} (NIJA CANNOT manage these)")

# Step 2: Get current prices
print(f"\nSTEP 2: Position Values")
print("-"*80)

total_advanced_value = 0
total_consumer_value = 0

if advanced_trade_positions:
    print(f"\n✅ Advanced Trade Positions (NIJA MANAGED):")
    for pos in advanced_trade_positions:
        curr = pos['currency']
        bal = pos['balance']
        try:
            product = client.get_product(f"{curr}-USD")
            price = float(getattr(product, 'price', 0))
            value = bal * price
            total_advanced_value += value
            print(f"   • {curr}: {bal:.8f} @ ${price:.4f} = ${value:.2f}")
            pos['price'] = price
            pos['value'] = value
        except:
            print(f"   • {curr}: {bal:.8f} (price unavailable)")

if consumer_positions:
    print(f"\n⚠️  Consumer Wallet Positions (NOT MANAGED BY NIJA):")
    for pos in consumer_positions:
        curr = pos['currency']
        bal = pos['balance']
        try:
            product = client.get_product(f"{curr}-USD")
            price = float(getattr(product, 'price', 0))
            value = bal * price
            total_consumer_value += value
            print(f"   • {curr}: {bal:.8f} @ ${price:.4f} = ${value:.2f}")
        except:
            print(f"   • {curr}: {bal:.8f}")

print(f"\n💎 Portfolio Summary:")
print(f"   Advanced Trade Value: ${total_advanced_value:.2f}")
print(f"   Consumer Value: ${total_consumer_value:.2f}")
print(f"   Total Portfolio: ${total_advanced_value + total_consumer_value + usd_balance + usdc_balance:.2f}")

# Step 3: Check open SELL orders
print(f"\nSTEP 3: Active SELL Orders (Is NIJA selling NOW?)")
print("-"*80)

try:
    open_orders = client.list_orders(order_status='OPEN')
    orders = getattr(open_orders, 'orders', [])
    
    sell_orders = [o for o in orders if getattr(o, 'side', '') == 'SELL']
    
    if sell_orders:
        print(f"\n✅ YES! NIJA has {len(sell_orders)} active SELL order(s):\n")
        for order in sell_orders:
            product_id = getattr(order, 'product_id', 'Unknown')
            status = getattr(order, 'status', 'Unknown')
            created = getattr(order, 'created_time', 'Unknown')
            print(f"   📤 {product_id} - Status: {status}")
            print(f"      Created: {created}")
    else:
        print(f"\n❌ NO ACTIVE SELL ORDERS")
        if len(advanced_trade_positions) > 0:
            print(f"   ⚠️  Warning: {len(advanced_trade_positions)} positions open but no sells pending")
            print(f"   Possible reasons:")
            print(f"   - Positions haven't hit profit target (+6%) yet")
            print(f"   - Stop losses (-2%) not triggered")
            print(f"   - Bot waiting for sell conditions")
        else:
            print(f"   ✅ No positions to sell")
except Exception as e:
    print(f"❌ Error checking orders: {e}")

# Step 4: Check recent filled orders (trading history)
print(f"\nSTEP 4: Recent Trading Activity (Last 20 orders)")
print("-"*80)

try:
    filled_orders = client.list_orders(order_status='FILLED', limit=20)
    orders = getattr(filled_orders, 'orders', [])
    
    if orders:
        buy_orders = []
        sell_orders = []
        
        for order in orders:
            side = getattr(order, 'side', 'Unknown')
            if side == 'BUY':
                buy_orders.append(order)
            elif side == 'SELL':
                sell_orders.append(order)
        
        print(f"\n📊 Recent Activity Summary:")
        print(f"   BUY orders:  {len(buy_orders)}")
        print(f"   SELL orders: {len(sell_orders)}")
        
        if len(sell_orders) > 0:
            print(f"\n✅ NIJA IS SELLING! Recent SELL orders:")
            for order in sell_orders[:5]:
                product_id = getattr(order, 'product_id', 'Unknown')
                completed = getattr(order, 'completion_time', 'Unknown')
                filled_value = getattr(order, 'filled_value', '0')
                print(f"   📤 {product_id} - ${filled_value} @ {completed}")
        else:
            print(f"\n⚠️  NO RECENT SELL ORDERS")
            print(f"   NIJA has been buying but not selling yet")
        
        if len(buy_orders) > 0:
            print(f"\n📥 Recent BUY orders:")
            for order in buy_orders[:5]:
                product_id = getattr(order, 'product_id', 'Unknown')
                completed = getattr(order, 'completion_time', 'Unknown')
                filled_value = getattr(order, 'filled_value', '0')
                print(f"   📥 {product_id} - ${filled_value} @ {completed}")
        
        # Calculate profit if we have both buys and sells
        if len(sell_orders) > 0 and len(buy_orders) > 0:
            total_buy_value = sum(float(getattr(o, 'filled_value', '0')) for o in buy_orders)
            total_sell_value = sum(float(getattr(o, 'filled_value', '0')) for o in sell_orders)
            
            if total_buy_value > 0:
                profit = total_sell_value - total_buy_value
                profit_pct = (profit / total_buy_value) * 100
                
                print(f"\n💰 PROFIT ANALYSIS (Last 20 trades):")
                print(f"   Total Bought:  ${total_buy_value:.2f}")
                print(f"   Total Sold:    ${total_sell_value:.2f}")
                print(f"   Net Profit:    ${profit:.2f} ({profit_pct:+.2f}%)")
                
                if profit > 0:
                    print(f"\n✅ NIJA IS PROFITABLE! 🎉")
                elif profit < 0:
                    print(f"\n⚠️  Currently at a loss (positions may still be open)")
                else:
                    print(f"\n➖ Breaking even")
    else:
        print(f"\n❌ No filled orders found")
        print(f"   NIJA may have just started or not traded yet")
except Exception as e:
    print(f"❌ Error checking filled orders: {e}")

# Step 5: Analysis & Recommendations
print(f"\n" + "="*80)
print(f"🎯 ANALYSIS & RECOMMENDATIONS")
print("="*80)

issues = []
recommendations = []

# Check position count
if len(advanced_trade_positions) > 8:
    issues.append(f"❌ {len(advanced_trade_positions)} positions > 8 max configured")
    recommendations.append("NIJA should sell down to 8 positions automatically")
elif len(advanced_trade_positions) == 8:
    print(f"\n✅ Position count: {len(advanced_trade_positions)}/8 (at maximum)")
else:
    print(f"\n✅ Position count: {len(advanced_trade_positions)}/8 (room for more)")

# Check consumer wallet
if len(consumer_positions) > 0:
    issues.append(f"⚠️  {len(consumer_positions)} positions in Consumer wallet (NIJA can't manage these)")
    recommendations.append(f"Transfer Consumer crypto to Advanced Trade OR sell manually")
    print(f"\n⚠️  Consumer Wallet Issue:")
    print(f"   {len(consumer_positions)} positions in Consumer wallet")
    print(f"   These are NOT managed by NIJA's trading bot")
    print(f"   Solution: Transfer to Advanced Trade or sell via Coinbase app")

# Check cash reserves
if usd_balance + usdc_balance < 10:
    issues.append(f"⚠️  Low cash: ${usd_balance + usdc_balance:.2f} < $10")
    recommendations.append("NIJA needs cash to open new positions - consider selling some crypto")

# Check if selling
try:
    filled_orders = client.list_orders(order_status='FILLED', limit=20)
    orders = getattr(filled_orders, 'orders', [])
    sell_count = sum(1 for o in orders if getattr(o, 'side', '') == 'SELL')
    
    if sell_count == 0 and len(advanced_trade_positions) > 0:
        issues.append(f"⚠️  No recent SELL orders but {len(advanced_trade_positions)} positions open")
        recommendations.append("Check if positions have hit profit targets or if bot is running")
except:
    pass

print(f"\n" + "="*80)
if issues:
    print(f"⚠️  ISSUES DETECTED:")
    for issue in issues:
        print(f"   {issue}")
    
    print(f"\n💡 RECOMMENDATIONS:")
    for rec in recommendations:
        print(f"   • {rec}")
else:
    print(f"✅ NO ISSUES DETECTED - NIJA IS OPERATING NORMALLY")

print(f"\n" + "="*80)
print(f"📋 NEXT STEPS:")
print("="*80)
print(f"""
1. Check Railway Logs:
   • Visit: https://railway.app
   • Look for: "SELL order" or "Closing position"
   • Verify: Bot is running without errors

2. Monitor for Sells:
   • Positions sell when +6% profit OR -2% loss
   • Check back in 30-60 minutes
   • Run: python3 verify_nija_selling_now.py

3. If Consumer Wallet has crypto:
   • Run: python3 enable_nija_profit.py
   • Or transfer manually to Advanced Trade
   • This consolidates everything for NIJA to manage

4. Force Sell (Emergency):
   • If needed: python3 direct_sell.py
   • Manually liquidate positions to reset
""")

print("="*80 + "\n")
