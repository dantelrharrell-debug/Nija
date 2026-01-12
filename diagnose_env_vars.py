#!/usr/bin/env python3
"""
Comprehensive Environment Variables Diagnostic Tool

This script diagnoses issues with exchange API credentials (Kraken, Alpaca, OKX, Binance)
by checking:
1. Whether environment variables are set
2. Whether they have valid (non-empty) values
3. Whether they contain leading/trailing whitespace
4. Which exchanges are properly configured
5. Account-by-account status for multi-user setup

Usage:
    python3 diagnose_env_vars.py
    ./diagnose_env_vars.py
"""

import os
import sys

# Try to load from .env file if dotenv is available
try:
    from dotenv import load_dotenv
    load_dotenv()
    print("✅ Loaded environment variables from .env file (if present)")
except ImportError:
    print("⚠️  python-dotenv not installed - using system environment only")
except Exception as e:
    print(f"⚠️  Could not load .env file: {e}")

print("\n" + "=" * 100)
print(" " * 30 + "ENVIRONMENT VARIABLES DIAGNOSTIC")
print("=" * 100)


def check_var(var_name, account_name):
    """
    Check if an environment variable is properly set.
    Returns: (is_set, value_info, issue_description)
    """
    # Get raw value without stripping
    raw_value = os.getenv(var_name, None)
    
    if raw_value is None:
        return False, "NOT SET", "Variable does not exist in environment"
    
    if raw_value == "":
        return False, "EMPTY STRING", "Variable exists but has empty value"
    
    # Check for whitespace issues
    stripped_value = raw_value.strip()
    
    if len(raw_value) != len(stripped_value):
        # Has leading or trailing whitespace
        leading = len(raw_value) - len(raw_value.lstrip())
        trailing = len(raw_value) - len(raw_value.rstrip())
        return False, f"HAS WHITESPACE (leading: {leading}, trailing: {trailing})", \
               f"Value has whitespace that will be stripped: '{raw_value}'"
    
    if not stripped_value:
        return False, "WHITESPACE ONLY", "Variable contains only whitespace characters"
    
    # Mask the value for display (show first 4 and last 4 chars)
    if len(stripped_value) > 12:
        masked = f"{stripped_value[:4]}...{stripped_value[-4:]} ({len(stripped_value)} chars)"
    elif len(stripped_value) > 8:
        masked = f"{stripped_value[:4]}...{stripped_value[-2:]} ({len(stripped_value)} chars)"
    else:
        masked = f"*** ({len(stripped_value)} chars)"
    
    return True, masked, "OK"


def print_exchange_section(exchange_name, var_configs):
    """
    Print a section for one exchange showing all accounts
    var_configs is a list of (var_name, account_label) tuples
    """
    print("\n" + "-" * 100)
    print(f"  {exchange_name.upper()}")
    print("-" * 100)
    
    all_configured = True
    results = []
    
    for var_name, account_label in var_configs:
        is_set, value_info, issue = check_var(var_name, account_label)
        results.append((var_name, account_label, is_set, value_info, issue))
        
        if not is_set:
            all_configured = False
    
    # Print results
    for var_name, account_label, is_set, value_info, issue in results:
        icon = "✅" if is_set else "❌"
        status = "SET" if is_set else "NOT SET"
        print(f"  {icon} {var_name:<40} {status:<12} {value_info}")
        if not is_set and issue != "Variable does not exist in environment":
            print(f"     Issue: {issue}")
    
    # Summary for this exchange
    configured_count = sum(1 for r in results if r[2])
    total_count = len(results)
    
    print()
    if all_configured:
        print(f"  ✅ {exchange_name}: FULLY CONFIGURED ({configured_count}/{total_count} credentials)")
    elif configured_count > 0:
        print(f"  ⚠️  {exchange_name}: PARTIALLY CONFIGURED ({configured_count}/{total_count} credentials)")
    else:
        print(f"  ❌ {exchange_name}: NOT CONFIGURED (0/{total_count} credentials)")
    
    return all_configured, configured_count, total_count


