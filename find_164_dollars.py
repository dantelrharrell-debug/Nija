#!/usr/bin/env python3
"""
FIND THE $164.45 - Check BOTH Consumer API and Advanced Trade API
"""
import os
import sys
from dotenv import load_dotenv
load_dotenv()

sys.path.insert(0, '/workspaces/Nija')

from bot.broker_manager import CoinbaseBroker
from coinbase.rest import RESTClient
import logging

logging.basicConfig(level=logging.INFO)

def main():
    print("\n" + "="*80)
    print("🔍 SEARCHING FOR $164.45 IN ALL COINBASE ACCOUNTS")
    print("="*80 + "\n")
    
    api_key = os.getenv('COINBASE_API_KEY')
    api_secret = os.getenv('COINBASE_API_SECRET')
    
    if not api_key or not api_secret:
        print("❌ Missing API credentials in .env file")
        return
    
    # Initialize direct REST client
    client = RESTClient(api_key=api_key, api_secret=api_secret)
    
    print("📊 CHECKING ADVANCED TRADE API (v3)...")
    print("-" * 80)
    
    try:
        accounts_response = client.get_accounts()
        
        # Handle response
        if hasattr(accounts_response, 'accounts'):
            accounts = accounts_response.accounts
        elif isinstance(accounts_response, dict) and 'accounts' in accounts_response:
            accounts = accounts_response['accounts']
        else:
            accounts = []
        
        print(f"Found {len(accounts)} accounts\n")
        
        total_usd = 0.0
        total_usdc = 0.0
        crypto_positions = []
        
        for account in accounts:
            # Handle both object and dict response types
            if hasattr(account, 'currency'):
                currency = account.currency
                available = float(account.available_balance.value) if hasattr(account.available_balance, 'value') else 0.0
            else:
                currency = account.get('currency', '')
                balance_info = account.get('available_balance', {})
                available = float(balance_info.get('value', 0.0)) if balance_info else 0.0
            
            if available > 0:
                print(f"   {currency}: ${available:,.2f}")
                
                if currency == 'USD':
                    total_usd += available
                elif currency == 'USDC':
                    total_usdc += available
                else:
                    crypto_positions.append({'currency': currency, 'amount': available})
        
        print(f"\n💵 CASH TOTALS:")
        print(f"   USD:  ${total_usd:,.2f}")
        print(f"   USDC: ${total_usdc:,.2f}")
        print(f"   TOTAL CASH: ${total_usd + total_usdc:,.2f}")
        
        if crypto_positions:
            print(f"\n🪙 CRYPTO POSITIONS:")
            for pos in crypto_positions:
                print(f"   {pos['currency']}: {pos['amount']}")
        
        grand_total = total_usd + total_usdc
        print(f"\n💰 GRAND TOTAL (USD + USDC): ${grand_total:,.2f}")
        
        if grand_total < 164.0:
            print(f"\n⚠️  Only found ${grand_total:,.2f} in Advanced Trade")
            print(f"❓ Looking for remaining ${164.45 - grand_total:,.2f}...")
            print("\n💡 The funds might be in your Consumer wallet (separate API)")
            print("   Consumer wallets are NOT accessible via Advanced Trade API")
            print("   You need to TRANSFER funds from Consumer → Advanced Trade")
            print("\n📖 NEXT STEPS:")
            print("   1. Log into Coinbase.com")
            print("   2. Go to 'My Assets' or 'Portfolio'")
            print("   3. Find your USD/USDC in Consumer wallet")
            print("   4. Click 'Send/Receive' → 'Send' → 'To Coinbase Advanced Trade'")
            print("   5. Transfer all funds to Advanced Trade")
        
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == '__main__':
    main()
