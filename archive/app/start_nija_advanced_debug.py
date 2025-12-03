#!/usr/bin/env python3
# /app/start_nija_advanced_debug.py
"""
Debug helper: writes PEM (if provided), then attempts:
  1) client.request(method="GET", path="/v3/accounts")
  2) raw HTTP GET to base and base + /v3/accounts
Logs full status and response body for diagnosis.
"""

import os
import time
import logging
import requests

# Try to import the client's CoinbaseClient (if present)
try:
    from nija_client import CoinbaseClient
    HAVE_CLIENT = True
except Exception as e:
    CoinbaseClient = None
    HAVE_CLIENT = False

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
logger = logging.getLogger("nija.advanced.debug")

# Config from environment
COINBASE_PEM_CONTENT = os.getenv("COINBASE_PEM_CONTENT")
COINBASE_PEM_PATH = os.getenv("COINBASE_PRIVATE_KEY_PATH", "/app/coinbase_advanced.pem")
COINBASE_BASE = os.getenv("COINBASE_BASE", "https://api.cdp.coinbase.com")
COINBASE_API_KEY = os.getenv("COINBASE_API_KEY")
COINBASE_API_SECRET = os.getenv("COINBASE_API_SECRET")
COINBASE_ORG_ID = os.getenv("COINBASE_ORG_ID")
COINBASE_ISS = os.getenv("COINBASE_ISS")

POLL_INTERVAL = int(os.getenv("POLL_INTERVAL", "15"))
RETRY_INTERVAL = int(os.getenv("RETRY_INTERVAL", "10"))

def ensure_pem():
    if COINBASE_PEM_CONTENT:
        try:
            os.makedirs(os.path.dirname(COINBASE_PEM_PATH) or "/app", exist_ok=True)
            with open(COINBASE_PEM_PATH, "w") as f:
                f.write(COINBASE_PEM_CONTENT)
            try:
                os.chmod(COINBASE_PEM_PATH, 0o600)
            except Exception:
                pass
            logger.info(f"PEM written to {COINBASE_PEM_PATH}")
            return True
        except Exception as e:
            logger.exception(f"Failed to write PEM: {e}")
            return False
    else:
        if os.path.exists(COINBASE_PEM_PATH):
            logger.info(f"Using existing PEM file at {COINBASE_PEM_PATH}")
            return True
        logger.warning("No COINBASE_PEM_CONTENT and no PEM file present.")
        return False

def make_client():
    if not HAVE_CLIENT:
        logger.warning("nija_client.CoinbaseClient not importable. Skipping client.request() step.")
        return None
    try:
        client = CoinbaseClient(
            api_key=COINBASE_API_KEY,
            api_secret=COINBASE_API_SECRET,
            private_key_path=COINBASE_PEM_PATH,
            org_id=COINBASE_ORG_ID,
            base=COINBASE_BASE,
            advanced=True
        )
        logger.info("CoinbaseClient created (advanced=True).")
        return client
    except Exception as e:
        logger.exception(f"Failed to create CoinbaseClient: {e}")
        return None

def try_client_accounts(client):
    if client is None:
        logger.info("No client available; skipping client.request() call.")
        return
    logger.info("Calling client.request(method='GET', path='/v3/accounts') ...")
    try:
        # call client.request and capture return
        res = client.request(method="GET", path="/v3/accounts")
        logger.info(f"client.request() returned: {type(res)} -> {res}")
        # if it's tuple-like, break out
        try:
            status, data = res
            logger.info(f"client.request: status={status}")
            logger.info(f"client.request: data type={type(data)}")
            # log small sample of body safely
            if isinstance(data, (dict, list)):
                logger.info(f"client.request: data keys/sample: {list(data)[:5]}")
            else:
                logger.info(f"client.request: data raw: {str(data)[:500]}")
        except Exception as e:
            logger.warning(f"Could not unpack client.request() result: {e}")
            logger.info(f"Full client.request() result: {res}")
    except Exception as e:
        logger.exception(f"Exception calling client.request(): {e}")

def raw_http_checks():
    # Raw base URL GET -- see if the host responds
    try:
        base_url = COINBASE_BASE.rstrip("/")
        logger.info(f"Raw GET to base: {base_url} (no auth)")
        r = requests.get(base_url, timeout=8)
        logger.info(f"BASE GET -> status {r.status_code} | headers: {dict(r.headers)}")
        body = r.text or ""
        logger.info(f"BASE GET -> body (first 1000 chars): {body[:1000]!r}")
    except Exception as e:
        logger.exception(f"Base GET failed: {e}")

    # Raw GET to /v3/accounts (no auth) to see server response
    try:
        url = COINBASE_BASE.rstrip("/") + "/v3/accounts"
        logger.info(f"Raw GET to {url} (no auth)")
        r = requests.get(url, timeout=8)
        logger.info(f"GET {url} -> status {r.status_code}")
        # show a safe slice of body
        text = r.text or ""
        logger.info(f"GET {url} -> body (first 1500 chars): {text[:1500]!r}")
    except Exception as e:
        logger.exception(f"GET /v3/accounts failed: {e}")

def show_env_summary():
    logger.info("ENV SUMMARY:")
    logger.info(f" COINBASE_BASE = {COINBASE_BASE}")
    logger.info(f" COINBASE_ORG_ID = {COINBASE_ORG_ID}")
    logger.info(f" COINBASE_ISS = {COINBASE_ISS}")
    logger.info(f" COINBASE_PRIVATE_KEY_PATH = {COINBASE_PEM_PATH} (exists={os.path.exists(COINBASE_PEM_PATH)})")
    logger.info(f" COINBASE_API_KEY present = {bool(COINBASE_API_KEY)}")
    logger.info(f" COINBASE_API_SECRET present = {bool(COINBASE_API_SECRET)}")
    logger.info(f" nija_client importable = {HAVE_CLIENT}")

def main():
    logger.info("=== start_nija_advanced_debug.py starting ===")
    pem_ok = ensure_pem()
    show_env_summary()
    client = make_client()

    # Try once per loop with verbose logging
    while True:
        try:
            logger.info("=== DEBUG ITERATION START ===")
            # 1) client.request (if client available)
            try_client_accounts(client)

            # 2) raw HTTP checks (no auth) so we can see how base responds
            raw_http_checks()

            logger.info("=== DEBUG ITERATION END ===")
        except Exception as e:
            logger.exception(f"Unexpected debug loop error: {e}")

        logger.info(f"Sleeping {POLL_INTERVAL} seconds before next debug check...")
        time.sleep(POLL_INTERVAL)

if __name__ == "__main__":
    main()