# KRAKEN
kraken_vars = [
    ("KRAKEN_MASTER_API_KEY", "Master Account"),
    ("KRAKEN_MASTER_API_SECRET", "Master Account"),
    ("KRAKEN_USER_DAIVON_API_KEY", "User #1: Daivon Frazier"),
    ("KRAKEN_USER_DAIVON_API_SECRET", "User #1: Daivon Frazier"),
    ("KRAKEN_USER_TANIA_API_KEY", "User #2: Tania Gilbert"),
    ("KRAKEN_USER_TANIA_API_SECRET", "User #2: Tania Gilbert"),
]

kraken_ok, kraken_count, kraken_total = print_exchange_section("Kraken", kraken_vars)

# ALPACA
alpaca_vars = [
    ("ALPACA_API_KEY", "Master Account"),
    ("ALPACA_API_SECRET", "Master Account"),
    ("ALPACA_PAPER", "Master Account (trading mode)"),
    ("ALPACA_USER_TANIA_API_KEY", "User #2: Tania Gilbert"),
    ("ALPACA_USER_TANIA_API_SECRET", "User #2: Tania Gilbert"),
    ("ALPACA_USER_TANIA_PAPER", "User #2: Tania Gilbert (trading mode)"),
]

alpaca_ok, alpaca_count, alpaca_total = print_exchange_section("Alpaca", alpaca_vars)

# OKX
okx_vars = [
    ("OKX_API_KEY", "Master Account"),
    ("OKX_API_SECRET", "Master Account"),
    ("OKX_PASSPHRASE", "Master Account"),
    ("OKX_USE_TESTNET", "Master Account (mode)"),
]

okx_ok, okx_count, okx_total = print_exchange_section("OKX", okx_vars)

# BINANCE
binance_vars = [
    ("BINANCE_API_KEY", "Master Account"),
    ("BINANCE_API_SECRET", "Master Account"),
    ("BINANCE_USE_TESTNET", "Master Account (mode)"),
]

binance_ok, binance_count, binance_total = print_exchange_section("Binance", binance_vars)

# COINBASE
coinbase_vars = [
    ("COINBASE_API_KEY", "Master Account"),
    ("COINBASE_API_SECRET", "Master Account"),
]

coinbase_ok, coinbase_count, coinbase_total = print_exchange_section("Coinbase", coinbase_vars)

# OVERALL SUMMARY
print("\n" + "=" * 100)
print(" " * 35 + "OVERALL SUMMARY")
print("=" * 100)

exchanges_status = [
    ("Kraken", kraken_ok, kraken_count, kraken_total),
    ("Alpaca", alpaca_ok, alpaca_count, alpaca_total),
    ("OKX", okx_ok, okx_count, okx_total),
    ("Binance", binance_ok, binance_count, binance_total),
    ("Coinbase", coinbase_ok, coinbase_count, coinbase_total),
]

print()
for exchange, is_ok, count, total in exchanges_status:
    icon = "✅" if is_ok else ("⚠️" if count > 0 else "❌")
    if is_ok:
        status = "READY TO TRADE"
    elif count > 0:
        status = f"PARTIAL ({count}/{total})"
    else:
        status = "NOT CONFIGURED"
    print(f"  {icon} {exchange:<15} {status}")

# Account-by-account summary
print("\n" + "=" * 100)
print(" " * 30 + "ACCOUNT-BY-ACCOUNT STATUS")
print("=" * 100)

print("\n🏢 MASTER ACCOUNT:")
master_exchanges = []
if coinbase_ok:
    master_exchanges.append("Coinbase")
if all(check_var(v[0], "")[0] for v in [("KRAKEN_MASTER_API_KEY", ""), ("KRAKEN_MASTER_API_SECRET", "")]):
    master_exchanges.append("Kraken")
if all(check_var(v[0], "")[0] for v in [("ALPACA_API_KEY", ""), ("ALPACA_API_SECRET", "")]):
    master_exchanges.append("Alpaca")
if all(check_var(v[0], "")[0] for v in [("OKX_API_KEY", ""), ("OKX_API_SECRET", ""), ("OKX_PASSPHRASE", "")]):
    master_exchanges.append("OKX")
