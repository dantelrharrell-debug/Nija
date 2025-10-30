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

# --- Check library presence ---
def check_library():
    try:
        import coinbase_advanced_py  # noqa: F401
        logger.info("[OK] coinbase-advanced-py library is installed")
        return True
    except Exception as e:
        logger.warning(f"[WARN] coinbase-advanced-py library NOT fully available: {e}")
        return False

# --- Check environment variables ---
def check_env_vars():
    api_key = os.getenv("COINBASE_API_KEY")
    api_secret = os.getenv("COINBASE_API_SECRET")
    passphrase = os.getenv("COINBASE_API_PASSPHRASE")

    logger.info(f"COINBASE_API_KEY: {mask(api_key)}")
    logger.info(f"COINBASE_API_SECRET: {mask(api_secret)}")
    logger.info(f"COINBASE_API_PASSPHRASE: {mask(passphrase)}")

    ok_basic = bool(api_key and api_secret)
    if not ok_basic:
        logger.warning("[WARN] API key and/or secret missing. Live trading will be disabled.")
    else:
        logger.info("[OK] API key and secret present. Passphrase optional; will attempt both auth styles.")
    return ok_basic

# --- Fake authentication check (DummyClient only) ---
def try_auth():
    # Since CoinbaseClient import fails, always use DummyClient
    from nija_client import DummyClient
    client = DummyClient()
    accounts = client.get_accounts()
    usd_bal = next((Decimal(a.get("balance", "0")) for a in accounts if a.get("currency") == "USD"), Decimal("0"))
    logger.info(f"[INFO] Running in DummyClient mode. USD balance: {usd_bal}")
    logger.warning("[WARN] Live trading is disabled until the correct CoinbaseClient import is fixed.")
    return True

def main():
    lib_ok = check_library()
    env_ok = check_env_vars()

    if not lib_ok or not env_ok:
        logger.warning("[WARN] Pre-flight check detected issues. DummyClient will be used.")
    try_auth()

    logger.info("[PRE-FLIGHT] Pre-flight complete. Deploying with DummyClient.")
    sys.exit(0)

if __name__ == "__main__":
    main()
