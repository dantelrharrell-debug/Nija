# nija_client/check_funded.py
import os
from typing import List, Dict

class CoinbaseError(Exception):
    pass

def _client_from_env():
    """
    Try to construct the coinbase_advanced Client using env vars.
    Raises CoinbaseError if keys missing or module missing.
    """
    api_key = os.environ.get("COINBASE_API_KEY")
    api_secret = os.environ.get("COINBASE_API_SECRET")
    api_sub = os.environ.get("COINBASE_API_SUB")  # subscription / client id if used

    if not (api_key and api_secret and api_sub):
        raise CoinbaseError("Missing one or more Coinbase environment variables: COINBASE_API_KEY, COINBASE_API_SECRET, COINBASE_API_SUB")

    try:
        from coinbase_advanced.client import Client
    except ModuleNotFoundError:
        raise CoinbaseError("coinbase_advanced client is not installed in the environment")

    return Client(api_key=api_key, api_secret=api_secret, api_sub=api_sub)

def get_balances() -> List[Dict]:
    """
    Returns a list of {"currency": <str>, "available": <str>} for each account.
    Raises CoinbaseError on problems.
    """
    client = _client_from_env()

    try:
        accounts_resp = client.get_accounts()
    except Exception as e:
        # wrap network/auth errors
        raise CoinbaseError(f"Failed to fetch accounts from Coinbase: {e}")

    accounts = accounts_resp.get("accounts") if isinstance(accounts_resp, dict) else None
    if accounts is None:
        # sometimes the client returns a list or different structure
        # attempt to coerce
        try:
            # if accounts_resp itself is a list of accounts
            if isinstance(accounts_resp, list):
                accounts = accounts_resp
            else:
                raise CoinbaseError("Unexpected accounts response format from Coinbase client.")
        except Exception as e:
            raise CoinbaseError(str(e))

    balances = []
    for acct in accounts:
        # robust extraction
        curr = acct.get("currency") or acct.get("asset") or acct.get("id", "UNKNOWN")
        avail = acct.get("available_balance", {}).get("value")
        if avail is None:
            # try other common fields
            avail = acct.get("available") or acct.get("balance", {}).get("amount") if isinstance(acct.get("balance"), dict) else None

        # normalize to string
        try:
            avail_str = str(avail) if avail is not None else "0"
        except Exception:
            avail_str = "0"

        balances.append({"currency": curr, "available": avail_str})

    return balances

def check_funded_accounts(min_usd = 1.0) -> bool:
    """
    Helper used previously: return True if any account has available balance > min_usd
    Will attempt to convert non-USD balances by skipping them (simple).
    """
    balances = get_balances()
    for b in balances:
        try:
            if float(b.get("available", "0")) > min_usd and b.get("currency","").upper() == "USD":
                return True
        except Exception:
            continue
    # fallback: if any nonzero balance exists
    for b in balances:
        try:
            if float(b.get("available", "0")) > 0:
                return True
        except Exception:
            continue
    return False
