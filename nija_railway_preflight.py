# nija_railway_preflight.py
from nija_coinbase_client import get_usd_balance
import logging
logging.basicConfig(level=logging.INFO)
bal = get_usd_balance()
logging.info("[NIJA-PREFLIGHT] USD balance: %s", bal)
if bal is None:
    raise SystemExit("[NIJA-PREFLIGHT] Preflight failed")
