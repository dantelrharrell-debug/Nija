from nija_client import CoinbaseClient
import logging

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("nija_live")

def main():
    log.info("Starting Nija Live Trader with Coinbase Advanced API...")
    client = CoinbaseClient()
    
    accounts = client.list_accounts()
    if not accounts.get("ok"):
        log.error(f"Failed to fetch accounts: {accounts}")
        return

    log.info(f"Accounts fetched successfully: {accounts['accounts']}")
    # You can call your trading loop here
    # from nija_trading_loop import start_trading
    # start_trading(client)

if __name__ == "__main__":
    main()
