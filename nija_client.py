# nija_client.py
import os
import logging
from decimal import Decimal

# --- Logging setup ---
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("nija_client")

# --- Dummy client fallback ---
class DummyClient:
    def get_accounts(self):
        logger.warning("[DummyClient] Returning fake balances")
        return [{"currency": "USD", "balance": Decimal("1000")}]

# --- Try primary import and gather alternates (best-effort) ---
CoinbaseClient = None
_alt_clients = []

try:
    from coinbase_advanced_py.client import CoinbaseClient
    logger.info("[NIJA] Imported coinbase_advanced_py.client.CoinbaseClient")
except Exception as e:
    CoinbaseClient = None
    logger.warning(f"[NIJA] Failed to import coinbase_advanced_py.client.CoinbaseClient: {e}")

# Try some common alternate entrypoints (best-effort, harmless to attempt)
try:
    from coinbase_advanced_py import RESTClient as RESTClient
    _alt_clients.append(("RESTClient", RESTClient))
    logger.info("[NIJA] Found alternate client: RESTClient")
except Exception:
    pass

try:
    from coinbase_advanced_py import Client as ClientAlt
    _alt_clients.append(("Client", ClientAlt))
    logger.info("[NIJA] Found alternate client: Client")
except Exception:
    pass

# --- Load env vars (may be missing) ---
API_KEY = os.getenv("COINBASE_API_KEY")
API_SECRET = os.getenv("COINBASE_API_SECRET")
API_PASSPHRASE = os.getenv("COINBASE_API_PASSPHRASE")  # can be None

def _attempt_instantiate(client_cls, *args, **kwargs):
    """
    Try to instantiate a client class with args/kwargs and run a quick get_accounts test.
    Returns instance on success, None on any failure.
    """
    try:
        inst = client_cls(*args, **kwargs)
    except Exception as e:
        logger.debug(f"[NIJA-DEBUG] Instantiation failed for {client_cls} with args={args}, kwargs={kwargs}: {e}")
        return None

    try:
        accounts = inst.get_accounts()
        logger.debug(f"[NIJA-DEBUG] get_accounts returned {len(accounts) if accounts is not None else 'None'} items")
        return inst
    except Exception as e:
        logger.debug(f"[NIJA-DEBUG] get_accounts test failed for {client_cls}: {e}")
        return None

def init_client():
    """
    Try multiple auth styles in order and log which succeeded:
      A) CoinbaseClient(api_key, api_secret, passphrase)  -- if passphrase present
      B) CoinbaseClient(api_key, api_secret)               -- no passphrase
      C) Alternate client classes with passphrase / without
    Returns a live client instance on success or DummyClient() on failure.
    """
    # quick env presence info
    logger.info(f"[NIJA] COINBASE_API_KEY present: {'yes' if API_KEY else 'no'}")
    logger.info(f"[NIJA] COINBASE_API_SECRET present: {'yes' if API_SECRET else 'no'}")
    logger.info(f"[NIJA] COINBASE_API_PASSPHRASE present: {'yes' if API_PASSPHRASE else 'no'}")

    if not (API_KEY and API_SECRET):
        logger.warning("[NIJA] Missing API key or secret — cannot instantiate live client.")
        return DummyClient()

    # 1) Try primary CoinbaseClient class if available
    if CoinbaseClient:
        logger.info("[NIJA] Trying primary CoinbaseClient class")
        # A) try with passphrase if provided
        if API_PASSPHRASE:
            logger.info("[NIJA] Attempt: CoinbaseClient(api_key, api_secret, passphrase)")
            inst = _attempt_instantiate(CoinbaseClient, API_KEY, API_SECRET, API_PASSPHRASE)
            if inst:
                logger.info("[NIJA] Authenticated using CoinbaseClient with passphrase")
                return inst
            else:
                logger.warning("[NIJA] CoinbaseClient with passphrase failed")
        # B) try without passphrase
        logger.info("[NIJA] Attempt: CoinbaseClient(api_key, api_secret) (no passphrase)")
        inst = _attempt_instantiate(CoinbaseClient, API_KEY, API_SECRET)
        if inst:
            logger.info("[NIJA] Authenticated using CoinbaseClient without passphrase")
            return inst
        else:
            logger.warning("[NIJA] CoinbaseClient without passphrase failed")

    # 2) Try alternate client classes discovered earlier
    for name, cls in _alt_clients:
        logger.info(f"[NIJA] Trying alternate client '{name}'")
        if API_PASSPHRASE:
            logger.info(f"[NIJA] Attempt: {name}(api_key, api_secret, passphrase)")
            inst = _attempt_instantiate(cls, API_KEY, API_SECRET, API_PASSPHRASE)
            if inst:
                logger.info(f"[NIJA] Authenticated using alternate client {name} with passphrase")
                return inst
            else:
                logger.warning(f"[NIJA] Alternate client {name} with passphrase failed")
        logger.info(f"[NIJA] Attempt: {name}(api_key, api_secret) (no passphrase)")
        inst = _attempt_instantiate(cls, API_KEY, API_SECRET)
        if inst:
            logger.info(f"[NIJA] Authenticated using alternate client {name} without passphrase")
            return inst
        else:
            logger.warning(f"[NIJA] Alternate client {name} without passphrase failed")

    # nothing worked
    logger.warning("[NIJA] Could not authenticate with any client method. Falling back to DummyClient.")
    return DummyClient()

def get_usd_balance(client):
    try:
        accounts = client.get_accounts()
        for acc in accounts:
            if acc.get("currency") == "USD":
                return Decimal(acc.get("balance", "0"))
    except Exception as e:
        logger.warning(f"[NIJA-DEBUG] Could not fetch balances: {e}")
    return Decimal("0")
