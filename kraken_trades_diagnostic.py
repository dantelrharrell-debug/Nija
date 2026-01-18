#!/usr/bin/env python3
"""
NIJA Kraken Trading Diagnostic Tool
====================================

Comprehensive diagnostic to identify why Kraken is not trading for master and users.

This script checks:
1. API credentials configuration
2. Kraken API connectivity  
3. Account balances
4. Trading permissions
5. Copy trading system initialization
6. Recent trades (if any)

Run with: python3 diagnose_kraken_trades.py
"""

import os
import sys
import json
import logging
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(message)s'
)
logger = logging.getLogger(__name__)

# Try to load dotenv if available
try:
    from dotenv import load_dotenv
    load_dotenv()
    logger.info("✅ Loaded .env file\n")
except ImportError:
    logger.warning("⚠️  python-dotenv not installed, relying on system environment variables\n")

# Constants
SEPARATOR_FULL = "=" * 80
SEPARATOR_SUB = "-" * 80


def print_header(title: str):
    """Print formatted section header."""
    logger.info("")
    logger.info(SEPARATOR_FULL)
    logger.info(f"🔍 {title}")
    logger.info(SEPARATOR_FULL)
    logger.info("")


def print_subheader(title: str):
    """Print formatted subsection header."""
    logger.info(SEPARATOR_SUB)
    logger.info(f"   {title}")
    logger.info(SEPARATOR_SUB)


def check_credential(var_name: str, account_name: str) -> Tuple[bool, str]:
    """
    Check if a credential environment variable is set and valid.
    
    Returns:
        Tuple of (is_valid, status_message)
    """
    value_raw = os.getenv(var_name, "")
    value = value_raw.strip()
    
    # Check if set
    if not value_raw:
        return False, f"❌ NOT SET - {account_name} will NOT trade"
    
    # Check for whitespace-only (common error)
    if value_raw and not value:
        return False, f"⚠️  SET but EMPTY after removing whitespace - {account_name} will NOT trade"
    
    # Check minimum length (Kraken API keys are typically 56+ characters)
    if len(value) < 20:
        return False, f"⚠️  SET but TOO SHORT ({len(value)} chars) - likely invalid"
    
    # Obscure the value for display
    obscured = value[:8] + "..." + value[-8:] if len(value) > 16 else "***"
    return True, f"✅ SET ({len(value)} chars): {obscured}"


def check_master_credentials() -> bool:
    """Check Kraken master account credentials."""
    print_subheader("1️⃣  MASTER ACCOUNT (NIJA System)")
    
    # Check primary credentials
    key_valid, key_msg = check_credential("KRAKEN_MASTER_API_KEY", "MASTER")
    secret_valid, secret_msg = check_credential("KRAKEN_MASTER_API_SECRET", "MASTER")
    
    logger.info(f"   KRAKEN_MASTER_API_KEY:    {key_msg}")
    logger.info(f"   KRAKEN_MASTER_API_SECRET: {secret_msg}")
    logger.info("")
    
    # Check legacy credentials as fallback
    if not (key_valid and secret_valid):
        logger.info("   📌 Checking legacy credentials (fallback)...")
        legacy_key_valid, legacy_key_msg = check_credential("KRAKEN_API_KEY", "MASTER (legacy)")
        legacy_secret_valid, legacy_secret_msg = check_credential("KRAKEN_API_SECRET", "MASTER (legacy)")
        
        logger.info(f"   KRAKEN_API_KEY:           {legacy_key_msg}")
        logger.info(f"   KRAKEN_API_SECRET:        {legacy_secret_msg}")
        logger.info("")
        
        if legacy_key_valid and legacy_secret_valid:
            logger.info("   ✅ Legacy credentials found - will be used as fallback")
            return True
    
    if key_valid and secret_valid:
        logger.info("   ✅ MASTER credentials properly configured")
        return True
    else:
        logger.info("   ❌ MASTER credentials MISSING or INVALID")
        logger.info("   → Master account will NOT trade on Kraken")
        return False


def check_user_credentials() -> List[Dict]:
    """Check Kraken user account credentials."""
    print_subheader("2️⃣  USER ACCOUNTS")
    
    # Load user config
    config_path = Path(__file__).parent / "config" / "users" / "retail_kraken.json"
    
    if not config_path.exists():
        logger.error(f"   ❌ User config not found: {config_path}")
        return []
    
    try:
        with open(config_path, 'r') as f:
            users_config = json.load(f)
    except Exception as e:
        logger.error(f"   ❌ Failed to load user config: {e}")
        return []
    
    if not isinstance(users_config, list):
        logger.error("   ❌ Invalid user config format (expected list)")
        return []
    
    logger.info(f"   Found {len(users_config)} user(s) in retail_kraken.json")
    logger.info("")
    
    valid_users = []
    
    for idx, user in enumerate(users_config, 1):
        user_id = user.get('user_id', '')
        name = user.get('name', 'Unknown')
        enabled = user.get('enabled', False)
        
        logger.info(f"   User #{idx}: {name} ({user_id})")
        logger.info(f"      Enabled: {'✅ YES' if enabled else '❌ NO'}")
        
        if not enabled:
            logger.info("      ⏭️  Skipping (disabled in config)")
            logger.info("")
            continue
        
        # Determine environment variable names
        if '_' in user_id:
            user_env_name = user_id.split('_')[0].upper()
        else:
            user_env_name = user_id.upper()
        
        key_var = f"KRAKEN_USER_{user_env_name}_API_KEY"
        secret_var = f"KRAKEN_USER_{user_env_name}_API_SECRET"
        
        key_valid, key_msg = check_credential(key_var, name)
        secret_valid, secret_msg = check_credential(secret_var, name)
        
        logger.info(f"      {key_var}: {key_msg}")
        logger.info(f"      {secret_var}: {secret_msg}")
        
        if key_valid and secret_valid:
            valid_users.append({
                'user_id': user_id,
                'name': name,
                'key_var': key_var,
                'secret_var': secret_var
            })
            logger.info(f"      ✅ Credentials OK - {name} WILL trade")
        else:
            logger.info(f"      ❌ MISSING CREDENTIALS - {name} will NOT trade")
        
        logger.info("")
    
    return valid_users


