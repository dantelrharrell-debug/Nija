# start_nija_live_advanced.py
import os
import time
from loguru import logger
from decimal import Decimal

# simple, robust bootstrap for Coinbase Advanced (PEM/JWT)
from nija_coinbase_advanced import get_key_permissions, get_accounts
from nija_balance_helper import get_usd_balance

logger.remove()
logger.add(lambda msg: print(msg, end=""), level="INFO")
logger = logger.bind(name="nija_entry")

# config
POLL_SECONDS = int(os.getenv("NIJA_POLL_SECONDS", "10"))
MIN_USD_TO_TRADE = Decimal(os.getenv("NIJA_MIN_TRADE_USD", "10"))

logger.info("Starting Nija (Advanced/JWT) entrypoint")

# verify env
if not (os.getenv("COINBASE_PEM_CONTENT") or os.getenv("COINBASE_PRIVATE_KEY_PATH")):
    logger.error("Missing COINBASE_PEM_CONTENT and COINBASE_PRIVATE_KEY_PATH. Aborting.")
    raise SystemExit(1)
if not os.getenv("COINBASE_ISS"):
    logger.error("Missing COINBASE_ISS. Aborting.")
    raise SystemExit(1)

# permissions check
try:
    resp = get_key_permissions()
    if resp is None:
        logger.error("Key permissions request returned no response. Aborting.")
        raise SystemExit(1)
    logger.info(f"key_permissions status={resp.status_code}")
    if resp.status_code != 200:
        logger.error("Key permissions check failed; inspect permissions and BASE_URL. Aborting.")
        logger.info("Response (truncated): %s", (getattr(resp, "text", "") or "")[:1000])
        raise SystemExit(1)
    logger.info("Key permissions OK (200).")
except Exception as e:
    logger.exception("Exception during key permissions check: %s", e)
    raise SystemExit(1)

# fetch accounts once
accounts_data = get_accounts()
if not accounts_data:
    logger.error("No accounts returned from get_accounts(). Aborting.")
    raise SystemExit(1)

if isinstance(accounts_data, dict):
    accounts_list = accounts_data.get("accounts") or accounts_data.get("data") or []
else:
    accounts_list = accounts_data

logger.info("Fetched %d account(s) on startup", len(accounts_list))
for acc in accounts_list:
    name = acc.get("name") or acc.get("id") or acc.get("address")
    bal = acc.get("balance") or {}
    amt = bal.get("amount") if isinstance(bal, dict) else bal
    cur = bal.get("currency") if isinstance(bal, dict) else acc.get("currency")
    logger.info("Account: %s -> %s %s", name, amt, cur)

# compute USD via helper
usd = get_usd_balance(__import__("nija_coinbase_advanced"))
logger.info("Computed USD (helper): %s", usd)

# minimal live loop
logger.info("Starting live loop (POLL_SECONDS=%s)", POLL_SECONDS)
while True:
    try:
        usd = get_usd_balance(__import__("nija_coinbase_advanced"))
        logger.info("USD available: %s", usd)
        if usd >= MIN_USD_TO_TRADE:
            logger.info("Sufficient balance to trade (>= %s) — ready.", MIN_USD_TO_TRADE)
            # insert order execution here when you're ready
        else:
            logger.info("Balance below min trade threshold; waiting.")
        time.sleep(POLL_SECONDS)
    except KeyboardInterrupt:
        logger.info("Shutting down (keyboard interrupt).")
        break
    except Exception:
        logger.exception("Exception in live loop; continuing.")
        time.sleep(POLL_SECONDS)
