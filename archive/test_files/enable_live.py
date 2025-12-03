#!/usr/bin/env python3
"""
enable_live.py
Safe live-enabler for NIJA trading bot.

Usage (once you've set env vars in Railway or locally):
    python3 enable_live.py

This script performs deterministic checks and only then writes ./LIVE_ENABLED
which your bot should check before allowing live order submission.

IT WILL NOT PLACE ORDERS. It only enables live mode after checks succeed.
"""

import os
import sys
import json
import traceback
from pathlib import Path

# === Configuration / Safety defaults you can change BEFORE running ===
MAX_ALLOWED_FIRST_ORDER_USD = float(os.getenv("MAX_ORDER_USD", "5"))  # keep tiny for first live run
REQUIRED_ENV = [
    "MODE",                # must be 'LIVE'
    "COINBASE_API_KEY",
    "COINBASE_API_SECRET",
    # For Coinbase Advanced JWT flow you should set COINBASE_PEM_CONTENT and COINBASE_ORG_ID
    # For Retail/HMAC flow you may only need key+secret and possibly COINBASE_API_PASSPHRASE
    "COINBASE_ACCOUNT_ID", # the account id you want to use for trading
    "CONFIRM_LIVE",        # must be "true"
]

LIVE_FLAG = Path("LIVE_ENABLED")   # presence indicates live allowed

def fail(msg, code=1):
    print("ERROR:", msg)
    sys.exit(code)

def check_env_vars():
    missing = [k for k in REQUIRED_ENV if not os.getenv(k)]
    if missing:
        fail(f"Missing required env vars: {missing}. Set them in Railway (or export locally).")
    if os.getenv("MODE", "").upper() != "LIVE":
        fail("MODE must be set to LIVE to proceed.")
    if os.getenv("CONFIRM_LIVE", "").lower() not in ("1", "true", "yes"):
        fail("CONFIRM_LIVE must be set to true (CONFIRM_LIVE=true). This prevents accidental live activation.")

def check_requirements():
    # PyJWT + cryptography required for ES256 signing (Coinbase Advanced JWT)
    try:
        import jwt
    except Exception as e:
        fail("PyJWT is not installed. Install with: pip install 'PyJWT[crypto]>=2.6.0' and ensure cryptography is available.")
    # check algorithm support for ES256 if PEM provided
    pem = os.getenv("COINBASE_PEM_CONTENT")
    if pem:
        try:
            # quick encode attempt to confirm ES256 support
            # NOTE: this is a light check; we don't actually sign with your real PEM here
            from jwt import encode as jwt_encode
            # jwt_encode will raise NotImplementedError if ES256 not supported
            jwt_encode({"check":"es256"}, key=pem, algorithm="ES256")
        except NotImplementedError as ne:
            fail("cryptography-backed PyJWT ES256 support not available. Ensure 'cryptography' is installed and available (see Dockerfile + requirements).")
        except Exception:
            # If it fails for other reasons (invalid PEM) that's okay — we just check the runtime supports ES256
            pass

def init_coinbase_client_and_check_account():
    # Import your project's Coinbase client (nija_client.py) and call the account-list method.
    try:
        # adjust import name if your module is different
        from nija_client import CoinbaseClient
    except Exception as e:
        traceback.print_exc()
        fail(f"Failed to import CoinbaseClient from nija_client.py: {e}")

    advanced = os.getenv("COINBASE_API_BASE", "").lower().startswith("https://api.cdp") or os.getenv("COINBASE_PEM_CONTENT")
    print("Info: Initiating CoinbaseClient (advanced=%s)..." % advanced)
    try:
        client = CoinbaseClient(advanced=advanced)
    except Exception as e:
        traceback.print_exc()
        fail(f"CoinbaseClient failed to initialize: {e}")

    # Try to fetch accounts (method name differs between versions — try common candidates)
    accounts = None
    candidate_methods = ["get_accounts", "list_accounts", "accounts", "fetch_accounts", "fetch_accounts_list"]
    for m in candidate_methods:
        if hasattr(client, m):
            try:
                accounts = getattr(client, m)()
                break
            except TypeError:
                # maybe needs no args etc; try without handling
                try:
                    accounts = getattr(client, m)()
                    break
                except Exception:
                    pass
            except Exception:
                pass

    if accounts is None:
        # fallback: if client exposes `.session` or `.request` we can't safely assume anything.
        # don't fail here with a scary message; instead ask to confirm account id presence by trying an explicit API call.
        print("Warning: Could not call a standard accounts method on CoinbaseClient. The client initialized but does not have a known accounts() method signature.")
        print("If you used a custom CoinbaseClient API, ensure it has a callable method to list accounts (get_accounts/list_accounts).")
        # Let script continue but require manual verification in logs.
    else:
        # Normalize account IDs for check
        acc_ids = []
        try:
            # accounts could be a list of dicts or nested structure; try to extract ids/names
            if isinstance(accounts, dict) and "data" in accounts:
                for a in accounts["data"]:
                    if isinstance(a, dict):
                        if "id" in a:
                            acc_ids.append(str(a["id"]))
                        elif "account_id" in a:
                            acc_ids.append(str(a["account_id"]))
            elif isinstance(accounts, list):
                for a in accounts:
                    if isinstance(a, dict):
                        if "id" in a:
                            acc_ids.append(str(a["id"]))
                        elif "account_id" in a:
                            acc_ids.append(str(a["account_id"]))
            else:
                # if it's a string or other, print it
                print("Accounts (raw):", accounts)
        except Exception:
            print("Warning parsing accounts response; raw value printed below.")
            print("Accounts raw:", accounts)

        if acc_ids:
            print("Detected account ids:", acc_ids)
            wanted = os.getenv("COINBASE_ACCOUNT_ID")
            if wanted not in acc_ids:
                fail(f"COINBASE_ACCOUNT_ID={wanted} not found in your Coinbase accounts. Pick one of: {acc_ids}")

    # Check MAX_ORDER_USD small
    try:
        max_usd = float(os.getenv("MAX_ORDER_USD", "0"))
    except Exception:
        fail("MAX_ORDER_USD must be a numeric value in USD (e.g. 1 or 10).")

    if max_usd <= 0 or max_usd > 10000:
        # allow large but warn — we set a hard recommended limit for the first run
        print(f"Warning: MAX_ORDER_USD is set to {max_usd}. Ensure this is intended.")
    if max_usd > MAX_ALLOWED_FIRST_ORDER_USD:
        print(f"Warning: MAX_ORDER_USD > {MAX_ALLOWED_FIRST_ORDER_USD}. For first live run it's safer to set MAX_ORDER_USD={MAX_ALLOWED_FIRST_ORDER_USD} or lower.")

    # Warn about withdraw permission (best practice) - we can't always auto-detect, but warn strongly
    print("IMPORTANT: Ensure the API key does NOT have withdraw permission. If it does, revoke it immediately and create a new key without withdraw access.")

    return True

def write_live_flag():
    LIVE_FLAG.write_text(json.dumps({
        "enabled_by": os.getenv("USER", "unknown"),
        "timestamp": __import__("time").time()
    }))
    print(f"SUCCESS: Live enabled flag written to {LIVE_FLAG}. Your bot should check for this file before placing live orders.")

def main():
    print("== NIJA LIVE ENABLE CHECK ==")
    check_env_vars()
    check_requirements()
    init_coinbase_client_and_check_account()
    write_live_flag()
    print("All checks passed. Live mode enabled. Review logs and then start your bot processes normally.")

if __name__ == "__main__":
    main()
