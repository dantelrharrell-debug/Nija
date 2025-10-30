import logging
from flask import Flask

# --- Setup logging ---
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("nija_worker")

# --- Import client from nija_client ---
try:
    from nija_client import client, USE_DUMMY
except ImportError as e:
    logger.error(f"[NIJA] Failed to import client from nija_client: {e}")
    raise

app = Flask(__name__)

@app.route("/")
def health_check():
    status = "DummyClient (no live trades)" if USE_DUMMY else "Live CoinbaseClient"
    return f"Nija Trading Bot is running. Status: {status}"

# --- Start Worker ---
if __name__ == "__main__":
    if USE_DUMMY:
        logger.warning("[NIJA] Using DummyClient — live trading disabled")
    else:
        logger.info("[NIJA] Using Live CoinbaseClient — live trading enabled")

    # Start your Nija worker logic here, passing `client` where needed
    from nija_worker import start_worker  # your existing worker function
    start_worker(client)

    # Start Flask for health check
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 8080)))
