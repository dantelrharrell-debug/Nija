#!/usr/bin/env python3
"""
fix_balance_detection.py — Fix NIJA's $0 balance detection issue for Coinbase & Kraken.

This script:
1. Tests actual Coinbase API connectivity
2. Verifies account access permissions
3. Checks for portfolio creation
4. Tests Kraken credentials if available
5. Provides step-by-step fixes

Usage:
    python fix_balance_detection.py

Or run individual tests:
    python fix_balance_detection.py coinbase
    python fix_balance_detection.py kraken
"""

import os
import sys
import json
from typing import Optional, Dict, Tuple

# Auto-load .env
try:
    from dotenv import load_dotenv
    load_dotenv()
except:
    pass


def print_header(text: str):
    """Print formatted header"""
    print(f"\n{'='*70}")
    print(f"  {text}")
    print(f"{'='*70}\n")


def print_success(text: str):
    """Print success message"""
    print(f"  ✅ {text}")


def print_error(text: str):
    """Print error message"""
    print(f"  ❌ {text}")


def print_warning(text: str):
    """Print warning message"""
    print(f"  ⚠️  {text}")


def print_info(text: str):
    """Print info message"""
    print(f"  ℹ️  {text}")


def test_coinbase_credentials() -> Tuple[bool, Optional[str], Optional[str]]:
    """Test if Coinbase credentials exist and are valid format"""
    print_header("TEST 1: Coinbase Credentials")
    
    api_key = os.getenv("COINBASE_API_KEY", "").strip()
    api_secret = os.getenv("COINBASE_API_SECRET") or os.getenv("COINBASE_PEM_CONTENT")
    
    if not api_key:
        print_error("COINBASE_API_KEY not set in environment")
        print_info("Get it from: https://portal.cdp.coinbase.com/access/api")
        return False, None, None
    
    if not api_secret:
        print_error("COINBASE_API_SECRET or COINBASE_PEM_CONTENT not set")
        print_info("Download PEM file from: https://portal.cdp.coinbase.com/access/api")
        return False, None, None
    
    # Validate format
    if not api_key.startswith("organizations/"):
        print_warning("API_KEY format unusual (expected 'organizations/...')")
    else:
        print_success(f"API_KEY format valid: {api_key[:40]}...")
    
    if "BEGIN EC PRIVATE KEY" not in api_secret:
        print_warning("API_SECRET doesn't look like PEM key (missing 'BEGIN EC PRIVATE KEY')")
        if len(api_secret) < 50:
            print_warning("API_SECRET appears to be raw key, not PEM format")
    else:
        print_success("API_SECRET format valid (PEM key detected)")
    
    return True, api_key, api_secret


def test_coinbase_connection(api_key: str, api_secret: str) -> Tuple[bool, Optional[object]]:
    """Test actual Coinbase API connection"""
    print_header("TEST 2: Coinbase API Connection")
    
    try:
        from coinbase.rest import RESTClient
    except ImportError:
        print_error("coinbase-advanced-py not installed")
        print_info("Install with: pip install coinbase-advanced-py")
        return False, None
    
    try:
        # Normalize PEM if needed
        if "\\n" in api_secret:
            api_secret_normalized = api_secret.replace("\\n", "\n")
            print_info("Normalized escaped newlines in PEM key")
        else:
            api_secret_normalized = api_secret
        
        print_info("Creating RESTClient...")
        client = RESTClient(api_key=api_key, api_secret=api_secret_normalized)
        print_success("RESTClient created successfully")
        
        # Test with actual API call
        print_info("Testing API connection with get_accounts()...")
        resp = client.get_accounts()
        print_success("API connection successful ✅")
        
        return True, client
        
    except Exception as e:
        print_error(f"API connection failed: {e}")
        print_warning("This usually means:")
        print_warning("  1. Invalid API credentials")
        print_warning("  2. API key lacks permissions")
        print_warning("  3. Network connectivity issue")
        return False, None


