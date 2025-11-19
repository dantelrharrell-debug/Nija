# bot.py - minimal connection test + heartbeat
import os, logging, time
logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")

def main():
    logging.info("Bot starting — will import coinbase_advanced now.")
    try:
        from coinbase_advanced.client import Client
    except Exception as e:
        logging.exception("coinbase_advanced import failed: %s", e)
        raise

    client = Client(api_key=os.getenv("COINBASE_API_KEY"),
                    api_secret=os.getenv("COINBASE_API_SECRET"),
                    api_passphrase=os.getenv("COINBASE_API_PASSPHRASE", None),
                    api_org_id=os.getenv("COINBASE_ORG_ID", None),
                    pem=(os.getenv("COINBASE_PEM_CONTENT").encode() if os.getenv("COINBASE_PEM_CONTENT") else None))
    logging.info("✅ Coinbase client created — testing accounts fetch")
    try:
        accounts = client.get_accounts()
        logging.info("Fetched %d accounts", len(accounts))
        acct_id = os.getenv("COINBASE_ACCOUNT_ID")
        funded = next((a for a in accounts if a.get("id")==acct_id), None)
        if funded:
            logging.info("✅ Funded account found: %s balance=%s", funded['id'], funded['balance']['amount'])
        else:
            logging.error("❌ Funded account not found in accounts list")
            # keep running so you can debug in logs
    except Exception as e:
        logging.exception("Failed to fetch accounts: %s", e)

    # simple heartbeat
    while True:
        logging.info("Trading loop heartbeat (no trades in this test).")
        time.sleep(10)

if __name__ == "__main__":
    main()
