#!/usr/bin/env python3
"""Test Coinbase connection and check status"""

import os
import sys

# Load .env file manually
def load_env_file():
    env_path = os.path.join(os.path.dirname(__file__), '.env')
    if os.path.exists(env_path):
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    key, val = line.split('=', 1)
                    key = key.strip()
                    val = val.strip().strip('"').strip("'")
                    os.environ[key] = val

load_env_file()

# Add bot directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'bot'))

from broker_manager import CoinbaseBroker

def main():
    print("\n" + "="*80)
    print("TESTING COINBASE CONNECTION")
    print("="*80 + "\n")
    
    # Create broker
    broker = CoinbaseBroker()
    
    # Try to connect
    print("🔌 Attempting to connect to Coinbase Advanced Trade...\n")
    if not broker.connect():
        print("\n❌ Connection failed - please check credentials")
        return 1
    
    print("\n✅ Successfully connected!\n")
    
    # Get balance
    print("💰 Fetching account balance...\n")
    try:
        balance = broker.get_account_balance()
        
        print("="*80)
        print("ACCOUNT BALANCE")
        print("="*80)
        print(f"USD:              ${balance.get('usd', 0):.2f}")
        print(f"USDC:             ${balance.get('usdc', 0):.2f}")
        print(f"Trading Balance:  ${balance.get('trading_balance', 0):.2f}")
        
        # Show crypto holdings
        crypto = balance.get('crypto', {})
        if crypto:
            print(f"\n📊 Crypto Holdings:")
            for currency, amount in sorted(crypto.items()):
                if amount > 0:
                    print(f"  {currency}: {amount:.8f}")
        
        print("\n" + "="*80)
        
        # Get positions
        print("\n📈 Fetching open positions...\n")
        positions = broker.get_positions()
        
        if positions:
            print(f"Found {len(positions)} open position(s):")
            for pos in positions:
                symbol = pos.get('symbol', 'Unknown')
                size = pos.get('size', 0)
                value = pos.get('value', 0)
                print(f"  - {symbol}: {size:.8f} (${value:.2f})")
        else:
            print("No open positions")
        
        print("\n" + "="*80)
        
        return 0
        
    except Exception as e:
        print(f"\n❌ Error fetching data: {e}")
        import traceback
        traceback.print_exc()
        return 1

if __name__ == "__main__":
    sys.exit(main())