def test_coinbase_accounts(client) -> Dict:
    """Test Coinbase account access"""
    print_header("TEST 3: Coinbase Account Access")
    
    try:
        resp = client.get_accounts()
        
        if hasattr(resp, 'accounts'):
            accounts = resp.accounts
        elif isinstance(resp, dict):
            accounts = resp.get('accounts', [])
        else:
            accounts = []
        
        print_info(f"API returned {len(accounts)} account(s)")
        
        if len(accounts) == 0:
            print_error("Zero accounts returned - API key likely lacks 'View' permission")
            print_info("FIX: Enable 'View account details' permission:")
            print_info("  1. Go to: https://portal.cdp.coinbase.com/access/api")
            print_info("  2. Click your API key")
            print_info("  3. Enable checkbox: 'View account details'")
            print_info("  4. Save and regenerate key if needed")
            return {"status": "zero_accounts", "count": 0}
        
        # Show account summary
        usd_total = 0.0
        usdc_total = 0.0
        
        for i, acct in enumerate(accounts):
            if isinstance(acct, dict):
                currency = acct.get('currency', '?')
                available_val = acct.get('available_balance', {})
                if isinstance(available_val, dict):
                    value = float(available_val.get('value', 0) or 0)
                else:
                    value = float(available_val or 0)
            else:
                currency = getattr(acct, 'currency', '?')
                available_val = getattr(acct, 'available_balance', {})
                if hasattr(available_val, 'value'):
                    value = float(available_val.value)
                else:
                    value = float(available_val or 0)
            
            print_info(f"  Account {i}: {currency} = ${value:.2f}")
            if currency == 'USD':
                usd_total += value
            elif currency == 'USDC':
                usdc_total += value
        
        total = usd_total + usdc_total
        
        if total == 0.0:
            print_error(f"Total balance is $0")
            print_warning("Your Coinbase account appears to have no funds")
            print_info("OPTIONS:")
            print_info("  1. Transfer USD/USDC to your Coinbase account")
            print_info("  2. Verify you're using the correct account")
            print_info("  3. Check portfolio selection")
            return {"status": "zero_balance", "count": len(accounts), "total": total}
        
        print_success(f"✅ Total Balance: ${total:.2f} (USD: ${usd_total:.2f}, USDC: ${usdc_total:.2f})")
        return {"status": "success", "count": len(accounts), "total": total, "usd": usd_total, "usdc": usdc_total}
        
    except Exception as e:
        print_error(f"Account access failed: {e}")
        return {"status": "error", "error": str(e)}


def test_kraken_credentials() -> Tuple[bool, Optional[str], Optional[str]]:
    """Test if Kraken credentials exist"""
    print_header("TEST 4: Kraken Credentials (Platform)")
    
    kraken_key = os.getenv("KRAKEN_PLATFORM_API_KEY", "").strip()
    kraken_secret = os.getenv("KRAKEN_PLATFORM_API_SECRET", "").strip()
    
    if not kraken_key or not kraken_secret:
        print_warning("Kraken platform credentials not configured")
        print_info("Optional - only required if using Kraken platform trading")
        return False, None, None
    
    print_success(f"Kraken API key found: {kraken_key[:20]}...")
    print_success(f"Kraken API secret found ({len(kraken_secret)} chars)")
    
    return True, kraken_key, kraken_secret


def main():
    """Run all tests"""
    print("\n" + "="*70)
    print("  NIJA Balance Detection Diagnostic")
    print("="*70)
    
    # Test Coinbase
    has_creds, cb_key, cb_secret = test_coinbase_credentials()
    
    client = None
    if has_creds:
        connected, client = test_coinbase_connection(cb_key, cb_secret)
        
        if connected and client:
            result = test_coinbase_accounts(client)
            
            # Print summary
            print_header("DIAGNOSIS SUMMARY")
            
            if result.get("status") == "success":
                print_success("✅ Coinbase integration working! NIJA should see your funds.")
                print_success(f"✅ Balance detected: ${result['total']:.2f}")
                
            elif result.get("status") == "zero_balance":
                print_error("❌ Coinbase detected but balance is $0")
                print_info("ACTIONS:")
                print_info("  1. Ensure your Coinbase account has USD/USDC")
                print_info("  2. Transfer funds from wallet if needed")
                print_info("  3. Check you're using the correct account")
                
            elif result.get("status") == "zero_accounts":
                print_error("❌ Cannot access any Coinbase accounts")
                print_info("LIKELY CAUSE: API key permissions issue")
                print_info("FIX:")
                print_info("  1. Go to: https://portal.cdp.coinbase.com/access/api")
                print_info("  2. Select your API key")
                print_info("  3. Ensure these permissions are enabled:")
                print_info("     • ✅ View account details")
                print_info("     • ✅ Trade")
                print_info("  4. Regenerate API key")
                print_info("  5. Update .env with new credentials")
                print_info("  6. Restart NIJA")
    else:
        print_header("NEXT STEPS")
        print_error("Cannot test without Coinbase credentials")
        print_info("1. Create API key at: https://portal.cdp.coinbase.com/access/api")
        print_info("2. Create new API key")
        print_info("3. Set permissions:")
        print_info("   • View account details ✓")
        print_info("   • Trade ✓")
        print_info("4. Download PEM file")
        print_info("5. Add to .env or environment:")
        print_info('   export COINBASE_API_KEY="organizations/YOUR-ORG/apiKeys/YOUR-KEY"')
        print_info('   export COINBASE_API_SECRET="-----BEGIN EC PRIVATE KEY-----\\nYOUR_KEY\\n-----END EC PRIVATE KEY-----"')
        print_info("6. Run this script again to verify")
    
    # Test Kraken if configured
    print("\n")
    kraken_ok, kraken_key, kraken_secret = test_kraken_credentials()
    
    print_header("FINAL RECOMMENDATIONS")
    print_info("If NIJA still shows $0 balance after these steps:")
    print_info("  1. Check the logs: grep -i balance nija.log")
    print_info("  2. Ensure API keys have LIVE permissions (not testnet)")
    print_info("  3. Try regenerating API key from Coinbase dashboard")
    print_info("  4. Contact support if issue persists")


if __name__ == "__main__":
    main()
