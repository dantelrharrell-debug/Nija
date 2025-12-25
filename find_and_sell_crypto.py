#!/usr/bin/env python3
"""
Find ALL crypto holdings (Consumer + Advanced Trade) and sell them
"""
import os
import sys
import time
from dotenv import load_dotenv

load_dotenv()

sys.path.append('/workspaces/Nija/bot')
from coinbase.rest import RESTClient

print("\n" + "="*80)
print("🔍 FINDING ALL CRYPTO HOLDINGS")
print("="*80)

api_key = os.getenv("COINBASE_API_KEY")
api_secret = os.getenv("COINBASE_API_SECRET")

if not api_key or not api_secret:
    print("❌ Missing credentials")
    sys.exit(1)

client = RESTClient(api_key=api_key, api_secret=api_secret)

# Get ALL accounts
print("\n📊 Scanning all accounts...")
accounts_resp = client.get_accounts()
accounts = getattr(accounts_resp, 'accounts', [])

crypto_found = []
usd_balances = {}

for account in accounts:
    currency = getattr(account, 'currency', None)
    available_balance = getattr(account, 'available_balance', None)
    
    if not currency or not available_balance:
        continue
    
    balance_value = getattr(available_balance, 'value', '0')
    balance = float(balance_value)
    
    if balance > 0:
        if currency in ['USD', 'USDC', 'USDT']:
            usd_balances[currency] = balance
            print(f"   💵 {currency}: ${balance:.2f}")
        else:
            # This is crypto - add to sell list
            crypto_found.append({
                'currency': currency,
                'balance': balance,
                'product_id': f"{currency}-USD"
            })
            print(f"   🪙 {currency}: {balance:.8f} 🔥 CAN SELL")

print("\n" + "="*80)
print("📊 SUMMARY")
print("="*80)
print(f"USD/USDC: ${sum(usd_balances.values()):.2f}")
print(f"Crypto positions: {len(crypto_found)}")

if not crypto_found:
    print("\n✅ NO CRYPTO TO SELL - You only have USD/USDC")
    print("\n🔧 YOUR ISSUE:")
    print("   Consumer USDC: $57.54 (cannot trade via API)")
    print("   Advanced Trade: $0.00 (can trade but empty)")
    print("\n👉 SOLUTION: Transfer $57.54 from Consumer to Advanced Trade")
    print("   https://www.coinbase.com/advanced-portfolio")
    sys.exit(0)

# Show what will be sold
print("\n" + "="*80)
print("🔥 CRYPTO TO SELL")
print("="*80)

for crypto in crypto_found:
    print(f"   • {crypto['currency']}: {crypto['balance']:.8f}")

confirm = input("\n❓ Sell ALL crypto now? Type 'SELL NOW' to proceed: ")

if confirm.strip() != "SELL NOW":
    print("\n❌ Cancelled")
    sys.exit(0)

# Sell all crypto
print("\n" + "="*80)
print("💸 SELLING CRYPTO...")
print("="*80)

sold_count = 0
failed_count = 0
total_proceeds = 0

for crypto in crypto_found:
    currency = crypto['currency']
    balance = crypto['balance']
    product_id = f"{currency}-USD"
    
    print(f"\n📤 Selling {balance:.8f} {currency}...")
    
    try:
        # Place market sell order
        from uuid import uuid4
        order = client.market_order_sell(
            client_order_id=str(uuid4()),
            product_id=product_id,
            base_size=str(balance)
        )
        
        # Check if successful - safely serialize Coinbase SDK response objects
        if isinstance(order, dict):
            order_dict = order
        else:
            # Convert object to dict safely
            try:
                import json
                json_str = json.dumps(order, default=str)
                order_dict = json.loads(json_str)
            except Exception:
                # Fallback: just try __dict__
                order_dict = {}
                if hasattr(order, '__dict__'):
                    for k, v in order.__dict__.items():
                        if isinstance(v, (dict, list, str, int, float, bool, type(None))):
                            order_dict[k] = v
                        else:
                            order_dict[k] = str(v)
        
        success = order_dict.get('success', True)
        
        if success:
            sold_count += 1
            print(f"   ✅ SOLD {currency}")
            time.sleep(0.5)  # Brief pause
        else:
            failed_count += 1
            error = order_dict.get('error_response', {})
            print(f"   ❌ FAILED: {error}")
    
    except Exception as e:
        failed_count += 1
        print(f"   ❌ ERROR: {str(e)}")

print("\n" + "="*80)
print("📊 RESULTS")
print("="*80)
print(f"Sold: {sold_count}/{len(crypto_found)}")
print(f"Failed: {failed_count}")

if sold_count > 0:
    print("\n⏳ Waiting 5 seconds for settlement...")
    time.sleep(5)
    
    print("\n🔄 Checking new balance...")
    from broker_manager import CoinbaseBroker
    broker = CoinbaseBroker()
    if broker.connect():
        balance = broker.get_account_balance()
        trading_balance = balance.get('trading_balance', 0)
        consumer_total = balance.get('consumer_usd', 0) + balance.get('consumer_usdc', 0)
        
        print("\n" + "="*80)
        print("💰 UPDATED BALANCE")
        print("="*80)
        print(f"Consumer USD/USDC: ${consumer_total:.2f}")
        print(f"Advanced Trade: ${trading_balance:.2f} ✅ [TRADABLE]")
        
        if trading_balance >= 10:
            print("\n✅ READY TO TRADE!")
            print("   Bot can now execute orders")
        else:
            print("\n⚠️  Still need to transfer Consumer → Advanced Trade")
            print("   https://www.coinbase.com/advanced-portfolio")

print("\n" + "="*80)
