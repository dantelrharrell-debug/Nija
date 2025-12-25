#!/usr/bin/env python3
"""
Debug script to investigate account balance issue
Checks all accounts from Coinbase API with detailed logging
"""

import os
import sys
import logging
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Configure logging for detailed output
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s | %(levelname)-8s | %(name)s | %(message)s'
)
logger = logging.getLogger("debug_balance")

def debug_balance():
    """Check account balance from Coinbase API directly"""
    
    logger.info("=" * 80)
    logger.info("NIJA BALANCE DEBUG SCRIPT")
    logger.info("=" * 80)
    
    # Check credentials
    api_key = os.getenv("COINBASE_API_KEY")
    api_secret = os.getenv("COINBASE_API_SECRET")
    
    logger.info("\n📋 CREDENTIAL CHECK:")
    logger.info(f"   COINBASE_API_KEY: {'✅ Set' if api_key else '❌ Missing'}")
    logger.info(f"   COINBASE_API_SECRET: {'✅ Set' if api_secret else '❌ Missing'}")
    
    if not api_key or not api_secret:
        logger.error("❌ Missing API credentials!")
        return False
    
    try:
        logger.info("\n🔐 Importing Coinbase SDK...")
        from coinbase.rest import RESTClient
        
        logger.info("🔌 Initializing RESTClient...")
        
        # Normalize PEM key if needed
        if '\\n' in api_secret:
            api_secret = api_secret.replace('\\n', '\n')
            logger.info("   ℹ️  Normalized escaped newlines in API_SECRET")
        
        client = RESTClient(
            api_key=api_key,
            api_secret=api_secret,
        )
        
        logger.info("✅ RESTClient created successfully")
        
        logger.info("\n🔍 Testing connection with GET /v3/accounts...")
        resp = client.get_accounts()
        logger.info(f"✅ Connection successful!")
        logger.info(f"   Response type: {type(resp)}")
        
        # Parse accounts
        logger.info("\n📊 PARSING ACCOUNTS:")
        accounts = getattr(resp, 'accounts', [])
        if isinstance(resp, dict):
            accounts = resp.get('accounts', [])
        
        logger.info(f"   Total accounts returned: {len(accounts)}")
        
        if len(accounts) == 0:
            logger.warning("⚠️  API returned ZERO accounts!")
            logger.info("   This could mean:")
            logger.info("   1. No portfolios created yet")
            logger.info("   2. API key doesn't have account permission")
            logger.info("   3. Wrong API key for this account")
            return False
        
        # Analyze each account
        logger.info("\n📋 DETAILED ACCOUNT BREAKDOWN:")
        logger.info("=" * 80)
        
        total_tradeable_usd = 0.0
        total_tradeable_usdc = 0.0
        total_consumer_usd = 0.0
        total_consumer_usdc = 0.0
        
        for i, account in enumerate(accounts, 1):
            logger.info(f"\n[Account {i}]")
            
            # Get account properties
            if isinstance(account, dict):
                currency = account.get('currency')
                name = account.get('name', 'Unknown')
                account_type = account.get('type', 'Unknown')
                platform = account.get('platform', 'Unknown')
                uuid = account.get('uuid', 'Unknown')
                available_obj = account.get('available_balance', {})
                hold_obj = account.get('hold', {})
                available = float(available_obj.get('value', 0) if isinstance(available_obj, dict) else available_obj or 0)
                hold = float(hold_obj.get('value', 0) if isinstance(hold_obj, dict) else hold_obj or 0)
            else:
                currency = getattr(account, 'currency', 'Unknown')
                name = getattr(account, 'name', 'Unknown')
                account_type = getattr(account, 'type', 'Unknown')
                platform = getattr(account, 'platform', 'Unknown')
                uuid = getattr(account, 'uuid', 'Unknown')
                available_obj = getattr(account, 'available_balance', None)
                hold_obj = getattr(account, 'hold', None)
                available = float(getattr(available_obj, 'value', 0) if available_obj else 0)
                hold = float(getattr(hold_obj, 'value', 0) if hold_obj else 0)
            
            logger.info(f"   Currency: {currency}")
            logger.info(f"   Name: {name}")
            logger.info(f"   Type: {account_type}")
            logger.info(f"   Platform: {platform}")
            logger.info(f"   UUID: {uuid}")
            logger.info(f"   Available: ${available:.2f}")
            logger.info(f"   On Hold: ${hold:.2f}")
            
            # Categorize account
            is_tradeable = (account_type == "ACCOUNT_TYPE_CRYPTO" or 
                          (platform and "ADVANCED_TRADE" in str(platform)))
            
            location = "✅ TRADEABLE (Advanced Trade)" if is_tradeable else "❌ CONSUMER (Not for API trading)"
            logger.info(f"   Status: {location}")
            
            # Track totals
            if currency in ("USD", "USDC"):
                if is_tradeable:
                    if currency == "USD":
                        total_tradeable_usd += available
                    else:
                        total_tradeable_usdc += available
                else:
                    if currency == "USD":
                        total_consumer_usd += available
                    else:
                        total_consumer_usdc += available
        
        # Summary
        logger.info("\n" + "=" * 80)
        logger.info("💰 BALANCE SUMMARY:")
        logger.info("=" * 80)
        logger.info(f"   Tradeable USD (Advanced Trade):  ${total_tradeable_usd:.2f} ✅")
        logger.info(f"   Tradeable USDC (Advanced Trade): ${total_tradeable_usdc:.2f} ✅")
        logger.info(f"   Consumer USD (NOT tradeable):    ${total_consumer_usd:.2f} ❌")
        logger.info(f"   Consumer USDC (NOT tradeable):   ${total_consumer_usdc:.2f} ❌")
        logger.info("-" * 80)
        
        trading_balance = total_tradeable_usd + total_tradeable_usdc
        logger.info(f"   🎯 AVAILABLE FOR TRADING: ${trading_balance:.2f}")
        logger.info("=" * 80)
        
        # Diagnosis
        logger.info("\n🔍 DIAGNOSIS:")
        if trading_balance == 0.0:
            logger.warning("⚠️  NO TRADING BALANCE DETECTED!")
            logger.info("\n   Possible causes:")
            logger.info("   1. ❌ Funds in Consumer wallet, NOT Advanced Trade")
            logger.info("      → Transfer to Advanced Trade: https://www.coinbase.com/advanced-portfolio")
            logger.info("   2. ❌ No Advanced Trade portfolio created")
            logger.info("      → Create one at: https://www.coinbase.com/advanced-portfolio")
            logger.info("   3. ❌ Wrong API key (for different account)")
            logger.info("      → Verify API key is from correct Coinbase account")
            logger.info("   4. ❌ API key missing account permissions")
            logger.info("      → Edit API key permissions to enable trading")
        else:
            logger.info(f"✅ Found ${trading_balance:.2f} available for trading")
            if trading_balance < 50.0:
                logger.warning(f"⚠️  Balance is below $50 minimum for profitable trading")
                logger.info(f"   Bot requires at least $50 to overcome 6% in fees")
        
        return True
        
    except ImportError as e:
        logger.error(f"❌ Failed to import Coinbase SDK: {e}")
        logger.info("   Run: pip install coinbase-advanced-py")
        return False
    except Exception as e:
        logger.error(f"❌ Error during balance check: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return False

if __name__ == "__main__":
    success = debug_balance()
    sys.exit(0 if success else 1)
