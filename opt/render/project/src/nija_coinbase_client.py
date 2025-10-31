import logging, requests
from decimal import Decimal
from nija_coinbase_jwt import get_jwt_token, debug_print_jwt_payload

logger = logging.getLogger("nija_coinbase_client")
logger.setLevel(logging.INFO)
COINBASE_API_URL = "https://api.coinbase.com/v2/accounts"

def get_usd_balance() -> Decimal:
    try:
        token = get_jwt_token()
    except Exception as e:
        logger.error("[NIJA-CLIENT] Failed to get JWT: %s", e)
        return Decimal(0)
    headers = {"Authorization": f"Bearer {token}", "CB-VERSION": "2025-10-01"}
    try:
        debug_print_jwt_payload()
    except: pass
    try:
        resp = requests.get(COINBASE_API_URL, headers=headers, timeout=10)
        if resp.status_code >= 400:
            preview = resp.text[:1000] if resp.text else "<empty>"
            logger.error("[NIJA-CLIENT] Coinbase returned HTTP %s. Body preview: %s", resp.status_code, preview)
        resp.raise_for_status()
        data = resp.json()
        accounts = data.get("data", [])
        logger.debug("[NIJA-CLIENT] Accounts raw data: %s", accounts)
        for acct in accounts:
            if str(acct.get("currency", "")).upper() == "USD":
                amount = acct.get("balance", {}).get("amount", "0")
                bal = Decimal(str(amount))
                logger.info("[NIJA-CLIENT] USD Balance: %s", bal)
                return bal
        logger.warning("[NIJA-CLIENT] No USD account found, returning 0")
        return Decimal(0)
    except requests.exceptions.HTTPError as e:
        logger.error("[NIJA-CLIENT] HTTP error fetching USD balance: %s | body=%s", e, getattr(e.response, "text", None))
        return Decimal(0)
    except Exception as e:
        logger.error("[NIJA-CLIENT] Unexpected error fetching USD balance: %s", e)
        return Decimal(0)
