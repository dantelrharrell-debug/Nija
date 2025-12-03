# test_coinbase_connection.py
import logging
import sys
import traceback
from nija_client import build_client, CDP_API_KEY, load_pem_secret

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
logger = logging.getLogger("test_coinbase")

def main():
    logger.info("Starting Coinbase connection test.")
    try:
        logger.info("CDP_API_KEY: %s", CDP_API_KEY or "<NOT SET>")
        pem = load_pem_secret()
        logger.info("CDP_API_SECRET loaded: %s", "yes" if pem else "no")

        client = build_client()
        logger.info("Client instantiated: %s", type(client))

        # Try a safe read-only call. Different SDK versions expose different methods;
        # attempt a few known read-only methods.
        for fnname in ("get_accounts", "accounts", "get_products", "get_wallets", "list_accounts"):
            try:
                fn = getattr(client, fnname, None)
                if callable(fn):
                    logger.info("Calling client.%s() ...", fnname)
                    result = fn()  # many SDKs return a list-like or Response object
                    logger.info("Success: client.%s returned type %s", fnname, type(result))
                    # don't dump sensitive details
                    return 0
            except Exception as e:
                logger.debug("client.%s threw: %s", fnname, e)

        # If none of the above worked, attempt a low-level call if the client has 'request' or 'send'
        if hasattr(client, "request"):
            try:
                logger.info("Attempting low-level client.request('GET','/health') if available.")
                resp = client.request("GET", "/health")
                logger.info("Low-level request responded: %s", getattr(resp, "status_code", str(type(resp))))
                return 0
            except Exception:
                logger.debug("Low-level request failed:\n%s", traceback.format_exc())

        logger.warning("No known read-only API methods succeeded. Check SDK docs for your installed version.")
        return 1

    except Exception as e:
        logger.exception("Coinbase connection test failed: %s", e)
        return 2

if __name__ == "__main__":
    sys.exit(main())
