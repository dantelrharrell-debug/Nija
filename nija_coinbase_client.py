 # nija_coinbase_client.py
import os
import logging
import importlib
import requests
from decimal import Decimal

logger = logging.getLogger("nija_coinbase_client")
logger.setLevel(logging.INFO)

# Environment
API_KEY = os.getenv("COINBASE_API_KEY")
API_SECRET = os.getenv("COINBASE_API_SECRET")
API_PASSPHRASE = os.getenv("COINBASE_API_PASSPHRASE")  # optional
USE_JWT = bool(os.getenv("COINBASE_PEM_KEY") or os.getenv("COINBASE_PEM_KEY_B64"))

# Only import JWT helpers when PEM env exists
get_jwt_token = None
if USE_JWT:
    try:
        from nija_coinbase_jwt import get_jwt_token  # imported lazily
        logger.info("[NIJA-CLIENT] JWT module available and will be used as fallback.")
    except Exception as e:
        logger.warning("[NIJA-CLIENT] JWT module import failed: %s", e)
        get_jwt_token = None
else:
    logger.info("[NIJA-CLIENT] JWT disabled (no PEM env). Using REST key/secret path.")

# Try to discover a REST SDK client class (non-fatal)
_client_candidates = [
    ("coinbase.rest.RESTClient", "from coinbase.rest import RESTClient"),
    ("coinbase.rest_client.RESTClient", "from coinbase.rest_client import RESTClient"),
    ("coinbase_advanced_py.client.RESTClient", "from coinbase_advanced_py.client import RESTClient"),
    ("coinbase_advanced_py.RESTClient", "from coinbase_advanced_py import RESTClient"),
    ("coinbase.RESTClient", "from coinbase import RESTClient"),
]

_instantiated_client = None
_import_attempts = []

def _discover_and_instantiate_rest_client():
    global _instantiated_client
    if not (API_KEY and API_SECRET):
        logger.debug("[NIJA-CLIENT] API_KEY/API_SECRET not present; skipping SDK client discovery.")
        return None

    for name, hint in _client_candidates:
        try:
            parts = hint.replace("from ", "").split(" import ")
            mod_name, cls_name = parts[0].strip(), parts[1].strip()
            mod = importlib.import_module(mod_name)
            cls = getattr(mod, cls_name)
            logger.info(f"[NIJA-CLIENT] Found candidate SDK: {mod_name}.{cls_name}")
            # try common constructor shapes
            for ctor_args in (
                (API_KEY, API_SECRET),
                (),
            ):
                try:
                    if ctor_args:
                        inst = cls(*ctor_args)
                    else:
                        # try keyword form
                        try:
                            inst = cls(api_key=API_KEY, api_secret=API_SECRET)
                        except Exception:
                            inst = cls(api_key=API_KEY, api_secret=API_SECRET, api_passphrase=API_PASSPHRASE)
                    # quick smoke test for balances
                    if hasattr(inst, "get_spot_account_balances"):
                        _ = inst.get_spot_account_balances()
                    elif hasattr(inst, "get_accounts"):
                        _ = inst.get_accounts()
                    logger.info(f"[NIJA-CLIENT] Instantiated SDK client: {mod_name}.{cls_name}")
                    _instantiated_client = inst
                    return inst
                except Exception as e:
                    logger.debug(f"[NIJA-CLIENT] Constructor attempt failed for {name}: {e}")
            _import_attempts.append((hint, "ok"))
        except Exception as e:
            _import_attempts.append((hint, f"failed: {e}"))
            logger.debug(f"[NIJA-CLIENT] Import attempt failed: {hint} -> {e}")
    return None

# instantiate once at module load
try:
    _discover_and_instantiate_rest_client()
except Exception as e:
    logger.debug("[NIJA-CLIENT] Error discovering REST client: %s", e)


# Helper: get USD balance using SDK client if available
def _get_balance_via_sdk(client):
    try:
        if hasattr(client, "get_spot_account_balances"):
            accounts = client.get_spot_account_balances()
        elif hasattr(client, "get_accounts"):
            accounts = client.get_accounts()
        else:
            logger.debug("[NIJA-CLIENT] SDK client has no known balance method.")
            return Decimal(0)
        for a in accounts:
            if a.get("currency") == "USD":
                return Decimal(str(a.get("balance", a.get("amount", "0"))))
    except Exception as e:
        logger.warning(f"[NIJA-CLIENT] SDK balance fetch failed: {e}")
    return Decimal(0)


# Fallback: use JWT + Coinbase v2 API via requests
COINBASE_API_URL = "https://api.coinbase.com/v2/accounts"

def _get_balance_via_jwt():
    if not get_jwt_token:
        logger.debug("[NIJA-CLIENT] get_jwt_token not available")
        return Decimal(0)
    try:
        token = get_jwt_token()
        headers = {"Authorization": f"Bearer {token}", "CB-VERSION": "2025-10-01"}
        resp = requests.get(COINBASE_API_URL, headers=headers, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        for acct in data.get("data", []):
            if acct.get("currency") == "USD":
                balance = Decimal(acct.get("balance", {}).get("amount", "0"))
                return balance
    except Exception as e:
        logger.warning(f"[NIJA-CLIENT] JWT balance fetch failed: {e}")
    return Decimal(0)


# Public API
def get_usd_balance():
    """
    Returns Decimal USD balance (0 on any failure). Tries in order:
      1) SDK REST client instantiated from installed Coinbase SDKs
      2) JWT -> Coinbase v2 /accounts via requests (only if PEM env present and JWT module available)
      3) returns Decimal(0)
    """
    # 1) SDK client
    if _instantiated_client:
        bal = _get_balance_via_sdk(_instantiated_client)
        if bal and bal > 0:
            logger.info(f"[NIJA-CLIENT] USD Balance via SDK: {bal}")
            return bal
        # If SDK returned 0 or failed, we still might succeed via JWT below

    # 2) JWT fallback
    if USE_JWT and get_jwt_token:
        bal = _get_balance_via_jwt()
        if bal and bal > 0:
            logger.info(f"[NIJA-CLIENT] USD Balance via JWT: {bal}")
            return bal

    logger.warning("[NIJA-CLIENT] USD balance is zero or unavailable — returning 0")
    return Decimal(0)
