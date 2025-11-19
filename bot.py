# bot.py (skeleton)
import os, logging, time
from time import sleep

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")

def setup_client():
    try:
        # import after coinbase-advanced installed at runtime
        from coinbase_advanced.client import Client
    except Exception as e:
        logging.error("coinbase_advanced import failed: %s", e)
        raise

    api_key = os.environ.get("COINBASE_API_KEY")
    api_secret = os.environ.get("COINBASE_API_SECRET")
    api_passphrase = os.environ.get("COINBASE_API_PASSPHRASE")  # if used
    org_id = os.environ.get("COINBASE_ORG_ID")
    pem = os.environ.get("COINBASE_PEM_CONTENT")  # optional

    client = Client(
        api_key=api_key,
        api_secret=api_secret,
        api_passphrase=api_passphrase,
        api_org_id=org_id,
        pem=pem.encode() if pem else None
    )
    logging.info("✅ Coinbase client initialized")
    return client

def test_connection(client):
    try:
        accounts = client.get_accounts()
        logging.info(f"Fetched {len(accounts)} accounts")
        acct_id = os.environ.get("COINBASE_ACCOUNT_ID")
        funded = next((a for a in accounts if a.get("id")==acct_id), None)
        if funded:
            logging.info("✅ Funded account found: %s balance=%s", funded['id'], funded['balance']['amount'])
        else:
            logging.error("❌ Funded account id not found in accounts")
        return bool(funded)
    except Exception as e:
        logging.exception("Coinbase connection/test failed: %s", e)
        return False

def main():
    client = setup_client()
    ok = test_connection(client)
    if not ok:
        logging.error("Cannot find funded account — exiting")
        raise SystemExit(1)

    logging.info("⚡ Starting trading loop")
    while True:
        try:
            # put your trading logic here
            logging.info("Trading loop heartbeat")
            sleep(10)
        except Exception as e:
            logging.exception("Error in trading loop: %s", e)
            sleep(5)

if __name__ == "__main__":
    main()
