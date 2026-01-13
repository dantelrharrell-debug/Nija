#!/usr/bin/env python3
"""
Multi-Exchange Trading Status Verifier
=======================================

This script verifies the multi-exchange trading setup status for NIJA.
It checks:
1. Master account (Nija) exchange connections
2. User account exchange connections
3. Configuration completeness
4. Trading readiness

Run this to see what's connected and what needs configuration.
"""

import os
import sys
import json
from pathlib import Path

# Add bot directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'bot'))

# Try to load dotenv if available
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass


def check_env_var(var_name):
    """Check if environment variable is set and not empty"""
    value = os.getenv(var_name, "")
    is_set = bool(value.strip())
    return is_set, len(value) if is_set else 0


def print_header(title):
    """Print a formatted header"""
    print("\n" + "=" * 80)
    print(f"  {title}")
    print("=" * 80)


def print_section(title):
    """Print a formatted section"""
    print(f"\n{title}")
    print("-" * 80)


def main():
    print_header("NIJA MULTI-EXCHANGE TRADING STATUS VERIFIER")
    
    # Check Master Account Credentials
    print_section("🔷 MASTER ACCOUNT (Nija System)")
    
    exchanges_configured = 0
    master_exchanges = []
    
    # Coinbase
    coinbase_key, coinbase_key_len = check_env_var("COINBASE_API_KEY")
    coinbase_secret, coinbase_secret_len = check_env_var("COINBASE_API_SECRET")
    if coinbase_key and coinbase_secret:
        exchanges_configured += 1
        master_exchanges.append("Coinbase")
        print(f"✅ Coinbase: Configured (Key: {coinbase_key_len} chars, Secret: {coinbase_secret_len} chars)")
    else:
        print("❌ Coinbase: NOT configured")
        if coinbase_key and not coinbase_secret:
            print("   → API Key is set, but Secret is missing")
        elif coinbase_secret and not coinbase_key:
            print("   → Secret is set, but API Key is missing")
    
    # Kraken Master
    kraken_key, kraken_key_len = check_env_var("KRAKEN_MASTER_API_KEY")
    kraken_secret, kraken_secret_len = check_env_var("KRAKEN_MASTER_API_SECRET")
    if kraken_key and kraken_secret:
        exchanges_configured += 1
        master_exchanges.append("Kraken")
        print(f"✅ Kraken (Master): Configured (Key: {kraken_key_len} chars, Secret: {kraken_secret_len} chars)")
    else:
        print("❌ Kraken (Master): NOT configured")
    
    # Alpaca Master
    alpaca_key, alpaca_key_len = check_env_var("ALPACA_API_KEY")
    alpaca_secret, alpaca_secret_len = check_env_var("ALPACA_API_SECRET")
    alpaca_paper, _ = check_env_var("ALPACA_PAPER")
    paper_mode = os.getenv("ALPACA_PAPER", "true")
    if alpaca_key and alpaca_secret:
        exchanges_configured += 1
        master_exchanges.append("Alpaca")
        print(f"✅ Alpaca (Master): Configured (Key: {alpaca_key_len} chars, Secret: {alpaca_secret_len} chars, Paper: {paper_mode})")
    else:
        print("❌ Alpaca (Master): NOT configured")
    
    # OKX Master
    okx_key, _ = check_env_var("OKX_API_KEY")
    okx_secret, _ = check_env_var("OKX_API_SECRET")
    okx_pass, _ = check_env_var("OKX_PASSPHRASE")
    if okx_key and okx_secret and okx_pass:
        exchanges_configured += 1
        master_exchanges.append("OKX")
        print("✅ OKX (Master): Configured")
    else:
        print("❌ OKX (Master): NOT configured")
    
    # Binance Master
    binance_key, _ = check_env_var("BINANCE_API_KEY")
    binance_secret, _ = check_env_var("BINANCE_API_SECRET")
    if binance_key and binance_secret:
        exchanges_configured += 1
        master_exchanges.append("Binance")
        print("✅ Binance (Master): Configured")
    else:
        print("❌ Binance (Master): NOT configured")
    
    # Check User Account Credentials
    print_section("👤 USER ACCOUNTS")
    
    user_accounts = []
    
    # User: Daivon (Kraken)
    daivon_kraken_key, _ = check_env_var("KRAKEN_USER_DAIVON_API_KEY")
    daivon_kraken_secret, _ = check_env_var("KRAKEN_USER_DAIVON_API_SECRET")
    if daivon_kraken_key and daivon_kraken_secret:
        user_accounts.append("Daivon Frazier (Kraken)")
        print("✅ Daivon Frazier → Kraken: Configured")
    else:
        print("❌ Daivon Frazier → Kraken: NOT configured")
    
    # User: Tania (Kraken)
    tania_kraken_key, _ = check_env_var("KRAKEN_USER_TANIA_API_KEY")
    tania_kraken_secret, _ = check_env_var("KRAKEN_USER_TANIA_API_SECRET")
    if tania_kraken_key and tania_kraken_secret:
        user_accounts.append("Tania Gilbert (Kraken)")
        print("✅ Tania Gilbert → Kraken: Configured")
    else:
        print("❌ Tania Gilbert → Kraken: NOT configured")
    
    # User: Tania (Alpaca)
    tania_alpaca_key, _ = check_env_var("ALPACA_USER_TANIA_API_KEY")
    tania_alpaca_secret, _ = check_env_var("ALPACA_USER_TANIA_API_SECRET")
    tania_paper, _ = check_env_var("ALPACA_USER_TANIA_PAPER")
    tania_paper_mode = os.getenv("ALPACA_USER_TANIA_PAPER", "true")
    if tania_alpaca_key and tania_alpaca_secret:
        user_accounts.append("Tania Gilbert (Alpaca)")
        print(f"✅ Tania Gilbert → Alpaca: Configured (Paper: {tania_paper_mode})")
    else:
        print("❌ Tania Gilbert → Alpaca: NOT configured")
    
    # Check User Configuration Files
    print_section("📁 USER CONFIGURATION FILES")
    
    config_dir = Path(__file__).parent / "config" / "users"
    if config_dir.exists():
        config_files = list(config_dir.glob("*.json"))
        print(f"Found {len(config_files)} user configuration files:")
        
        for config_file in config_files:
            try:
                with open(config_file, 'r') as f:
                    users = json.load(f)
                    enabled_users = [u for u in users if u.get('enabled', False)]
                    print(f"  ✅ {config_file.name}: {len(enabled_users)} enabled user(s)")
                    for user in enabled_users:
                        user_id = user.get('user_id', 'unknown')
                        broker = user.get('broker_type', 'unknown')
                        print(f"     • {user_id} → {broker}")
            except Exception as e:
                print(f"  ⚠️  {config_file.name}: Error reading file - {e}")
    else:
        print("❌ User configuration directory not found")
    
    # Summary
    print_header("SUMMARY")
    
    print(f"\n📊 Master Account Exchanges: {exchanges_configured}")
    if master_exchanges:
        print(f"   ✅ {', '.join(master_exchanges)}")
    else:
        print("   ❌ No master exchanges configured")
    
    print(f"\n👥 User Accounts: {len(user_accounts)}")
    if user_accounts:
        for user in user_accounts:
            print(f"   ✅ {user}")
    else:
        print("   ❌ No user accounts configured")
    
    # Trading Readiness Assessment
    print_section("🎯 TRADING READINESS ASSESSMENT")
    
    if exchanges_configured == 0 and len(user_accounts) == 0:
        print("❌ CRITICAL: No accounts configured")
        print("\n   The bot cannot trade without credentials.")
        print("\n   Next Steps:")
        print("   1. Copy .env.example to .env")
        print("   2. Fill in your API credentials")
        print("   3. Restart the bot")
        print("\n   See MULTI_EXCHANGE_TRADING_GUIDE.md for instructions")
    
    elif exchanges_configured > 0 and len(user_accounts) == 0:
        print("✅ Master account is ready to trade")
        print("⚠️  No user accounts configured")
        print("\n   The bot will trade on master account only.")
        print("\n   To enable user trading:")
        print("   1. Add user credentials to .env file")
        print("   2. Verify user configs in config/users/")
        print("   3. Restart the bot")
        print("\n   See USER_SETUP_GUIDE.md for instructions")
    
    elif exchanges_configured == 0 and len(user_accounts) > 0:
        print("⚠️  Master account is NOT configured")
        print("✅ User accounts are ready to trade")
        print("\n   Users can trade, but master account cannot.")
        print("\n   To enable master trading:")
        print("   1. Add Coinbase credentials to .env")
        print("   2. Restart the bot")
    
    else:
        print("✅ READY: Both master and user accounts are configured")
        print("\n   The bot will trade on:")
        print(f"   • {exchanges_configured} master exchange(s)")
        print(f"   • {len(user_accounts)} user account(s)")
        print("\n   Each account trades independently in its own thread.")
        print("   Failures in one account won't affect others.")
        print("\n   To start trading:")
        print("   1. Ensure all accounts are funded")
        print("   2. Run: ./start.sh")
        print("   3. Monitor logs for connection status")
    
    # How Trading Works
    print_section("ℹ️  HOW MULTI-EXCHANGE TRADING WORKS")
    
    print("""
1. MASTER ACCOUNT (Nija System):
   • Connects to configured exchanges (Coinbase, Kraken, Alpaca, etc.)
   • Trades using master account credentials
   • Uses APEX v7.1 strategy
   • Independent balance and positions

2. USER ACCOUNTS (Individual Traders):
   • Each user has their own API credentials
   • Loaded from config/users/*.json files
   • Trade independently from master account
   • Each user has separate balance and positions

3. INDEPENDENT TRADING:
   • Each account runs in its own thread
   • Failures in one account don't affect others
   • Staggered startup prevents API rate limits
   • Complete isolation between accounts

4. EXECUTION:
   • Bot connects all configured accounts
   • Starts independent trading threads
   • Each thread executes APEX strategy
   • Runs continuously (2.5 minute cycles)
    """)
    
    print_header("VERIFICATION COMPLETE")
    print("\nFor detailed setup instructions, see:")
    print("  • MULTI_EXCHANGE_TRADING_GUIDE.md")
    print("  • USER_SETUP_GUIDE.md")
    print("  • .env.example (for credential format)")
    print("\nTo start trading: ./start.sh")
    print()


if __name__ == "__main__":
    main()
