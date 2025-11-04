# nija_client.py
import os
import logging
from coinbase_advanced_py import Client

log = logging.getLogger("nija_client")
logging.basicConfig(level=logging.INFO)

API_KEY = os.getenv("COINBASE_API_KEY")
API_SECRET = os.getenv("COINBASE_API_SECRET")
API_PASSPHRASE = os.getenv("COINBASE_API_PASSPHRASE")

if not all([API_KEY, API_SECRET, API_PASSPHRASE]):
    raise RuntimeError("Missing one of COINBASE_API_KEY / COINBASE_API_SECRET / COINBASE_API_PASSPHRASE")

def make_client():
    return Client(api_key=API_KEY, api_secret=API_SECRET, api_passphrase=API_PASSPHRASE)

def get_all_accounts():
    client = make_client()
    # coinbase_advanced_py returns a list/dict depending on version; handle exceptions
    return client.get_accounts()

def get_usd_spot_balance():
    accounts = get_all_accounts()
    # accounts may be list of dicts or similar structure
    for a in accounts:
        # safe access — adjust keys to match the returned structure
        if a.get("currency") == "USD" or a.get("currency_code") == "USD":
            bal = a.get("available", a.get("balance", a.get("amount")))
            try:
                return float(bal.get("amount")) if isinstance(bal, dict) else float(bal)
            except Exception:
                try:
                    return float(a.get("balance", {}).get("amount", 0))
                except Exception:
                    return 0.0
    return 0.0

if __name__ == "__main__":
    try:
        accts = get_all_accounts()
        log.info("Preflight: fetched %d accounts", len(accts))
        usd = get_usd_spot_balance()
        log.info("USD balance: %s", usd)
    except Exception as e:
        log.exception("Preflight failed: %s", e)
        raise