def test_kraken_connection(api_key: str, api_secret: str, account_name: str) -> Tuple[bool, Optional[float], Optional[str]]:
    """
    Test connection to Kraken API and get account balance.
    
    Returns:
        Tuple of (success, balance_usd, error_message)
    """
    try:
        import krakenex
        from pykrakenapi import KrakenAPI
    except ImportError as e:
        return False, None, f"Kraken libraries not installed: {e}"
    
    try:
        # Create API client
        api = krakenex.API()
        api.key = api_key
        api.secret = api_secret
        k = KrakenAPI(api)
        
        # Test connection with balance query
        balance = api.query_private('Balance')
        
        if 'error' in balance and balance['error']:
            error_msg = ', '.join(balance['error'])
            return False, None, error_msg
        
        # Calculate USD balance
        balances = balance.get('result', {})
        usd_balance = float(balances.get('ZUSD', 0))
        usdt_balance = float(balances.get('USDT', 0))
        total_usd = usd_balance + usdt_balance
        
        return True, total_usd, None
        
    except Exception as e:
        return False, None, str(e)


def test_connections(master_ok: bool, valid_users: List[Dict]):
    """Test API connections for all configured accounts."""
    print_subheader("3️⃣  API CONNECTION TESTS")
    
    if not master_ok and not valid_users:
        logger.info("   ⏭️  No credentials configured - skipping connection tests")
        logger.info("")
        return
    
    # Test master connection
    if master_ok:
        logger.info("   Testing MASTER account connection...")
        
        api_key = os.getenv("KRAKEN_MASTER_API_KEY", "").strip()
        api_secret = os.getenv("KRAKEN_MASTER_API_SECRET", "").strip()
        
        # Fallback to legacy
        if not api_key:
            api_key = os.getenv("KRAKEN_API_KEY", "").strip()
        if not api_secret:
            api_secret = os.getenv("KRAKEN_API_SECRET", "").strip()
        
        success, balance, error = test_kraken_connection(api_key, api_secret, "MASTER")
        
        if success:
            logger.info(f"   ✅ MASTER connected successfully")
            logger.info(f"      Balance: ${balance:,.2f} USD")
            if balance < 25:
                logger.warning(f"      ⚠️  Low balance - minimum $25 recommended for trading")
        else:
            logger.error(f"   ❌ MASTER connection FAILED: {error}")
        
        logger.info("")
    
    # Test user connections
    for user in valid_users:
        logger.info(f"   Testing {user['name']} connection...")
        
        api_key = os.getenv(user['key_var'], "").strip()
        api_secret = os.getenv(user['secret_var'], "").strip()
        
        success, balance, error = test_kraken_connection(api_key, api_secret, user['name'])
        
        if success:
            logger.info(f"   ✅ {user['name']} connected successfully")
            logger.info(f"      Balance: ${balance:,.2f} USD")
            if balance < 25:
                logger.warning(f"      ⚠️  Low balance - minimum $25 recommended for trading")
        else:
            logger.error(f"   ❌ {user['name']} connection FAILED: {error}")
        
        logger.info("")


def check_copy_trading_system():
    """Check if copy trading system is properly initialized."""
    print_subheader("4️⃣  COPY TRADING SYSTEM")
    
    try:
        # Try to import copy trading module
        from bot.kraken_copy_trading import (
            initialize_copy_trading_system,
            KRAKEN_MASTER,
            KRAKEN_USERS
        )
        
        logger.info("   ✅ Copy trading module available")
        logger.info("")
        logger.info("   Testing initialization...")
        
        # Try to initialize (this won't work without credentials)
        success = initialize_copy_trading_system()
        
        if success:
            logger.info("   ✅ Copy trading system initialized successfully")
            logger.info(f"      Master: {'Connected' if KRAKEN_MASTER else 'Not connected'}")
            logger.info(f"      Users: {len(KRAKEN_USERS)} configured")
        else:
            logger.error("   ❌ Copy trading initialization FAILED")
            logger.error("      This is expected if credentials are not configured")
        
    except ImportError as e:
        logger.error(f"   ❌ Copy trading module not available: {e}")
    except Exception as e:
        logger.error(f"   ❌ Error checking copy trading: {e}")
    
    logger.info("")


