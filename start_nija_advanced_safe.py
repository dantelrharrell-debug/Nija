#!/usr/bin/env python3
"""
start_nija_advanced_safe.py
Safe, resilient starter script for Coinbase Advanced (v3) + fallback.
Paste into /app/start_nija_advanced_safe.py and run with:
    python3 /app/start_nija_advanced_safe.py
"""

import os
import time
import json
import logging

# Try to import your existing Advanced client (preferred).
# If it isn't available, the script will log and exit cleanly.
try:
    from nija_client import CoinbaseClient
    HAVE_NIJA_CLIENT = True
except Exception:
    CoinbaseClient = None
    HAVE_NIJA_CLIENT = False

# ---------- logging ----------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)
logger = logging.getLogger("nija.advanced.safe")

# ---------- Environment / config ----------
COINBASE_ISS = os.getenv("COINBASE_ISS")  # e.g. organizations/.../apiKeys/...
COINBASE_PEM_CONTENT = os.getenv("COINBASE_PEM_CONTENT")
COINBASE_PEM_PATH = os.getenv("COINBASE_PRIVATE_KEY_PATH", "/app/coinbase_advanced.pem")
COINBASE_ORG_ID = os.getenv("COINBASE_ORG_ID")
COINBASE_API_KEY = os.getenv("COINBASE_API_KEY")
COINBASE_API_SECRET = os.getenv("COINBASE_API_SECRET")
COINBASE_BASE = os.getenv("COINBASE_BASE", "https://api.cdp.coinbase.com")  # Advanced default

POLL_INTERVAL = int(os.getenv("POLL_INTERVAL", "30"))
RETRY_INTERVAL = int(os.getenv("RETRY_INTERVAL", "10"))

# ---------- write PEM file if content provided ----------
def ensure_pem_file():
    if COINBASE_PEM_CONTENT:
        try:
            # ensure directory exists
            pem_dir = os.path.dirname(COINBASE_PEM_PATH) or "/app"
            os.makedirs(pem_dir, exist_ok=True)
            with open(COINBASE_PEM_PATH, "w") as f:
                f.write(COINBASE_PEM_CONTENT)
            # tighten file permissions (best-effort)
            try:
                os.chmod(COINBASE_PEM_PATH, 0o600)
            except Exception:
                pass
            logger.info(f"PEM file written to {COINBASE_PEM_PATH}")
            return True
        except Exception as e:
            logger.exception(f"Failed to write PEM file: {e}")
            return False
    else:
        if os.path.exists(COINBASE_PEM_PATH):
            logger.info(f"Using existing PEM file at {COINBASE_PEM_PATH}")
            return True
        logger.warning("No COINBASE_PEM_CONTENT and no existing PEM file found.")
        return False

# ---------- initialize Coinbase Advanced client ----------
def make_client():
    if not HAVE_NIJA_CLIENT:
        logger.error("nija_client.CoinbaseClient not importable. Ensure nija_client.py is in PYTHONPATH.")
        return None

    try:
        # Adjust the CoinbaseClient constructor parameters for your codebase.
        # This tries to create the client in 'advanced' mode (JWT via PEM + org_id).
        client = CoinbaseClient(
            api_key=COINBASE_API_KEY,
            api_secret=COINBASE_API_SECRET,
            private_key_path=COINBASE_PEM_PATH,
            org_id=COINBASE_ORG_ID,
            base=COINBASE_BASE,
            advanced=True
        )
        logger.info("Coinbase Advanced client created (advanced=True).")
        return client
    except Exception as e:
        logger.exception(f"Failed to create CoinbaseClient: {e}")
        return None

# ---------- fetch accounts (strict v3, safe handling) ----------
def fetch_advanced_accounts(client):
    """
    Use v3 accounts endpoint only for Advanced API. Return list of accounts or [].
    This will log errors and never raise.
    """
    if client is None:
        logger.error("Client is None — cannot fetch accounts.")
        return []

    path = "/v3/accounts"
    try:
        # We expect client.request(method, path) to return (status_code, data)
        status, data = client.request(method="GET", path=path)
    except Exception as e:
        logger.exception(f"Exception while requesting {path}: {e}")
        return []

    if status == 200 and data:
        # data is expected in the shape { "data": [...] }
        try:
            accounts = data.get("data", []) if isinstance(data, dict) else []
            logger.info(f"✅ Fetched {len(accounts)} accounts via {path}")
            return accounts
        except Exception:
            logger.warning(f"Unexpected accounts payload shape: {type(data)}")
            return []
    elif status == 401:
        logger.error(f"❌ Unauthorized (401) when calling {path}. Check API key/PEM/org permissions.")
    elif status == 404:
        logger.error(f"❌ {path} not found (404) on base {COINBASE_BASE}. Confirm COINBASE_BASE is https://api.cdp.coinbase.com")
    else:
        logger.warning(f"⚠️ {path} returned status {status}. Body: {data}")
    return []

# ---------- main loop ----------
def main_loop():
    logger.info("Starting start_nija_advanced_safe.py")
    pem_ok = ensure_pem_file()
    if not pem_ok:
        logger.warning("PEM file not available. The client may fail to generate JWTs.")

    client = make_client()
    if client is None:
        logger.error("Could not initialize Coinbase client. Exiting (no crash).")
        return

    while True:
        accounts = fetch_advanced_accounts(client)
        if not accounts:
            logger.warning("No accounts found. Will retry after RETRY_INTERVAL.")
            time.sleep(RETRY_INTERVAL)
            continue

        # Example: log account balances; replace with your trading logic
        for a in accounts:
            acct_id = a.get("id") or a.get("account_id") or "n/a"
            bal = a.get("balance", {}) or {}
            amount = bal.get("amount", "N/A")
            currency = bal.get("currency", a.get("currency", "N/A"))
            logger.info(f"Account {acct_id} — {amount} {currency}")

        # Sleep before next poll
        time.sleep(POLL_INTERVAL)

if __name__ == "__main__":
    try:
        main_loop()
    except KeyboardInterrupt:
        logger.info("Stopped by user (KeyboardInterrupt).")
    except Exception as e:
        # Safety net: never crash hard — log and exit cleanly
        logger.exception(f"Unhandled exception in main: {e}")
        logger.info("Exiting safely.")
