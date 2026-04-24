#!/usr/bin/env python3
"""
test_v2_balance.py — Coinbase Advanced Trade API connection & balance test.

Run this script to verify that NIJA can see your Coinbase funds:

    python test_v2_balance.py

Expected output (values will reflect your actual account):
    ✅ Connected!
    💰 BALANCES:
       USD:  $30.31
       USDC: $5.00
       TRADING BALANCE: $35.31
    ✅✅✅ SUCCESS! NIJA CAN SEE YOUR FUNDS!
"""

import os
import sys

# ---------------------------------------------------------------------------
# Auto-load .env so the script works when run directly from the project root
# ---------------------------------------------------------------------------
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # python-dotenv not installed; rely on environment variables already set


def _check_credentials() -> tuple:
    """Return (api_key, api_secret) or print an error and exit."""
    api_key = os.getenv("COINBASE_API_KEY")
    api_secret = os.getenv("COINBASE_API_SECRET") or os.getenv("COINBASE_PEM_CONTENT")

    if not api_key or not api_secret:
        print()
        print("❌ Coinbase credentials not found in environment.")
        print()
        print("   Set the following environment variables and re-run:")
        print()
        print('   export COINBASE_API_KEY="organizations/YOUR-ORG-ID/apiKeys/YOUR-KEY-ID"')
        print('   export COINBASE_API_SECRET="-----BEGIN EC PRIVATE KEY-----\\nYOUR_KEY\\n-----END EC PRIVATE KEY-----\\n"')
        print('   # or:')
        print('   export COINBASE_PEM_CONTENT="-----BEGIN EC PRIVATE KEY-----\\nYOUR_KEY\\n-----END EC PRIVATE KEY-----\\n"')
        print()
        print("   Or create a .env file in the project root with the above values.")
        print("   See .env.example for the full configuration template.")
        print()
        sys.exit(1)

    return api_key, api_secret


def _connect(api_key: str, api_secret: str):
    """Create a RESTClient and verify connectivity by fetching accounts."""
    try:
        from coinbase.rest import RESTClient
    except ImportError:
        print()
        print("❌ Coinbase SDK not installed.")
        print()
        print("   Install it with:")
        print("      pip install coinbase-advanced-py")
        print()
        sys.exit(1)

    print()
    print("🔌 Connecting to Coinbase Advanced Trade API...")

    client = RESTClient(api_key=api_key, api_secret=api_secret)

    # Verify connectivity — this raises on auth failure / network error
    accounts_resp = client.get_accounts()
    return client, accounts_resp


def _get_balances(client, accounts_resp) -> dict:
    """
    Extract USD and USDC trading balances from the accounts response.

    Returns a dict with keys: usd, usdc, trading_balance, crypto
    """
    usd_balance = 0.0
    usdc_balance = 0.0
    crypto_holdings = {}

    # Collect account list from the response (handles both object and dict formats)
    accounts = getattr(accounts_resp, 'accounts', None)
    if accounts is None and isinstance(accounts_resp, dict):
        accounts = accounts_resp.get('accounts', [])
    if accounts is None:
        accounts = []

    for acct in accounts:
        # Support both Coinbase SDK Account objects and plain dicts
        if isinstance(acct, dict):
            currency = acct.get('currency', '')
            available = float(acct.get('available_balance', {}).get('value', 0) or 0)
        else:
            currency = getattr(acct, 'currency', '') or ''
            avail_obj = getattr(acct, 'available_balance', None)
            if avail_obj is not None:
                available = float(getattr(avail_obj, 'value', 0) or 0)
            else:
                available = 0.0

        currency = str(currency).upper()

        if currency == 'USD':
            usd_balance += available
        elif currency == 'USDC':
            usdc_balance += available
        elif available > 0:
            crypto_holdings[currency] = available

    trading_balance = usd_balance + usdc_balance

    return {
        'usd': usd_balance,
        'usdc': usdc_balance,
        'trading_balance': trading_balance,
        'crypto': crypto_holdings,
    }


def main():
    print("=" * 55)
    print("   NIJA — Coinbase Connection & Balance Test")
    print("=" * 55)

    # 1. Credentials
    api_key, api_secret = _check_credentials()

    # 2. Connect
    try:
        client, accounts_resp = _connect(api_key, api_secret)
    except Exception as exc:
        print()
        print(f"❌ Connection failed: {exc}")
        print()
        print("   Common causes:")
        print("   • Invalid API key or secret")
        print("   • API key lacks required permissions (needs 'View' at minimum)")
        print("   • Secret is not in PEM format (must include BEGIN/END headers)")
        print("   • Network connectivity issue")
        print()
        print("   See README.md → '🔐 Coinbase API Setup' for help.")
        print()
        sys.exit(1)

    print("✅ Connected!")

    # 3. Balances
    try:
        balances = _get_balances(client, accounts_resp)
    except Exception as exc:
        print()
        print(f"⚠️  Could not parse balances: {exc}")
        print("   Connection succeeded but balance details are unavailable.")
        print()
        sys.exit(1)

    print()
    print("💰 BALANCES:")
    print(f"   USD:  ${balances['usd']:.2f}")
    print(f"   USDC: ${balances['usdc']:.2f}")
    print(f"   TRADING BALANCE: ${balances['trading_balance']:.2f}")

    if balances['crypto']:
        print()
        print("   Other holdings:")
        for symbol, qty in sorted(balances['crypto'].items()):
            print(f"     {symbol}: {qty:.6f}")

    print()

    if balances['trading_balance'] > 0:
        print("✅✅✅ SUCCESS! NIJA CAN SEE YOUR FUNDS!")
    else:
        print("⚠️  Connected successfully but trading balance is $0.00.")
        print("   If you have funds in a Consumer wallet, transfer them to your")
        print("   Advanced Trade portfolio at https://www.coinbase.com/advanced-trade")

    print()


if __name__ == "__main__":
    main()