def print_summary(master_ok: bool, valid_users: List[Dict]):
    """Print diagnostic summary and recommendations."""
    logger.info("")
    logger.info(SEPARATOR_FULL)
    logger.info("📊 DIAGNOSTIC SUMMARY")
    logger.info(SEPARATOR_FULL)
    logger.info("")
    
    # Status
    if master_ok and len(valid_users) > 0:
        logger.info("✅ STATUS: Credentials configured for master and users")
        logger.info("   → Kraken trading SHOULD be active")
        logger.info("")
        logger.info("🔍 If trades are still not executing:")
        logger.info("   1. Check API connection tests above for errors")
        logger.info("   2. Verify API key permissions on Kraken")
        logger.info("   3. Check bot logs for trading activity")
        logger.info("   4. Ensure bot is running (not stopped)")
    elif master_ok:
        logger.info("⚠️  STATUS: Master configured but NO users")
        logger.info("   → Only MASTER will trade on Kraken")
        logger.info("   → Users will NOT receive copy trades")
        logger.info("")
        logger.info("🔧 To enable user trading:")
        logger.info("   1. Get Kraken API keys for each user")
        logger.info("   2. Set environment variables (see below)")
        logger.info("   3. Restart the bot")
    elif len(valid_users) > 0:
        logger.error("❌ STATUS: Users configured but NO master")
        logger.error("   → Users CANNOT trade without master")
        logger.error("   → Master executes trades, users copy them")
        logger.error("")
        logger.error("🔧 CRITICAL FIX REQUIRED:")
        logger.error("   1. Get Kraken API key for MASTER account")
        logger.error("   2. Set KRAKEN_MASTER_API_KEY and KRAKEN_MASTER_API_SECRET")
        logger.error("   3. Restart the bot")
    else:
        logger.error("❌ STATUS: NO CREDENTIALS CONFIGURED")
        logger.error("   → Kraken trading is COMPLETELY DISABLED")
        logger.error("   → Neither master nor users can trade")
        logger.error("")
        logger.error("🔧 REQUIRED ACTIONS:")
        logger.error("")
        logger.error("   Step 1: Get API Keys from Kraken")
        logger.error("   ──────────────────────────────────")
        logger.error("   Visit: https://www.kraken.com/u/security/api")
        logger.error("")
        logger.error("   Create API keys with these permissions:")
        logger.error("      ✅ Query Funds")
        logger.error("      ✅ Query Open Orders & Trades")
        logger.error("      ✅ Query Closed Orders & Trades")
        logger.error("      ✅ Create & Modify Orders")
        logger.error("      ✅ Cancel/Close Orders")
        logger.error("      ❌ Do NOT enable 'Withdraw Funds'")
        logger.error("")
        logger.error("   You need API keys for:")
        logger.error("      • MASTER account (system trading account)")
        logger.error("      • Daivon Frazier account")
        logger.error("      • Tania Gilbert account")
        logger.error("")
        logger.error("   Step 2: Set Environment Variables")
        logger.error("   ──────────────────────────────────")
        logger.error("   In your deployment platform (Railway/Render):")
        logger.error("")
        logger.error("   KRAKEN_MASTER_API_KEY=your_master_api_key_here")
        logger.error("   KRAKEN_MASTER_API_SECRET=your_master_api_secret_here")
        logger.error("   KRAKEN_USER_DAIVON_API_KEY=daivon_api_key_here")
        logger.error("   KRAKEN_USER_DAIVON_API_SECRET=daivon_api_secret_here")
        logger.error("   KRAKEN_USER_TANIA_API_KEY=tania_api_key_here")
        logger.error("   KRAKEN_USER_TANIA_API_SECRET=tania_api_secret_here")
        logger.error("")
        logger.error("   Step 3: Restart the Bot")
        logger.error("   ──────────────────────────────────")
        logger.error("   After setting credentials, restart your deployment")
        logger.error("")
    
    logger.info(SEPARATOR_FULL)
    logger.info("")


def main():
    """Run comprehensive Kraken trading diagnostic."""
    print_header("NIJA KRAKEN TRADING DIAGNOSTIC")
    
    logger.info("This diagnostic will check:")
    logger.info("  1. API credential configuration")
    logger.info("  2. Kraken API connectivity")
    logger.info("  3. Account balances")
    logger.info("  4. Copy trading system status")
    logger.info("")
    
    # Check credentials
    master_ok = check_master_credentials()
    valid_users = check_user_credentials()
    
    # Test connections (if credentials exist)
    test_connections(master_ok, valid_users)
    
    # Check copy trading system
    check_copy_trading_system()
    
    # Print summary
    print_summary(master_ok, valid_users)
    
    logger.info("✅ Diagnostic complete!")
    logger.info("")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        logger.info("\n\n⚠️  Diagnostic interrupted by user")
        sys.exit(0)
    except Exception as e:
        logger.error(f"\n\n❌ Diagnostic failed with error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
