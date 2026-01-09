#!/usr/bin/env python3
"""
Check Kraken balance for user account (Daivon Frazier)
Since master Kraken credentials are not configured, only checking user balance.
"""

import os
import sys
import logging

# Setup path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'bot'))

# Try to load dotenv
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(message)s'
)

from broker_manager import KrakenBroker, AccountType

def check_user_kraken_balance():
    """Check Daivon's Kraken balance."""
    
    print("")
    print("=" * 70)
    print("KRAKEN BALANCE CHECK - USER ACCOUNT (Daivon Frazier)")
    print("=" * 70)
    print("")
    
    # Create user Kraken broker
    broker = KrakenBroker(account_type=AccountType.USER, user_id='daivon_frazier')
    
    # Connect
    if broker.connect():
        print("")
        balance = broker.get_account_balance()
        print("")
        print("=" * 70)
        print(f"USER KRAKEN BALANCE: ${balance:,.2f}")
        print("=" * 70)
        print("")
        return balance
    else:
        print("")
        print("=" * 70)
        print("ERROR: Could not connect to user Kraken account")
        print("=" * 70)
        print("")
        return 0.0


if __name__ == "__main__":
    try:
        balance = check_user_kraken_balance()
        
        print("")
        print("=" * 70)
        print("ANSWER TO QUESTION:")
        print("=" * 70)
        print("")
        print(f"User (Daivon Frazier) Kraken account balance: ${balance:,.2f}")
        print("")
        print("Master Kraken account: NOT CONFIGURED")
        print("  - Master Kraken credentials have not been added to .env")
        print("  - Only user account can currently trade on Kraken")
        print("  - See MASTER_KRAKEN_SETUP_NEEDED.txt for setup instructions")
        print("")
        print("=" * 70)
        print("")
        
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
