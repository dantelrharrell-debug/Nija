import time
from loguru import logger
from nija_coinbase_client import CoinbaseClient
from trading_logic import signal_generator

TRADE_INTERVAL = 10
MIN_BALANCE = 10.0
POSITION_SIZE = 0.5
PRODUCTS = ["BTC-USD", "ETH-USD", "LTC-USD"]

logger.info("Nija Live Trader starting...")

client = CoinbaseClient()

def preflight_check():
    funded = client.get_funded_accounts(min_balance=MIN_BALANCE)
    if not funded["ok"]:
        logger.error(f"Failed preflight check: {funded.get('error')}")
        return []

    accounts = funded["funded_accounts"]
    logger.info(f"Funded accounts ready: {[a['currency'] for a in accounts]}")
    return accounts

def main():
    accounts = preflight_check()
    if not accounts:
        logger.warning("No funded accounts found. Exiting...")
        return

    while True:
        for acct in accounts:
            account_id = acct["id"]
            balance = float(acct["balance"])
            currency = acct["currency"]

            for product in PRODUCTS:
                signal = signal_generator(product)
                size = balance * POSITION_SIZE

                if signal in ["buy", "sell"]:
                    res = client.place_order(account_id, signal, product, size=size)
                    if res.get("ok"):
                        logger.info(f"Order executed: {res['order']}")
                    else:
                        logger.error(f"Order failed: {res.get('error')}")

        logger.info(f"Sleeping {TRADE_INTERVAL}s for next cycle...")
        time.sleep(TRADE_INTERVAL)

if __name__ == "__main__":
    main()
