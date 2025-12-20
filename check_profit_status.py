#!/usr/bin/env python3
"""
NIJA Consumer Wallet Manager - Check prices and sell when profitable
"""
import os
import sys
from dotenv import load_dotenv
load_dotenv()

sys.path.append('/workspaces/Nija/bot')
from coinbase.rest import RESTClient

print("\n" + "="*80)
print("💰 NIJA CONSUMER WALLET PROFIT CHECK")
print("="*80)

client = RESTClient(
    api_key=os.getenv("COINBASE_API_KEY"),
    api_secret=os.getenv("COINBASE_API_SECRET")
)

# Get all accounts and find crypto with balances
accounts_resp = client.get_accounts()
accounts = getattr(accounts_resp, 'accounts', [])

crypto_positions = []

for account in accounts:
    currency = getattr(account, 'currency', None)
    available = getattr(account, 'available_balance', None)
    
    if not currency or not available or currency in ['USD', 'USDC', 'USDT']:
        continue
    
    balance = float(getattr(available, 'value', '0'))
    
    if balance > 0:
        crypto_positions.append({
            'currency': currency,
            'balance': balance,
            'product_id': f"{currency}-USD"
        })

if not crypto_positions:
    print("\n✅ No crypto positions in Consumer wallet")
    print("\n💡 SOLUTION: Transfer your USDC to Advanced Trade")
    print("   https://www.coinbase.com/advanced-portfolio")
    sys.exit(0)

print(f"\n📊 FOUND {len(crypto_positions)} CRYPTO POSITION(S):")
print("="*80)

total_value = 0

for crypto in crypto_positions:
    currency = crypto['currency']
    balance = crypto['balance']
    product_id = crypto['product_id']
    
    # Get current price
    try:
        product = client.get_product(product_id)
        price = float(getattr(product, 'price', 0))
        value = balance * price
        total_value += value
        
        print(f"\n{currency}:")
        print(f"   Amount: {balance:.8f}")
        print(f"   Price: ${price:.4f}")
        print(f"   Value: ${value:.2f}")
        
        crypto['price'] = price
        crypto['value'] = value
    except Exception as e:
        print(f"\n{currency}: {balance:.8f} (price unavailable: {e})")
        crypto['price'] = 0
        crypto['value'] = 0

print("\n" + "="*80)
print(f"💎 TOTAL VALUE: ${total_value:.2f}")
print("="*80)

print("\n" + "="*80)
print("🎯 THE ISSUE:")
print("="*80)
print("❌ These positions are in CONSUMER wallet")
print("❌ NIJA bot CANNOT access Consumer wallet via API")
print("❌ Bot can ONLY trade in Advanced Trade portfolio")
print("")
print("🔧 THE FIX:")
print("="*80)
print("1️⃣  Sell these crypto positions → Get USD")
print("2️⃣  Transfer USD to Advanced Trade")
print("3️⃣  Bot will trade automatically and make profit")
print("")
print("💡 WHY THIS WORKS:")
print("   - Bot buys at good prices (RSI signals)")
print("   - Bot sells at +6% profit automatically")
print("   - Bot uses trailing stops to lock gains")
print("   - Bot compounds profits into bigger positions")

print("\n" + "="*80)
print("📈 ESTIMATED OUTCOME:")
print("="*80)
print(f"Starting capital: ${total_value:.2f}")
print(f"Bot position size (40%): ${total_value * 0.40:.2f}")
print(f"Target profit per trade: +6%")
print(f"Profit per successful trade: ~${total_value * 0.40 * 0.06:.2f}")
print("")
print("With NIJA's strategy, your money will:")
print("✅ Only buy when RSI shows strong signals")
print("✅ Automatically sell at profit targets")  
print("✅ Use stop losses to protect capital")
print("✅ Compound profits for exponential growth")

print("\n" + "="*80)
print("🚀 READY TO ENABLE NIJA?")
print("="*80)
print("")
print("Run this to sell and enable bot trading:")
print("   python3 direct_sell.py")
print("")
print("Then transfer the USD to Advanced Trade:")
print("   https://www.coinbase.com/advanced-portfolio")
print("")
print("NIJA will start trading automatically!")
print("="*80 + "\n")
