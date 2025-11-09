# start_bot.py
from loguru import logger
from decimal import Decimal
from nija_balance_helper import get_usd_balance

# Try to import the client under the common names we saw in repo
try:
    # most likely correct class name in nija_client.py
    from nija_client import CoinbaseClient as _Client
except Exception:
    try:
        from nija_client import NijaCoinbaseClient as _Client
    except Exception:
        raise ImportError("Neither 'CoinbaseClient' nor 'NijaCoinbaseClient' could be imported from nija_client.py")

logger.remove()
logger.add(lambda msg: print(msg, end=""), level="INFO")
logger = logger.bind(name="start_bot")

logger.info("Starting Nija bot (entrypoint)")

# instantiate client (some clients accept advanced=True)
try:
    client = _Client(advanced=True)
except TypeError:
    # fallback if the constructor signature is different
    client = _Client()

# quick diagnostics
try:
    balances = client.get_balances() if hasattr(client, "get_balances") else client.get_accounts()
    logger.info("Balances (raw): %s", balances)
except Exception as e:
    logger.exception("Error fetching balances: %s", e)

# show USD via your helper
try:
    usd = get_usd_balance(client)
    logger.info("USD balance (helper): %s", usd)
except Exception as e:
    logger.exception("Error computing USD balance: %s", e)

# keep process alive for logs (short loop)
import time
for i in range(3):
    logger.info("Startup complete — tick %d/3", i+1)
    time.sleep(1)
logger.info("Exiting start_bot (replace this with your live loop once verified).")
