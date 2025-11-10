#!/usr/bin/env python3
import os
import sys
import traceback
from loguru import logger

# ---------- Setup logger ----------
logger.remove()
logger.add(lambda msg: print(msg, end=""), level=os.getenv("LOG_LEVEL", "INFO"))

# ---------- Load .env ----------
try:
    from dotenv import load_dotenv
    load_dotenv()
    logger.info(".env loaded")
except ImportError:
    logger.warning("python-dotenv not installed, relying on environment variables only")

# ---------- Import helper ----------
def load_from_app():
    try:
        from app.nija_client import CoinbaseClient
        logger.info("Imported CoinbaseClient from app.nija_client")
        return CoinbaseClient
    except Exception:
        logger.warning("Could not import from app.nija_client:\n" + traceback.format_exc())
        return None

def load_from_root():
    try:
        from nija_client import CoinbaseClient
        logger.info("Imported CoinbaseClient from root nija_client.py")
        return CoinbaseClient
    except Exception:
        logger.warning("Could not import from root nija_client.py:\n" + traceback.format_exc())
        return None

# ---------- Main ----------
def main():
    logger.info("Starting Nija loader (robust).")

    # --- Import CoinbaseClient ---
    CoinbaseClient = load_from_app() or load_from_root()

    if CoinbaseClient is None:
        logger.error("FATAL: Cannot import CoinbaseClient from either app.nija_client nor nija_client.")
        logger.error("Check: 1) app/__init__.py exists, 2) app/nija_client.py exists, 3) you're running from project root.")
        sys.exit(1)

    # --- Instantiate client & fetch accounts ---
    try:
        client = CoinbaseClient(advanced=True)

        accounts = []
        if hasattr(client, "fetch_advanced_accounts"):
            accounts = client.fetch_advanced_accounts()
        else:
            # fallback to generic request
            try:
                status, data = client.request("GET", "/v3/accounts")
                if status == 200 and data:
                    accounts = data.get("data", []) if isinstance(data, dict) else []
            except Exception:
                accounts = []

        if not accounts:
            logger.error("No accounts returned. Verify COINBASE env vars, key permissions, and COINBASE_BASE.")
            sys.exit(1)

        logger.info("Accounts:")
        for a in accounts:
            logger.info(f" - {a.get('name', a.get('id', '<unknown>'))}")

        logger.info("✅ HMAC/Advanced account check passed. Ready to start trading loop (not included here).")

    except Exception:
        logger.exception("Error during CoinbaseClient initialization or account fetch")
        sys.exit(1)

if __name__ == "__main__":
    main()
