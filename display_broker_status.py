#!/usr/bin/env python3
"""
NIJA Broker Status Display
===========================

Displays the configuration status of all supported brokers and accounts
in a clean, easy-to-read format.

Usage:
    python3 check_broker_status.py
"""

import os
import sys

# Try to load dotenv if available
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass


def check_credentials(api_key_var, api_secret_var, passphrase_var=None):
    """
    Check if broker credentials are configured.
    
    Args:
        api_key_var: Environment variable name for API key
        api_secret_var: Environment variable name for API secret
        passphrase_var: Optional environment variable name for passphrase
        
    Returns:
        Tuple of (is_configured, key_length, secret_length, passphrase_length)
    """
    api_key = os.getenv(api_key_var, "").strip()
    api_secret = os.getenv(api_secret_var, "").strip()
    
    if passphrase_var:
        passphrase = os.getenv(passphrase_var, "").strip()
        is_configured = bool(api_key and api_secret and passphrase)
        return is_configured, len(api_key), len(api_secret), len(passphrase)
    else:
        is_configured = bool(api_key and api_secret)
        return is_configured, len(api_key), len(api_secret), 0


def check_coinbase_rest_client():
    """Check if Coinbase REST client SDK is available"""
    try:
        from coinbase.rest import RESTClient
        return True
    except ImportError:
        return False


def print_broker_status():
    """Print comprehensive broker status"""
    print()
    print("=" * 80)
    print("  NIJA BROKER STATUS")
    print("=" * 80)
    print()
    
    # Coinbase
    print("   Coinbase:")
    coinbase_sdk_available = check_coinbase_rest_client()
    if coinbase_sdk_available:
        print("      ✅ Coinbase REST client available")
    else:
        print("      ❌ Coinbase REST client NOT installed")
    
    coinbase_configured, cb_key_len, cb_secret_len, _ = check_credentials(
        "COINBASE_API_KEY", "COINBASE_API_SECRET"
    )
    if coinbase_configured:
        print(f"      ✅ Configured (Key: {cb_key_len} chars, Secret: {cb_secret_len} chars)")
    else:
        print("      ❌ Not configured")
    
    # Kraken Master
    print("   📊 KRAKEN (Master):")
    kraken_master_configured, kr_key_len, kr_secret_len, _ = check_credentials(
        "KRAKEN_MASTER_API_KEY", "KRAKEN_MASTER_API_SECRET"
    )
    if kraken_master_configured:
        print(f"      ✅ Configured (Key: {kr_key_len} chars, Secret: {kr_secret_len} chars)")
    else:
        print("      ❌ Not configured")
    
    # Kraken User #1: Daivon
    print("   👤 KRAKEN (User #1: Daivon):")
    daivon_configured, daivon_key_len, daivon_secret_len, _ = check_credentials(
        "KRAKEN_USER_DAIVON_API_KEY", "KRAKEN_USER_DAIVON_API_SECRET"
    )
    if daivon_configured:
        print(f"      ✅ Configured (Key: {daivon_key_len} chars, Secret: {daivon_secret_len} chars)")
    else:
        print("      ❌ Not configured")
    
    # Kraken User #2: Tania
    print("   👤 KRAKEN (User #2: Tania):")
    tania_kraken_configured, tania_kr_key_len, tania_kr_secret_len, _ = check_credentials(
        "KRAKEN_USER_TANIA_API_KEY", "KRAKEN_USER_TANIA_API_SECRET"
    )
    if tania_kraken_configured:
        print(f"      ✅ Configured (Key: {tania_kr_key_len} chars, Secret: {tania_kr_secret_len} chars)")
    else:
        print("      ❌ Not configured")
    
    # Alpaca Master
    print("   📊 ALPACA (Master):")
    alpaca_configured, alp_key_len, alp_secret_len, _ = check_credentials(
        "ALPACA_API_KEY", "ALPACA_API_SECRET"
    )
    if alpaca_configured:
        paper_mode = os.getenv("ALPACA_PAPER", "true")
        print(f"      ✅ Configured (Key: {alp_key_len} chars, Secret: {alp_secret_len} chars, Paper: {paper_mode})")
    else:
        print("      ❌ Not configured")
    
    # Alpaca User #2: Tania
    print("   👤 ALPACA (User #2: Tania):")
    tania_alpaca_configured, tania_alp_key_len, tania_alp_secret_len, _ = check_credentials(
        "ALPACA_USER_TANIA_API_KEY", "ALPACA_USER_TANIA_API_SECRET"
    )
    if tania_alpaca_configured:
        tania_paper_mode = os.getenv("ALPACA_USER_TANIA_PAPER", "true")
        print(f"      ✅ Configured (Key: {tania_alp_key_len} chars, Secret: {tania_alp_secret_len} chars, Paper: {tania_paper_mode})")
    else:
        print("      ❌ Not configured")
    
    # OKX Master
    print("   📊 OKX (Master):")
    okx_configured, okx_key_len, okx_secret_len, okx_pass_len = check_credentials(
        "OKX_API_KEY", "OKX_API_SECRET", "OKX_PASSPHRASE"
    )
    if okx_configured:
        print(f"      ✅ Configured (Key: {okx_key_len} chars, Secret: {okx_secret_len} chars, Passphrase: {okx_pass_len} chars)")
    else:
        print("      ❌ Not configured")
    
    # Binance Master
    print("   📊 BINANCE (Master):")
    binance_configured, bn_key_len, bn_secret_len, _ = check_credentials(
        "BINANCE_API_KEY", "BINANCE_API_SECRET"
    )
    if binance_configured:
        print(f"      ✅ Configured (Key: {bn_key_len} chars, Secret: {bn_secret_len} chars)")
    else:
        print("      ❌ Not configured")
    
    print()
    print("=" * 80)
    print()
    
    # Summary
    configured_count = sum([
        coinbase_configured,
        kraken_master_configured,
        daivon_configured,
        tania_kraken_configured,
        alpaca_configured,
        tania_alpaca_configured,
        okx_configured,
        binance_configured
    ])
    
    master_count = sum([
        coinbase_configured,
        kraken_master_configured,
        alpaca_configured,
        okx_configured,
        binance_configured
    ])
    
    user_count = sum([
        daivon_configured,
        tania_kraken_configured,
        tania_alpaca_configured
    ])
    
    print(f"Summary:")
    print(f"  • Master accounts configured: {master_count}/5")
    print(f"  • User accounts configured: {user_count}/3")
    print(f"  • Total accounts configured: {configured_count}/8")
    print()
    
    if configured_count == 0:
        print("❌ No accounts configured - trading cannot begin")
        print()
        print("Next steps:")
        print("  1. Set environment variables for at least one exchange")
        print("  2. See .env.example for credential format")
        print("  3. Run this script again to verify")
        print()
        return 1
    elif master_count == 0:
        print("⚠️  No master accounts configured - only user trading available")
        print()
        return 0
    else:
        print("✅ Ready to trade!")
        print()
        if master_count > 0:
            print(f"  Master account will trade on {master_count} exchange(s)")
        if user_count > 0:
            print(f"  {user_count} user account(s) will trade independently")
        print()
        return 0


def main():
    """Main entry point"""
    return print_broker_status()


if __name__ == "__main__":
    sys.exit(main())
