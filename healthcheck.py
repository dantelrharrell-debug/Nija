# healthcheck.py
from loguru import logger
from nija_client import CoinbaseClient

logger.add(lambda msg: print(msg, end=""))

def run_check():
    logger.info("HEALTHCHECK: Starting Coinbase client test")
    try:
        # decide advanced_mode via env (nija_client handles it) but explicit True here if you want:
        client = CoinbaseClient()  # uses env and nija_client logic
        accounts = client.fetch_accounts()
        balances = client.get_balances() if hasattr(client, "get_balances") else client.get_account_balances()
        logger.info("HEALTHCHECK: fetch_accounts returned type=%s length=%d", type(accounts).__name__, len(accounts) if hasattr(accounts, "__len__") else 0)
        logger.info("HEALTHCHECK: balances (sample) %s", {k: balances[k] for k in list(balances)[:5]})
        # explicit success condition:
        if accounts and len(accounts) > 0:
            logger.success("HEALTHCHECK: SUCCESS — accounts fetched")
        else:
            logger.warning("HEALTHCHECK: WARNING — no accounts returned (check key permissions / endpoint)")
    except Exception as e:
        logger.error("HEALTHCHECK: FAILURE - Exception during check: %s", e)

if __name__ == "__main__":
    run_check()
