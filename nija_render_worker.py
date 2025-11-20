# nija_render_worker.py
import os, logging, time
from time import sleep

LOG_PATH = "/tmp/worker.log"
logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
logger = logging.getLogger("nija_worker")

def dump_env_snippet():
    relevant = ["COINBASE_API_KEY", "COINBASE_API_SECRET", "COINBASE_ACCOUNT_ID",
                "COINBASE_PEM_CONTENT", "COINBASE_ORG_ID", "COINBASE_JWT_KID", "LIVE_TRADING"]
    logger.info("Env variables snapshot:")
    for k in relevant:
        v = os.getenv(k)
        # show whether present and small hint (masked)
        if not v:
            logger.info(f"  {k}: MISSING")
        else:
            samples = v.strip().splitlines()[0][:40]
            logger.info(f"  {k}: present, startswith: {samples!r}")

def try_init_client_api_key_mode():
    try:
        from coinbase_advanced.client import Client
    except Exception as e:
        logger.exception("coinbase_advanced import failed. SDK may not be installed.")
        raise

    api_key = os.getenv("COINBASE_API_KEY")
    api_secret = os.getenv("COINBASE_API_SECRET")
    api_pass = os.getenv("COINBASE_API_PASSPHRASE") or None
    if not api_key or not api_secret:
        logger.info("API key/secret not provided -> skipping API-key init attempt.")
        return None

    # quick sanity detection: if api_secret looks like a PEM (contains BEGIN), bail and return None
    if "BEGIN" in api_secret and "PRIVATE KEY" in api_secret:
        logger.info("COINBASE_API_SECRET looks like a PEM block. API-key/secret mode unlikely to work.")
        return None

    logger.info("Attempting Coinbase client init using API_KEY/API_SECRET...")
    try:
        client = Client(api_key=api_key, api_secret=api_secret, api_passphrase=api_pass)
        logger.info("✅ Coinbase client (api_key mode) created")
        return client
    except Exception as e:
        logger.exception("Failed to initialize Client in api_key mode.")
        return None

def test_connection(client):
    try:
        accounts = client.get_accounts()
        logger.info(f"✅ Fetched {len(accounts)} accounts")
        acct_id = os.getenv("COINBASE_ACCOUNT_ID")
        if acct_id:
            funded = next((a for a in accounts if a.get("id")==acct_id or a.get("currency")==acct_id), None)
            if funded:
                logger.info(f"✅ Funded account found: {funded.get('id')} balance={funded.get('balance')}")
                return True
            else:
                logger.warning("Funded account ID not found among accounts.")
        else:
            logger.info("COINBASE_ACCOUNT_ID not set; cannot locate funded account here.")
        return False
    except Exception as e:
        logger.exception("Error while testing Coinbase connection")
        return False

def main():
    logger.info("nija_render_worker starting up")
    dump_env_snippet()

    # Try API-key mode first
    client = None
    try:
        client = try_init_client_api_key_mode()
    except Exception:
        logger.exception("SDK import or api-key init failed.")

    if client:
        ok = test_connection(client)
        if not ok:
            logger.error("Connection test failed using API key method. Please check COINBASE_API_KEY / COINBASE_API_SECRET values.")
            raise SystemExit("Coinbase connection test failed (api key mode).")
    else:
        # no client from api-key path — give clear instructions
        logger.error("Could not initialize client using API key/secret.")
        logger.error("If you intend to use JWT/PEM-based auth, ensure COINBASE_PEM_CONTENT (PEM), COINBASE_ORG_ID and COINBASE_JWT_KID are set.")
        logger.error("Alternatively, create a standard API key/secret pair in Coinbase Advanced and set COINBASE_API_KEY and COINBASE_API_SECRET to those values (not the PEM).")
        raise SystemExit("No usable Coinbase auth method found")

    # If we reached here, we have a client and can run the trading loop
    logger.info("⚡ Starting trading loop (placeholder) — will log account counts every 10s")
    while True:
        try:
            accounts = client.get_accounts()
            logger.info(f"Tick: accounts={len(accounts)}")
            sleep(10)
        except Exception:
            logger.exception("Error in trading loop; sleeping 5s")
            sleep(5)

if __name__ == "__main__":
    main()