if all(check_var(v[0], "")[0] for v in [("BINANCE_API_KEY", ""), ("BINANCE_API_SECRET", "")]):
    master_exchanges.append("Binance")

if master_exchanges:
    print(f"  ✅ Connected to: {', '.join(master_exchanges)}")
else:
    print(f"  ❌ No exchanges configured")

print("\n👤 USER #1: Daivon Frazier")
user1_exchanges = []
if all(check_var(v[0], "")[0] for v in [("KRAKEN_USER_DAIVON_API_KEY", ""), ("KRAKEN_USER_DAIVON_API_SECRET", "")]):
    user1_exchanges.append("Kraken")
if user1_exchanges:
    print(f"  ✅ Connected to: {', '.join(user1_exchanges)}")
else:
    print(f"  ❌ No exchanges configured")

print("\n👤 USER #2: Tania Gilbert")
user2_exchanges = []
if all(check_var(v[0], "")[0] for v in [("KRAKEN_USER_TANIA_API_KEY", ""), ("KRAKEN_USER_TANIA_API_SECRET", "")]):
    user2_exchanges.append("Kraken")
if all(check_var(v[0], "")[0] for v in [("ALPACA_USER_TANIA_API_KEY", ""), ("ALPACA_USER_TANIA_API_SECRET", "")]):
    user2_exchanges.append("Alpaca")
if user2_exchanges:
    print(f"  ✅ Connected to: {', '.join(user2_exchanges)}")
else:
    print(f"  ❌ No exchanges configured")

# RECOMMENDATIONS
print("\n" + "=" * 100)
print(" " * 35 + "RECOMMENDATIONS")
print("=" * 100)
print()

total_exchanges = len([e for e in exchanges_status if e[1]])
if total_exchanges == 0:
    print("  ⚠️  NO EXCHANGES CONFIGURED")
    print()
    print("  The bot cannot trade without exchange API credentials.")
    print("  To enable trading, you must configure at least one exchange:")
    print()
    print("  1. Get API credentials from the exchange website")
    print("  2. Set environment variables (see examples below)")
    print("  3. Restart the bot")
    print()
    print("  For Kraken (recommended):")
    print("    export KRAKEN_MASTER_API_KEY='your-api-key'")
    print("    export KRAKEN_MASTER_API_SECRET='your-api-secret'")
    print()
elif total_exchanges < 3:
    print(f"  ℹ️  {total_exchanges} exchange(s) configured")
    print()
    print("  Consider enabling additional exchanges for:")
    print("    • Better diversification")
    print("    • Reduced API rate limiting")
    print("    • More resilient trading")
    print()
else:
    print(f"  ✅ {total_exchanges} exchanges configured - excellent setup!")
    print()

# If Kraken is partially configured
if kraken_count > 0 and not kraken_ok:
    print("  ⚠️  KRAKEN IS PARTIALLY CONFIGURED")
    print()
    print("  Some Kraken credentials are set, but not all accounts are configured.")
    print("  Missing credentials:")
    for var_name, account_label in kraken_vars:
        is_set, _, _ = check_var(var_name, account_label)
        if not is_set:
            print(f"    ❌ {var_name} (for {account_label})")
    print()

# Deployment-specific instructions
print("  📋 DEPLOYMENT INSTRUCTIONS:")
print()
print("  If you're using Railway or Render and have already added environment")
print("  variables, the deployment needs to be RESTARTED to pick up the new values.")
print()
print("  Railway:")
print("    1. Go to https://railway.app → Your Project → Service")
print("    2. Click 'Deploy' → 'Restart Deployment'")
print("    3. Monitor logs for connection confirmations")
print()
print("  Render:")
print("    1. Go to https://render.com → Your Service")
print("    2. Click 'Manual Deploy' → 'Deploy latest commit'")
print("    3. OR: Service auto-redeploys when you save env vars")
print()

print("=" * 100)
print()

# Exit code
if total_exchanges >= 1:
    sys.exit(0)  # At least one exchange is configured
else:
    sys.exit(1)  # No exchanges configured
