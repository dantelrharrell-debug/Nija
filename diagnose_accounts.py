#!/usr/bin/env python3
"""
Diagnose Coinbase account balances and fund distribution.
Shows which accounts have available vs held balances.
"""

import os
import sys
import logging
from dotenv import load_dotenv

# Load environment
load_dotenv()

try:
    from coinbase.rest import RESTClient
except ImportError:
    print("❌ coinbase-advanced-py not installed")
    sys.exit(1)

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)s | %(message)s'
)
logger = logging.getLogger(__name__)

def diagnose_accounts():
    """Diagnose Coinbase account structure and balances."""
    
    # Get credentials from environment
    api_key = os.getenv("COINBASE_API_KEY")
    api_secret = os.getenv("COINBASE_API_SECRET")
    api_passphrase = os.getenv("COINBASE_API_PASSPHRASE", "")
    
    if not api_key or not api_secret:
        logger.error("❌ Missing COINBASE_API_KEY or COINBASE_API_SECRET")
        sys.exit(1)
    
    try:
        # Create client
        client = RESTClient(
            api_key=api_key,
            api_secret=api_secret,
            api_passphrase=api_passphrase
        )
        
        logger.info("✅ Connected to Coinbase Advanced Trade API")
        logger.info("=" * 70)
        logger.info("ACCOUNT BALANCE DIAGNOSIS")
        logger.info("=" * 70)
        
        # Fetch all accounts
        accounts = client.get_accounts()
        
        if not accounts or 'accounts' not in accounts:
            logger.error("❌ No accounts response from Coinbase")
            return
        
        total_available = 0.0
        total_held = 0.0
        
        # Display each account
        logger.info(f"\nTotal accounts: {len(accounts['accounts'])}\n")
        logger.info(f"{'Currency':<12} | {'Available':<15} | {'Held':<15} | {'Total':<15}")
        logger.info("-" * 70)
        
        for account in accounts['accounts']:
            currency = account.get('currency', '?')
            available = float(account.get('available_balance', {}).get('value', 0))
            held = float(account.get('hold', {}).get('value', 0))
            total = available + held
            
            total_available += available
            total_held += held
            
            logger.info(
                f"{currency:<12} | ${available:>13.2f} | ${held:>13.2f} | ${total:>13.2f}"
            )
        
        logger.info("-" * 70)
        logger.info(
            f"{'TOTAL':<12} | ${total_available:>13.2f} | ${total_held:>13.2f} | ${total_available + total_held:>13.2f}"
        )
        logger.info("=" * 70)
        
        # Recommendations
        logger.info("\n📋 RECOMMENDATIONS:\n")
        if total_available < 10:
            logger.warning(
                "⚠️  Available balance is very low ($%.2f). "
                "Transfer funds to Advanced Trade in Coinbase UI." % total_available
            )
        else:
            logger.info("✅ Sufficient available balance detected (%.2f)" % total_available)
        
        if total_held > 0:
            logger.info(
                f"ℹ️  You have ${total_held:.2f} on hold. This may be in pending orders."
            )
        
        logger.info(
            "\nℹ️  To trade:\n"
            "   1. Log into Coinbase.com\n"
            "   2. Go to Funding → Balances\n"
            "   3. Move funds to 'Advanced Trade' wallet\n"
            "   4. Restart the bot\n"
        )
        
    except Exception as e:
        logger.error(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    diagnose_accounts()
