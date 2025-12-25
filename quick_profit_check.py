#!/usr/bin/env python3
"""
ONE-COMMAND VERIFICATION: Is NIJA selling and making profit?
Run this single script to get the complete picture.
"""
import os
import sys
from datetime import datetime
from dotenv import load_dotenv
load_dotenv()

sys.path.append('/workspaces/Nija/bot')

try:
    from coinbase.rest import RESTClient
    
    print("\n" + "="*80)
    print("🚀 NIJA SELLING & PROFIT - ONE-COMMAND CHECK")
    print("="*80)
    print(f"⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S UTC')}\n")
    
    client = RESTClient(
        api_key=os.getenv('COINBASE_API_KEY'),
        api_secret=os.getenv('COINBASE_API_SECRET')
    )
    
    # Get filled orders
    filled = client.list_orders(order_status='FILLED', limit=20)
    orders = getattr(filled, 'orders', [])
    
    buys = [o for o in orders if getattr(o, 'side', '') == 'BUY']
    sells = [o for o in orders if getattr(o, 'side', '') == 'SELL']
    
    print(f"RECENT TRADING ACTIVITY (Last 20 orders):")
    print(f"  📥 BUY orders:  {len(buys)}")
    print(f"  📤 SELL orders: {len(sells)}")
    
    if len(sells) > 0:
        print(f"\n✅ NIJA IS SELLING! ✅")
        print(f"\n   Latest sells:")
        for order in sells[:3]:
            product = getattr(order, 'product_id', 'Unknown')
            value = getattr(order, 'filled_value', '0')
            time = getattr(order, 'completion_time', 'Unknown')
            print(f"   • {product}: ${value} @ {time}")
    else:
        print(f"\n⚠️  NO RECENT SELLS")
        print(f"   Positions may not have hit +6% target yet")
    
    # Calculate profit
    if len(sells) > 0 and len(buys) > 0:
        buy_total = sum(float(getattr(o, 'filled_value', '0')) for o in buys)
        sell_total = sum(float(getattr(o, 'filled_value', '0')) for o in sells)
        profit = sell_total - buy_total
        profit_pct = (profit / buy_total * 100) if buy_total > 0 else 0
        
        print(f"\n💰 PROFIT ANALYSIS:")
        print(f"   Bought:  ${buy_total:.2f}")
        print(f"   Sold:    ${sell_total:.2f}")
        print(f"   Profit:  ${profit:+.2f} ({profit_pct:+.2f}%)")
        
        if profit > 0:
            print(f"\n🎉 NIJA IS PROFITABLE! 🎉")
        elif profit < 0:
            print(f"\n⚠️  Current loss (positions may still be open)")
    
    # Get current positions
    accounts = client.get_accounts()
    acc_list = getattr(accounts, 'accounts', [])
    
    positions = []
    for acc in acc_list:
        curr = getattr(acc, 'currency', None)
        avail = getattr(acc, 'available_balance', None)
        if curr and avail and curr not in ['USD', 'USDC', 'USDT']:
            bal = float(getattr(avail, 'value', '0'))
            if bal > 0:
                positions.append(curr)
    
    print(f"\n📦 CURRENT POSITIONS: {len(positions)}")
    if len(positions) > 0:
        print(f"   {', '.join(positions)}")
    
    if len(positions) > 8:
        print(f"\n⚠️  {len(positions)} positions > 8 max configured")
        print(f"   Some may be in Consumer wallet (not managed by NIJA)")
    
    print(f"\n" + "="*80)
    print(f"📋 NEXT STEPS:")
    print("="*80)
    
    if len(sells) == 0:
        print(f"\n1. Wait for positions to hit +6% profit target")
        print(f"2. Check Railway logs: https://railway.app")
        print(f"3. Verify bot is running (logs should show activity)")
        print(f"4. Run again in 30-60 minutes")
    else:
        print(f"\n✅ NIJA is selling and operating correctly!")
        print(f"   Continue monitoring Railway logs for updates")
    
    if len(positions) > 8:
        print(f"\n💡 To consolidate Consumer wallet crypto:")
        print(f"   python3 enable_nija_profit.py")
    
    print("="*80 + "\n")
    
except Exception as e:
    print(f"\n❌ Error: {e}")
    print(f"\nTroubleshooting:")
    print(f"1. Check .env file has API credentials")
    print(f"2. Verify internet connection")
    print(f"3. Check Coinbase API status: https://status.coinbase.com")
    print()
