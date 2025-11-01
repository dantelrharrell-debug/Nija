# nija_render_worker.py
"""
Safe worker for Render & Railway.

- Calls init_client() (from nija_client.py)
- Runs a safe preflight that pulls balances/account amounts
- Optionally fails startup if balance fetch fails (NIJA_REQUIRE_BALANCE_CHECK=1)
"""

import logging
import time
import os
from decimal import Decimal

# Import your client init (assumes nija_client.py is in same package)
from nija_client import init_client, get_usd_balance

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("nija_worker")


def _fetch_usd_balance(client):
    """
    Try multiple common methods on the provided client to fetch a USD balance.
    Returns a Decimal balance if found or None.
    """
    try:
        # Prefer unified helper if provided by nija_client
        if callable(get_usd_balance):
            try:
                bal = get_usd_balance(client)
                if bal is not None:
                    return Decimal(bal)
            except Exception as e:
                logger.debug(f"[NIJA] get_usd_balance() helper failed: {e}")

        # Try common instance methods (names vary across libs)
        if hasattr(client, "get_usd_balance"):
            try:
                bal = client.get_usd_balance()
                return Decimal(bal)
            except Exception as e:
                logger.debug(f"[NIJA] client.get_usd_balance() error: {e}")

        if hasattr(client, "get_account_balance"):
            try:
                bal = client.get_account_balance()
                return Decimal(bal)
            except Exception as e:
                logger.debug(f"[NIJA] client.get_account_balance() error: {e}")

        if hasattr(client, "get_spot_account_balances"):
            try:
                res = client.get_spot_account_balances()
                if isinstance(res, dict) and "USD" in res:
                    return Decimal(res["USD"])
                if isinstance(res, (list, tuple)):
                    for a in res:
                        try:
                            if (isinstance(a, dict) and a.get("currency") == "USD") or getattr(a, "currency", None) == "USD":
                                val = a.get("balance") if isinstance(a, dict) else getattr(a, "balance", None)
                                if val is not None:
                                    return Decimal(val)
                        except Exception:
                            continue
            except Exception as e:
                logger.debug(f"[NIJA] client.get_spot_account_balances() error: {e}")

        if hasattr(client, "get_accounts"):
            try:
                accounts = client.get_accounts()
                if isinstance(accounts, dict):
                    accounts = accounts.get("accounts", accounts)
                if isinstance(accounts, (list, tuple)):
                    for a in accounts:
                        try:
                            if (isinstance(a, dict) and a.get("currency") == "USD") or getattr(a, "currency", None) == "USD":
                                val = a.get("balance") if isinstance(a, dict) else getattr(a, "balance", None)
                                if val is not None:
                                    return Decimal(val)
                        except Exception:
                            continue
            except Exception as e:
                logger.debug(f"[NIJA] client.get_accounts() error: {e}")

        if hasattr(client, "accounts"):
            try:
                accounts = getattr(client, "accounts")
                if isinstance(accounts, (list, tuple)):
                    for a in accounts:
                        try:
                            if (isinstance(a, dict) and a.get("currency") == "USD") or getattr(a, "currency", None) == "USD":
                                val = a.get("balance") if isinstance(a, dict) else getattr(a, "balance", None)
                                if val is not None:
                                    return Decimal(val)
                        except Exception:
                            continue
            except Exception as e:
                logger.debug(f"[NIJA] client.accounts read error: {e}")

    except Exception as e:
        logger.debug(f"[NIJA] Unexpected error while fetching balance: {e}")

    # Not found
    return None


def preflight_check(client):
    """
    Run a preflight check that attempts to pull USD balance and log account info.
    Returns True if preflight is acceptable (balance fetched or not required),
    False if preflight must fail (based on NIJA_REQUIRE_BALANCE_CHECK).
    """
    logger.info("[NIJA-PREFLIGHT] Starting preflight check...")

    balance = None
    try:
        balance = _fetch_usd_balance(client)
    except Exception as e:
        logger.debug(f"[NIJA-PREFLIGHT] Balance fetch raised: {e}")

    if balance is not None:
        logger.info(f"[NIJA-PREFLIGHT] USD balance fetched: {balance}")
        logger.info("[NIJA-PREFLIGHT] Preflight balance fetch OK.")
        return True

    logger.warning("[NIJA-PREFLIGHT] Unable to fetch USD balance during preflight.")

    require_check = os.getenv("NIJA_REQUIRE_BALANCE_CHECK", "0")
    if require_check == "1":
        logger.error("[NIJA-PREFLIGHT] NIJA_REQUIRE_BALANCE_CHECK=1 and balance fetch failed. Aborting startup.")
        return False

    logger.info("[NIJA-PREFLIGHT] Continuing without USD balance (NIJA_REQUIRE_BALANCE_CHECK not set).")
    return True


def run_worker():
    """
    Main worker entrypoint for Gunicorn: nija_render_worker:run_worker
    """
    logger.info("[NIJA] Worker starting...")

    # Initialize client here (safe for Gunicorn import)
    try:
        client = init_client()
    except Exception as e:
        logger.exception(f"[NIJA] init_client() failed: {e}")
        raise

    logger.info(f"[NIJA] Client initialized: {type(client).__name__}")

    ok = True
    try:
        ok = preflight_check(client)
    except Exception as e:
        logger.exception(f"[NIJA] Preflight raised unexpected error: {e}")
        ok = False

    if not ok:
        if os.getenv("NIJA_REQUIRE_BALANCE_CHECK", "0") == "1":
            logger.error("[NIJA] Preflight failed – exiting (balance check required).")
            raise SystemExit(1)
        else:
            logger.warning("[NIJA] Preflight incomplete but continuing (non-fatal).")

    # Main loop (replace with your trading logic)
    logger.info("[NIJA] Entering main loop. Worker is live (or in simulated mode).")
    try:
        while True:
            try:
                bal = _fetch_usd_balance(client)
                if bal is not None:
                    logger.info(f"[NIJA] Periodic USD balance: {bal}")
                else:
                    logger.debug("[NIJA] Periodic balance: unavailable")

                # TODO: Call your trading decision logic here, e.g. decide_trade(client)
                time.sleep(10)
            except Exception as inner_e:
                logger.exception(f"[NIJA] Runtime loop error: {inner_e}")
                time.sleep(5)
    except (KeyboardInterrupt, SystemExit):
        logger.info("[NIJA] Worker shutting down.")
    except Exception as fatal:
        logger.exception(f"[NIJA] Fatal worker error: {fatal}")
        raise


if __name__ == "__main__":
    run_worker()
