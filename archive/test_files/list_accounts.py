#!/usr/bin/env python3

import os
from nija_client import CoinbaseClient

def main():
    try:
        client = CoinbaseClient()
    except Exception as e:
        print(f"[ERROR] Failed to initialize CoinbaseClient: {e}")
        return

    accounts = client.get_accounts()
    if not accounts:
        print("[INFO] No accounts found or API error")
        return

    print("Coinbase Accounts:")
    for a in accounts:
        name = a.get("name", "<unknown>")
        bal = a.get("balance", {})
        amount = bal.get("amount", "0")
        currency = bal.get("currency", "?")
        print(f" - {name}: {amount} {currency}")

if __name__ == "__main__":
    main()
