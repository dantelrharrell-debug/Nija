# nija_railway_preflight.py
import os
import sys
import logging
from decimal import Decimal

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
        logger.error(f"[FAIL] coinbase-advanced-py NOT installed: {e}")
        return False

def check_env_vars():
    api_key = os.getenv("COINBASE_API_KEY")
    api_secret = os.getenv("COINBASE_API_SECRET")
    passphrase = os.getenv("COINBASE_API_PASSPHRASE")

    logger.info(f"COINBASE_API_KEY: {mask(api_key)}")
    logger.info(f"COINBASE_API_SECRET: {mask(api_secret)}")
    logger.info(f"COINBASE_API_PASSPHRASE: {mask(passphrase)}")

    ok_basic = bool(api_key and api_secret)
    if not ok_basic:
        logger.error("[FAIL] API key and/or secret missing.")
    else:
        logger.info("[OK] API key and secret present. Passphrase optional.")
    return ok_basic, api_key, api_secret, passphrase

def try_instantiate_and_fetch(api_key, api_secret, passphrase):
    try:
        from coinbase_advanced_py import CoinbaseClient
    except Exception as e:
        logger.error(f"[FAIL] Could not import CoinbaseClient: {e}")
        return False

    # Try no-passphrase first
    try:
        logger.info("[PRE-FLIGHT] Trying CoinbaseClient(api_key, api_secret)...")
        client = CoinbaseClient(api_key=api_key, api_secret=api_secret)
        accounts = client.get_accounts()
        logger.info("[OK] Authenticated without passphrase.")
        _report_accounts(accounts)
        return True
    except Exception as e:
        logger.warning(f"[PRE-FLIGHT] CoinbaseClient without passphrase failed: {e}")

    # Try with passphrase if present
    if passphrase:
        try:
            logger.info("[PRE-FLIGHT] Trying CoinbaseClient(api_key, api_secret, passphrase)...")
            client = CoinbaseClient(api_key=api_key, api_secret=api_secret, api_passphrase=passphrase)
            accounts = client.get_accounts()
            logger.info("[OK] Authenticated with passphrase.")
            _report_accounts(accounts)
            return True
        except Exception as e:
            logger.error(f"[PRE-FLIGHT] CoinbaseClient with passphrase failed: {e}")

    logger.error("[FAIL] Could not authenticate with Coinbase using either method.")
    return False

def _report_accounts(accounts):
    if not accounts:
        logger.warning("[WARN] Authenticated but no accounts returned.")
        return
    currencies = sorted({a.get("currency") for a in accounts if a.get("currency")})
    usd_bal = next((Decimal(a.get("balance", "0")) for a in accounts if a.get("currency") == "USD"), Decimal("0"))
    logger.info(f"[OK] Available currencies: {currencies}")
    logger.info(f"[OK] USD balance: {usd_bal}")

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
