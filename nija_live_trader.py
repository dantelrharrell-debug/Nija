import time
from loguru import logger
from nija_coinbase_client import CoinbaseClient
from trading_logic import signal_generator
from nija_preflight import get_funded_accounts

TRADE_INTERVAL = 10
POSITION_SIZE = 0.5
PRODUCTS = ["BTC-USD", "ETH-USD", "LTC-USD"]

logger.info("Nija Live Trader starting...")
client = CoinbaseClient()

def main():
    accounts = get_funded_accounts()
    if not accounts:
        logger.warning("No funded accounts found. Exiting...")
        return

    while True:
        for acct in accounts:
            account_id = acct["id"]
            balance = acct["balance"]

            for product in PRODUCTS:
                signal = signal_generator(product)
                size = balance * POSITION_SIZE

                if signal in ["buy", "sell"]:
                    res = client.place_order(account_id, signal, product, size=size)
                    if res.get("ok"):
                        logger.info(f"Order executed: {res['data']}")
                    else:
                        logger.error(f"Order failed: {res.get('error')}")
        logger.info(f"Sleeping {TRADE_INTERVAL}s for next cycle...")
        time.sleep(TRADE_INTERVAL)

if __name__ == "__main__":
    main()
