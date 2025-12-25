#!/usr/bin/env python3
"""
COMPREHENSIVE SELL CHECK - Find EVERYTHING that can be sold
"""
import os
import sys
from dotenv import load_dotenv
load_dotenv()

sys.path.append('/workspaces/Nija/bot')
from coinbase.rest import RESTClient

print("\n" + "="*80)
print("🔥 COMPREHENSIVE SELL DIAGNOSTIC")
print("="*80)

api_key = os.getenv("COINBASE_API_KEY")
api_secret = os.getenv("COINBASE_API_SECRET")

client = RESTClient(api_key=api_key, api_secret=api_secret)

# 1. CHECK ALL ACCOUNTS
print("\n📊 SCANNING ALL ACCOUNTS (Consumer + Advanced Trade)...")
accounts_resp = client.get_accounts()
accounts = getattr(accounts_resp, 'accounts', [])

consumer_usd = 0
consumer_usdc = 0
trading_usd = 0
trading_usdc = 0
crypto_positions = []

for account in accounts:
    currency = getattr(account, 'currency', None)
    available = getattr(account, 'available_balance', None)
    
    if not currency or not available:
        continue
    
    balance = float(getattr(available, 'value', '0'))
    
    if balance > 0:
        account_type = getattr(account, 'type', 'UNKNOWN')
        
        if currency == 'USD':
            if 'CONSUMER' in account_type.upper():
                consumer_usd += balance
                print(f"   Consumer USD: ${balance:.2f} ❌ [CANNOT SELL VIA API]")
            else:
                trading_usd += balance
                print(f"   Advanced Trade USD: ${balance:.2f} ✅ [ALREADY USD]")
        elif currency == 'USDC':
            if 'CONSUMER' in account_type.upper():
                consumer_usdc += balance
                print(f"   Consumer USDC: ${balance:.2f} ❌ [CANNOT SELL VIA API]")
            else:
                trading_usdc += balance
                print(f"   Advanced Trade USDC: ${balance:.2f} ✅ [ALREADY STABLE]")
        else:
            # CRYPTO - THIS CAN BE SOLD
            crypto_positions.append({
                'currency': currency,
                'balance': balance,
                'account_type': account_type,
                'product_id': f"{currency}-USD"
            })
            print(f"   🪙 {currency}: {balance:.8f} [{account_type}] 🔥 CAN SELL")

# 2. SUMMARY
print("\n" + "="*80)
print("💰 BALANCE SUMMARY")
print("="*80)
print(f"Consumer USD:      ${consumer_usd:.2f}")
print(f"Consumer USDC:     ${consumer_usdc:.2f}")
print(f"Advanced Trade USD:  ${trading_usd:.2f}")
print(f"Advanced Trade USDC: ${trading_usdc:.2f}")
print(f"Crypto Positions:  {len(crypto_positions)}")

total_usd = consumer_usd + consumer_usdc + trading_usd + trading_usdc
print(f"\n💎 TOTAL USD/USDC: ${total_usd:.2f}")

# 3. WHAT CAN BE SOLD?
print("\n" + "="*80)
print("🔥 WHAT CAN BE SOLD RIGHT NOW?")
print("="*80)

if crypto_positions:
    print(f"\n✅ FOUND {len(crypto_positions)} CRYPTO POSITION(S) TO SELL:")
    for pos in crypto_positions:
        print(f"   • {pos['currency']}: {pos['balance']:.8f} → Sell to USD")
    
    print("\n🚀 READY TO SELL CRYPTO!")
    print("   Run: python3 find_and_sell_crypto.py")
else:
    print("\n❌ NO CRYPTO TO SELL")
    print("   You only have USD/USDC (already cash)")

# 4. CAN BOT TRADE?
print("\n" + "="*80)
print("🤖 CAN BOT TRADE/SELL?")
print("="*80)

tradeable_balance = trading_usdc if trading_usdc > 0 else trading_usd

if tradeable_balance >= 10:
    print(f"\n✅ YES! Bot can trade with ${tradeable_balance:.2f}")
    print(f"   Position size: ${tradeable_balance * 0.40:.2f} (40%)")
    print(f"   Bot will BUY crypto, then SELL for profit")
else:
    print(f"\n❌ NO! Trading balance: ${tradeable_balance:.2f}")
    print(f"   Need: $10.00 minimum")
    
    if consumer_usdc > 0 or consumer_usd > 0:
        print(f"\n   💡 YOU HAVE ${consumer_usd + consumer_usdc:.2f} in Consumer wallet")
        print(f"   👉 TRANSFER to Advanced Trade to enable bot trading")
        print(f"   🔗 https://www.coinbase.com/advanced-portfolio")

# 5. CURRENT BOT STATUS
print("\n" + "="*80)
print("🔄 WHAT IS BOT DOING RIGHT NOW?")
print("="*80)

if tradeable_balance >= 10:
    print("✅ Bot is SCANNING markets and EXECUTING trades")
    print("   - Buys crypto when RSI signals are strong")
    print("   - Sells at +6% profit or -2% stop loss")
elif len(crypto_positions) > 0:
    print("⚠️  Bot CANNOT trade (no Advanced Trade balance)")
    print("   BUT you can manually sell crypto with find_and_sell_crypto.py")
else:
    print("🚫 Bot CANNOT do anything:")
    print("   - No crypto to sell")
    print("   - No trading balance to buy")
    print("   - Funds stuck in Consumer wallet (API can't touch)")

print("\n" + "="*80)
print("🎯 NEXT STEPS")
print("="*80)

if len(crypto_positions) > 0:
    print("\n1️⃣  SELL CRYPTO IMMEDIATELY:")
    print("   python3 find_and_sell_crypto.py")
    print("\n2️⃣  Transfer any USD/USDC to Advanced Trade")
    print("\n3️⃣  Bot will start trading automatically")
elif tradeable_balance < 10:
    print("\n1️⃣  Transfer ${:.2f} from Consumer → Advanced Trade".format(consumer_usd + consumer_usdc))
    print("   https://www.coinbase.com/advanced-portfolio")
    print("\n2️⃣  Bot will automatically start trading")
else:
    print("\n✅ Bot is LIVE and trading!")
    print("   Check Railway logs to see trades")

print("="*80 + "\n")
