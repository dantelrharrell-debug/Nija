# nija_worker.py
import logging
import time

logger = logging.getLogger("nija_worker")
logger.setLevel(logging.INFO)
if not logger.handlers:
    import sys
    handler = logging.StreamHandler(sys.stdout)
    fmt = logging.Formatter("%(asctime)s %(levelname)s:%(name)s:%(message)s")
    handler.setFormatter(fmt)
    logger.addHandler(handler)

def start_worker(client):
    """
    Placeholder worker that uses the provided client for safe, read-only checks.
    It does NOT place any orders. Replace with your real trading loop when ready.
    """
    logger.info("[NIJA] Placeholder start_worker started — NO TRADING (read-only checks only)")

    try:
        # Single initial check then loop to keep process alive and show logs.
        while True:
            try:
                # Try commonly-available read methods (wrapped by nija_client)
                if hasattr(client, "get_account_balances"):
                    balances = client.get_account_balances()
                    logger.info(f"[NIJA] Current balances (safe-read): {balances}")
                elif hasattr(client, "get_accounts"):
                    accounts = client.get_accounts()
                    logger.info(f"[NIJA] Accounts (safe-read): {accounts}")
                else:
                    logger.info("[NIJA] Client has no known read method; skipping read check")

            except Exception as e:
                logger.error(f"[NIJA] Read-check error from client: {e}")

            # Wait before next check to avoid spamming logs
            time.sleep(30)
    except KeyboardInterrupt:
        logger.info("[NIJA] Placeholder worker interrupted — exiting.")
