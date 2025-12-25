#!/usr/bin/env python3
import os
import sys
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

sys.path.append('/workspaces/Nija/bot')
from broker_manager import CoinbaseBroker

print("\n" + "="*80)
print("💰 CHECKING YOUR COINBASE BALANCE")
print("="*80)

broker = CoinbaseBroker()
if broker.connect():
    balance = broker.get_account_balance()
    
    print("\n" + "="*80)
    print("📊 BALANCE BREAKDOWN")
    print("="*80)
    
    consumer_usd = balance.get('consumer_usd', 0)
    consumer_usdc = balance.get('consumer_usdc', 0)
    trading_usd = balance.get('usd', 0)
    trading_usdc = balance.get('usdc', 0)
    trading_balance = balance.get('trading_balance', 0)
    crypto = balance.get('crypto', {})
    
    print(f"\n🏦 Consumer Wallets (NOT tradeable via API):")
    print(f"   USD:  ${consumer_usd:.2f}")
    print(f"   USDC: ${consumer_usdc:.2f}")
    
    print(f"\n✅ Advanced Trade (TRADEABLE):")
    print(f"   USD:  ${trading_usd:.2f}")
    print(f"   USDC: ${trading_usdc:.2f}")
    print(f"   → Trading Balance: ${trading_balance:.2f}")
    
    if crypto:
        print(f"\n🪙 Crypto Holdings:")
        total_crypto_value = 0
        for symbol, amount in crypto.items():
            if amount > 0:
                print(f"   {symbol}: {amount:.8f}")
    
    total = consumer_usd + consumer_usdc + trading_balance
    print(f"\n💎 TOTAL ACCOUNT VALUE: ${total:.2f}")
    
    print("\n" + "="*80)
    print("🤖 BOT STATUS")
    print("="*80)
    
    if trading_balance >= 10:
        print(f"✅ READY TO TRADE!")
        print(f"   Available: ${trading_balance:.2f}")
        print(f"   Position Size (40%): ${trading_balance * 0.40:.2f}")
        print(f"   Min Coinbase Order: $5.00")
        print(f"   → Can place trades: YES")
    else:
        print(f"⚠️  INSUFFICIENT TRADING BALANCE: ${trading_balance:.2f}")
        if consumer_usdc > 0 or consumer_usd > 0:
            print(f"\n   You have ${consumer_usd + consumer_usdc:.2f} in Consumer wallets")
            print(f"   Transfer to Advanced Trade to enable trading")
        else:
            print(f"   Add funds to your Coinbase account")
    
    print("="*80 + "\n")
else:
    print("❌ Failed to connect to Coinbase")
