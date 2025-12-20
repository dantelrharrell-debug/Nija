#!/usr/bin/env python3
"""
DEEP DIAGNOSTIC - Check EVERYTHING across v2 and v3 APIs
"""
import os
import sys
import json
from dotenv import load_dotenv
load_dotenv()

sys.path.append('/workspaces/Nija/bot')
from coinbase.rest import RESTClient

print("\n" + "="*80)
print("🔬 DEEP COINBASE DIAGNOSTIC - ALL APIs")
print("="*80)

api_key = os.getenv("COINBASE_API_KEY")
api_secret = os.getenv("COINBASE_API_SECRET")

client = RESTClient(api_key=api_key, api_secret=api_secret)

# ============================================================================
# 1. V3 API - Advanced Trade Accounts (what bot uses)
# ============================================================================
print("\n📊 V3 API - ADVANCED TRADE ACCOUNTS")
print("="*80)

try:
    accounts_resp = client.get_accounts()
    accounts = getattr(accounts_resp, 'accounts', [])
    
    print(f"Total accounts found: {len(accounts)}")
    
    total_value = 0
    for i, account in enumerate(accounts, 1):
        currency = getattr(account, 'currency', 'UNKNOWN')
        available = getattr(account, 'available_balance', None)
        uuid = getattr(account, 'uuid', 'NO_UUID')
        account_type = getattr(account, 'type', 'UNKNOWN')
        name = getattr(account, 'name', 'NO_NAME')
        
        if available:
            balance_value = float(getattr(available, 'value', '0'))
            if balance_value > 0:
                total_value += balance_value if currency in ['USD', 'USDC'] else 0
                print(f"\n{i}. {currency}")
                print(f"   UUID: {uuid[:16]}...")
                print(f"   Type: {account_type}")
                print(f"   Name: {name}")
                print(f"   Balance: {balance_value}")
                print(f"   Available: ✅" if balance_value > 0 else "   Empty")
    
    print(f"\n💎 Total USD/USDC (v3): ${total_value:.2f}")
    
except Exception as e:
    print(f"❌ V3 API Error: {e}")

# ============================================================================
# 2. Check portfolios directly
# ============================================================================
print("\n" + "="*80)
print("🗂️  PORTFOLIO CHECK")
print("="*80)

try:
    # Get portfolios
    portfolios_resp = client.get_portfolios()
    portfolios = getattr(portfolios_resp, 'portfolios', [])
    
    print(f"Total portfolios: {len(portfolios)}")
    
    for i, portfolio in enumerate(portfolios, 1):
        name = getattr(portfolio, 'name', 'UNKNOWN')
        uuid = getattr(portfolio, 'uuid', 'NO_UUID')
        portfolio_type = getattr(portfolio, 'type', 'UNKNOWN')
        
        print(f"\n{i}. {name}")
        print(f"   UUID: {uuid}")
        print(f"   Type: {portfolio_type}")
        
except Exception as e:
    print(f"Portfolio check not available: {e}")

# ============================================================================
# 3. List ALL products (markets)
# ============================================================================
print("\n" + "="*80)
print("📈 ACTIVE PRODUCTS")
print("="*80)

try:
    products = client.get_products()
    product_list = getattr(products, 'products', [])
    
    print(f"Total products available: {len(product_list)}")
    
    # Show first 10
    print("\nFirst 10 markets:")
    for i, product in enumerate(product_list[:10], 1):
        product_id = getattr(product, 'product_id', 'UNKNOWN')
        status = getattr(product, 'status', 'UNKNOWN')
        print(f"   {i}. {product_id} - {status}")
        
except Exception as e:
    print(f"❌ Products Error: {e}")

# ============================================================================
# 4. Check transaction history
# ============================================================================
print("\n" + "="*80)
print("📜 RECENT TRANSACTIONS")
print("="*80)

try:
    # Try to get recent transactions
    transactions = client.get_transactions()
    
    if hasattr(transactions, 'data'):
        txs = transactions.data
        print(f"Recent transactions: {len(txs)}")
        
        for i, tx in enumerate(txs[:5], 1):
            print(f"\n{i}. {tx}")
    else:
        print("No recent transaction data available")
        
except Exception as e:
    print(f"Transaction history: {e}")

# ============================================================================
# 5. RAW RESPONSE DUMP
# ============================================================================
print("\n" + "="*80)
print("🔍 RAW ACCOUNT RESPONSE (for debugging)")
print("="*80)

try:
    accounts_resp = client.get_accounts()
    
    # Try to serialize to JSON for inspection
    if hasattr(accounts_resp, '__dict__'):
        print(json.dumps(accounts_resp.__dict__, indent=2, default=str))
    else:
        print(f"Response type: {type(accounts_resp)}")
        print(f"Response: {accounts_resp}")
        
except Exception as e:
    print(f"❌ Raw dump error: {e}")

# ============================================================================
# 6. FINAL VERDICT
# ============================================================================
print("\n" + "="*80)
print("🎯 DIAGNOSTIC SUMMARY")
print("="*80)

print("""
If you're seeing $0.00 everywhere:

1. ✅ API credentials are working (we connected successfully)
2. ❓ Account may be completely empty OR
3. ❓ Funds are in a different Coinbase account/profile OR
4. ❓ Using wrong API keys (different account)

VERIFY:
- Log into https://www.coinbase.com directly
- Check if you see money there
- Check which email/account you're logged into
- Compare to the API key's account

If money shows on website but not in API:
- Funds might be in Coinbase.com (not Advanced Trade)
- Need to deposit to Advanced Trade portfolio
""")

print("="*80 + "\n")
