# nija_render_worker.py
import os
from time import sleep
from loguru import logger

# --- Configure logger ---
logger.add("/tmp/worker.log", rotation="10 MB", retention="7 days", level="INFO")
logger.info("Logger initialized")

# --- Helper: Dump environment variables ---
def dump_env_snippet():
    relevant = [
        "COINBASE_API_KEY",
        "COINBASE_API_SECRET",
        "COINBASE_API_PASSPHRASE",
        "COINBASE_ACCOUNT_ID",
        "COINBASE_PEM_CONTENT",
        "COINBASE_ORG_ID",
        "COINBASE_JWT_KID",
        "LIVE_TRADING"
    ]
    logger.info("Env variables snapshot:")
    for k in relevant:
        v = os.getenv(k)
        if not v:
            logger.warning(f"{k}: MISSING")
        else:
            sample = v.strip().splitlines()[0][:40]
            logger.info(f"{k}: present, startswith: {sample!r}")

# --- Try initializing Coinbase client using API key/secret ---
def try_init_client_api_key_mode():
    try:
        from coinbase_advanced.client import Client
    except ImportError:
        logger.error("coinbase_advanced SDK not installed. Install via requirements.txt.")
        raise

    api_key = os.getenv("COINBASE_API_KEY")
    api_secret = os.getenv("COINBASE_API_SECRET")
    api_pass = os.getenv("COINBASE_API_PASSPHRASE") or None

    if not api_key or not api_secret:
        logger.warning("API key/secret not provided -> skipping API-key init")
        return None

    # Prevent accidental PEM passed as API secret
    if "BEGIN" in api_secret and "PRIVATE KEY" in api_secret:
        logger.warning("COINBASE_API_SECRET looks like PEM. Skipping API-key mode.")
        return None

    logger.info("Attempting Coinbase client init using API_KEY/API_SECRET...")
    try:
        client = Client(api_key=api_key, api_secret=api_secret, api_passphrase=api_pass)
        logger.success("✅ Coinbase client initialized (API key mode)")
        return client
    except Exception as e:
        logger.exception("Failed to initialize Coinbase client in API key mode")
        return None

# --- Test connection ---
def test_connection(client):
    try:
        accounts = client.get_accounts()
        logger.info(f"✅ Fetched {len(accounts)} accounts")
        acct_id = os.getenv("COINBASE_ACCOUNT_ID")
        if acct_id:
            funded = next(
                (a for a in accounts if a.get("id") == acct_id or a.get("currency") == acct_id),
                None
            )
            if funded:
                logger.success(f"✅ Funded account found: {funded.get('id')} balance={funded.get('balance')}")
                return True
            else:
                logger.warning("Funded account ID not found among accounts")
        else:
            logger.info("COINBASE_ACCOUNT_ID not set; cannot locate funded account")
        return False
    except Exception:
        logger.exception("Error while testing Coinbase connection")
        return False

# --- Main worker ---
def main():
    logger.info("nija_render_worker starting up")
    dump_env_snippet()

    client = try_init_client_api_key_mode()
    if client:
        ok = test_connection(client)
        if not ok:
            logger.error("Connection test failed (API key mode). Check COINBASE_API_KEY/SECRET.")
            raise SystemExit("Coinbase connection failed (API key mode)")
    else:
        logger.error("No usable Coinbase API key/secret found. Use JWT/PEM auth or valid API key/secret.")
        raise SystemExit("No usable Coinbase auth method found")

    logger.info("⚡ Starting main trading loop (placeholder)")
    while True:
        try:
            accounts = client.get_accounts()
            logger.info(f"Tick: accounts={len(accounts)}")
            sleep(10)
        except Exception:
            logger.exception("Error in trading loop; retrying in 5s")
            sleep(5)

if __name__ == "__main__":
    main()
