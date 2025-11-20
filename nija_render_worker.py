import os
import time
from time import sleep
from loguru import logger

logger.info("nija_render_worker starting up")

# --- Helper functions ---

def dump_env_snippet():
    relevant = ["COINBASE_API_KEY", "COINBASE_API_SECRET", "COINBASE_ACCOUNT_ID",
                "COINBASE_PEM_CONTENT", "COINBASE_ORG_ID", "COINBASE_JWT_KID", "LIVE_TRADING"]
    logger.info("Env variables snapshot:")
    for k in relevant:
        v = os.getenv(k)
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
    api_pass = os.getenv("COINBASE_PASSPHRASE") or None
    if not api_key or not api_secret:
        logger.info("API key/secret not provided -> skipping API-key init attempt.")
        return None

    if "BEGIN" in api_secret and "PRIVATE KEY" in api_secret:
        logger.info("COINBASE_API_SECRET looks like a PEM block. API-key/secret mode unlikely to work.")
        return None

    logger.info("Attempting Coinbase client init using API_KEY/API_SECRET...")
    try:
        client = Client(api_key=api_key, api_secret=api_secret, api_passphrase=api_pass)
        logger.info("✅ Coinbase client (api_key mode) created")
        return client
    except Exception:
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
    except Exception:
        logger.exception("Error while testing Coinbase connection")
        return False

# --- Main Worker Loop ---

def main():
    dump_env_snippet()
    client = try_init_client_api_key_mode()

    if not client:
        logger.error("No usable Coinbase auth method found. Set API_KEY/SECRET or PEM credentials.")
        raise SystemExit("Cannot start worker: Coinbase auth missing")

    if not test_connection(client):
        logger.error("Coinbase connection test failed. Check credentials.")
        raise SystemExit("Coinbase connection failed")

    logger.info("⚡ Starting trading loop (placeholder)")
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
