#!/usr/bin/env python3
"""
Quick balance check - saves output to file
"""
import os
import sys
from dotenv import load_dotenv
load_dotenv()

sys.path.append('/workspaces/Nija/bot')
from coinbase.rest import RESTClient

output = []
output.append("="*80)
output.append("COINBASE ACCOUNT BALANCE CHECK")
output.append("="*80)

try:
    client = RESTClient(
        api_key=os.getenv("COINBASE_API_KEY"),
        api_secret=os.getenv("COINBASE_API_SECRET")
    )
    
    output.append("\n✅ Connected to Coinbase API")
    
    accounts_resp = client.get_accounts()
    accounts = getattr(accounts_resp, 'accounts', [])
    
    output.append(f"\n📊 Found {len(accounts)} accounts\n")
    
    has_balance = False
    total_usd = 0
    total_usdc = 0
    crypto_count = 0
    
    for account in accounts:
        currency = getattr(account, 'currency', 'UNKNOWN')
        available_obj = getattr(account, 'available_balance', None)
        account_type = getattr(account, 'type', 'UNKNOWN')
        
        if not available_obj:
            continue
        
        balance = float(getattr(available_obj, 'value', '0'))
        
        if balance > 0:
            has_balance = True
            output.append(f"\n💰 {currency}:")
            output.append(f"   Balance: {balance:.8f}")
            output.append(f"   Type: {account_type}")
            
            if currency == 'USD':
                total_usd += balance
            elif currency == 'USDC':
                total_usdc += balance
            elif currency not in ['USDT']:
                crypto_count += 1
    
    output.append("\n" + "="*80)
    output.append("SUMMARY:")
    output.append("="*80)
    output.append(f"USD:  ${total_usd:.2f}")
    output.append(f"USDC: ${total_usdc:.2f}")
    output.append(f"Crypto positions: {crypto_count}")
    output.append(f"Total cash: ${total_usd + total_usdc:.2f}")
    
    if has_balance:
        output.append("\n✅ YOU HAVE FUNDS!")
        if crypto_count > 0:
            output.append(f"\n🎯 NEXT STEP: Run enable_nija_profit.py to sell crypto")
        if total_usd + total_usdc > 0:
            output.append(f"\n🎯 NEXT STEP: Transfer ${total_usd + total_usdc:.2f} to Advanced Trade")
    else:
        output.append("\n❌ NO BALANCES FOUND")
        output.append("\nPossible reasons:")
        output.append("1. Account is empty")
        output.append("2. API permissions issue")
        output.append("3. Funds already moved")
    
except Exception as e:
    output.append(f"\n❌ ERROR: {e}")

# Save to file
with open('/workspaces/Nija/balance_check_result.txt', 'w') as f:
    f.write('\n'.join(output))

# Also print to console
for line in output:
    print(line)

print("\n" + "="*80)
print("Results saved to: balance_check_result.txt")
print("="*80)
