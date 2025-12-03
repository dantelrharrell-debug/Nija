# nija_preflight_check.py
import os
from nija_client import CoinbaseClient

def run_preflight():
    """
    Preflight check for Coinbase Advanced API.
    Returns account data if successful, None if failed.
    """
    print("ℹ️ Running Nija preflight check...")

    # Ensure required environment variables are set
    api_key = os.getenv("COINBASE_API_KEY")
    api_secret = os.getenv("COINBASE_API_SECRET")
    if not all([api_key, api_secret]):
        print("❌ Missing COINBASE_API_KEY or COINBASE_API_SECRET. Cannot start bot.")
        return None

    client = CoinbaseClient()

    # Try fetching accounts
    try:
        accounts = client.get_accounts()
        if accounts is None:
            print("❌ Preflight failed: unauthorized or invalid keys.")
            return None
        print(f"✅ Preflight passed: {len(accounts['data'])} accounts found.")
        return accounts
    except Exception as e:
        print(f"❌ Preflight failed with exception: {e}")
        return None
