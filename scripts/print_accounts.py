#!/usr/bin/env python3
"""
Print Coinbase Advanced Trade accounts using JWT authentication.
Reads COINBASE_API_KEY and COINBASE_API_SECRET from environment.
"""
import os
import sys
from coinbase.rest import RESTClient


def get_env(name: str) -> str:
    val = os.environ.get(name)
    if not val:
        print(f"ERROR: Missing environment variable {name}", file=sys.stderr)
        sys.exit(1)
    return val


def load_env_from_file(path: str = ".env") -> None:
    """Load environment variables from .env file."""
    if not os.path.isfile(path):
        return
    
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                key = key.strip()
                value = value.strip().strip('"').strip("'")
                
                if key not in os.environ:
                    os.environ[key] = value
    except Exception as e:
        print(f"Warning: Could not load .env file: {e}", file=sys.stderr)


def main() -> None:
    # Load .env file if present
    load_env_from_file()

    api_key = get_env("COINBASE_API_KEY")
    api_secret = get_env("COINBASE_API_SECRET")
    
    # Normalize PEM key if it has escaped newlines
    if '\\n' in api_secret:
        api_secret = api_secret.replace('\\n', '\n')
        print("🔧 Normalized PEM newlines in API secret")

    print(f"🔐 Coinbase Advanced Trade Authentication")
    print(f"   API Key: {'✅ Set' if api_key else '❌ Missing'}")
    print(f"   API Secret: {'✅ Set ({len(api_secret)} chars)' if api_secret else '❌ Missing'}")
    print()

    try:
        client = RESTClient(api_key=api_key, api_secret=api_secret)
    except Exception as e:
        print(f"ERROR: Failed to create REST client: {e}", file=sys.stderr)
        print(f"API Secret starts with: {api_secret[:50]}...", file=sys.stderr)
        sys.exit(2)
    
    try:
        print("📡 Calling GET /v3/accounts...")
        resp = client.get_accounts()
    except Exception as e:
        print(f"ERROR: get_accounts() failed: {e}", file=sys.stderr)
        sys.exit(2)

    accts = getattr(resp, "accounts", []) or []
    if not accts:
        print("No accounts returned.")
        return

    def bal(cur: str) -> float:
        total = 0.0
        for a in accts:
            if getattr(a, "currency", "") == cur:
                ab = getattr(a, "available_balance", None)
                total += float(getattr(ab, "value", 0) or 0)
        return total

    usd = bal("USD")
    usdc = bal("USDC")
    print(f"\n💰 BALANCES:")
    print(f"USD={usd:.2f} USDC={usdc:.2f} TOTAL={usd+usdc:.2f}")
    print(f"\n📋 ALL ACCOUNTS:")
    for a in accts:
        cur = getattr(a, "currency", "?")
        ab = getattr(a, "available_balance", None)
        val = getattr(ab, "value", 0)
        print(f"{cur}: {val}")


if __name__ == "__main__":
    main()
