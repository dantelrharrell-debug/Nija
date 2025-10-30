# nija_railway_preflight.py
import os
import sys
import logging
from decimal import Decimal

# --- Logging ---
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("nija_preflight")

def mask(val):
    if not val:
        return "<missing>"
    if len(val) <= 8:
        return "*" * len(val)
    return val[:4] + "*" * (len(val) - 8) + val[-4:]

def check_library():
    try:
        import coinbase_advanced_py  # noqa: F401
        logger.info("[OK] coinbase-advanced-py library is installed")
        return True
    except Exception as e:
        logger.error(f"[FAIL] coinbase-advanced-py NOT installed or import failed: {e}")
        return False

def check_env_vars():
    api_key = os.getenv("COINBASE_API_KEY")
    api_secret = os.getenv("COINBASE_API_SECRET")
    passphrase = os.getenv("COINBASE_API_PASSPHRASE")

    logger.info(f"COINBASE_API_KEY: {mask(api_key)}")
    logger.info(f"COINBASE_API_SECRET: {mask(api_secret)}")
    logger.info(f"COINBASE_API_PASSPHRASE: {mask(passphrase)}")

    ok = all([api_key, api_secret, passphrase])
    if not ok:
        logger.error("[FAIL] One or more Coinbase environment variables are missing")
    else:
        logger.info("[OK] All Coinbase environment variables are present")
    return ok, api_key, api_secret, passphrase

def try_instantiate_and_fetch(api_key, api_secret, passphrase):
    try:
        # Import here to ensure the package exists
        from coinbase_advanced_py.client import CoinbaseClient
    except Exception as e:
        logger.error(f"[FAIL] Could not import CoinbaseClient: {e}")
        return False

    try:
        client = CoinbaseClient(api_key, api_secret, passphrase)
    except Exception as e:
        logger.error(f"[FAIL] Failed to instantiate CoinbaseClient: {e}")
        return False

    try:
        accounts = client.get_accounts()
        if not accounts:
            logger.warning("[WARN] Client instantiated but no accounts returned (empty list)")
        # Summarize accounts without revealing sensitive data
        currencies = sorted({a.get("currency") for a in accounts if a.get("currency")})
        logger.info(f"[OK] Accounts currencies available: {currencies}")

        usd_bal = next((Decimal(a.get("balance", "0")) for a in accounts if a.get("currency") == "USD"), Decimal("0"))
        logger.info(f"[OK] USD balance (summary): {usd_bal}")
        return True
    except Exception as e:
        logger.error(f"[FAIL] Error fetching accounts from Coinbase: {e}")
        return False

def main():
    lib_ok = check_library()
    env_ok, api_key, api_secret, passphrase = check_env_vars()

    if not lib_ok or not env_ok:
        logger.error("[PRE-FLIGHT] Pre-flight check FAILED (library/env). Fix and redeploy.")
        sys.exit(1)

    auth_ok = try_instantiate_and_fetch(api_key, api_secret, passphrase)
    if not auth_ok:
        logger.error("[PRE-FLIGHT] Pre-flight check FAILED (auth/accounts).")
        sys.exit(1)

    logger.info("[PRE-FLIGHT] Success — Coinbase client authenticated and accounts fetched.")
    sys.exit(0)

if __name__ == "__main__":
    main()
