#!/usr/bin/env python3
"""
QUICK VERIFICATION: Are the 13 trades still there? How much are we losing?
Simplest possible check
"""
import os
from dotenv import load_dotenv

load_dotenv()

try:
    from coinbase.rest import RESTClient
    
    client = RESTClient(
        api_key=os.getenv('COINBASE_API_KEY'),
        api_secret=os.getenv('COINBASE_API_SECRET')
    )
    
    # Get positions
    accounts = client.get_accounts()
    positions = []
    cash = 0
    
    for acc in accounts.accounts:
        bal = float(acc.available_balance.value)
        if bal > 0:
            if acc.currency in ['USD', 'USDC']:
                cash += bal
            else:
                positions.append((acc.currency, bal))
    
    print(f"\n🚨 CURRENT STATUS:")
    print(f"   Open Positions: {len(positions)}")
    print(f"   Cash: ${cash:.2f}")
    
    if positions:
        print(f"\n📦 Positions held:")
        total_value = 0
        for curr, bal in positions:
            try:
                price = float(client.get_product(f"{curr}-USD").price)
                value = bal * price
                total_value += value
                print(f"   • {curr}: {bal:.8f} @ ${price:.4f} = ${value:.2f}")
            except:
                print(f"   • {curr}: {bal:.8f}")
        
        print(f"\n💰 PORTFOLIO: ${cash + total_value:.2f} total")
        if total_value > 0:
            print(f"   (${cash:.2f} cash + ${total_value:.2f} in crypto)")
    
    print()

except Exception as e:
    print(f"Error: {e}")
    print("Make sure .env has COINBASE_API_KEY and COINBASE_API_SECRET")
