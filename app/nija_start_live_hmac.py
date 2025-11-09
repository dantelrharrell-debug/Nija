#!/usr/bin/env python3
# start_nija_live_hmac.py  (paste into repo root)

from loguru import logger
logger.info("STARTUP: Running start_nija_live_hmac.py (robust HMAC entrypoint)")

import os
import sys
import importlib

# Try normal import first, then fallback to loading from /app/nija_hmac_client.py
try:
    from nija_hmac_client import CoinbaseClient
    logger.info("Imported nija_hmac_client via normal import")
except Exception as e_import:
    logger.warning(f"Normal import failed: {e_import!r}. Attempting file-based import fallback...")

    # Insert /app into sys.path in case it's missing
    if "/app" not in sys.path:
        sys.path.insert(0, "/app")

    # Resolve fallback path
    fallback_path = "/app/nija_hmac_client.py"
    if os.path.exists(fallback_path):
        try:
            import importlib.util
            spec = importlib.util.spec_from_file_location("nija_hmac_client", fallback_path)
            nija_hmac_client = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(nija_hmac_client)
            CoinbaseClient = getattr(nija_hmac_client, "CoinbaseClient")
            logger.info(f"Loaded nija_hmac_client from {fallback_path}")
        except Exception as e2:
            logger.exception(f"Failed to load {fallback_path}: {e2}")
            CoinbaseClient = None
    else:
        logger.error(f"Fallback file not found at {fallback_path}. Please ensure nija_hmac_client.py exists in repo root.")
        CoinbaseClient = None

# If still not available, bail with a clear log (no terminal)
if not CoinbaseClient:
    logger.error("CoinbaseClient not available. Check that nija_hmac_client.py exists in the repo root and contains class CoinbaseClient.")
    # stop here — avoid further exceptions
    sys.exit(1)

# Safety: basic env variables check
required_vars = ["COINBASE_API_KEY", "COINBASE_API_SECRET"]
missing = [v for v in required_vars if v not in os.environ]
if missing:
    logger.error(f"Missing environment variables: {missing}. Add them in Railway service settings -> Variables.")
    # continue so you see more diagnostic logs, but real trading will not proceed

# HMAC account fetch (synchronous call using client.request)
def fetch_accounts():
    try:
        client = CoinbaseClient()
        status, accounts = client.request(method="GET", path="/v2/accounts")
        if status != 200:
            logger.error(f"❌ Failed to fetch accounts. Status: {status} | body: {accounts}")
            return []
        logger.info("✅ Accounts fetched:")
        for acct in accounts.get("data", []):
            logger.info(f"{acct.get('name')} ({acct.get('currency')}): {acct.get('balance', {}).get('amount')}")
        return accounts.get("data", [])
    except Exception as exc:
        logger.exception(f"Error fetching accounts: {exc}")
        return []

if __name__ == "__main__":
    fetch_accounts()
