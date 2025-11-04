# nija_client.py
import os
import logging
import json
from coinbase.wallet.client import Client
import requests
from requests.exceptions import RequestException
from json import JSONDecodeError

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("nija_client")

def get_coinbase_client():
    api_key = os.getenv("COINBASE_API_KEY")
    api_secret = os.getenv("COINBASE_API_SECRET")
    if not api_key or not api_secret:
        log.error("Missing Coinbase API credentials in environment variables.")
        raise RuntimeError("COINBASE_API_KEY and COINBASE_API_SECRET must be set")

    # Convert literal "\n" sequences back to newlines if present
    if "\\n" in api_secret:
        api_secret = api_secret.replace("\\n", "\n")

    client = Client(api_key, api_secret)
    log.info("Coinbase client initialized successfully.")
    return client

def _dump_raw_accounts_request(client):
    """
    Try to fetch the accounts using the client's internal Session if available,
    or fall back to direct requests.get to the public Coinbase v2 accounts endpoint.
    This function is only used for diagnostics when the SDK JSON parsing fails.
    """
    base = os.getenv("COINBASE_API_BASE", "https://api.coinbase.com")
    url = base.rstrip('/') + "/v2/accounts"

    # If the coinbase Client exposes a session, use it (best effort)
    session = getattr(client, "_session", None)
    headers = {}
    try:
        if session is not None:
            log.debug("Using client's internal session for diagnostics.")
            resp = session.get(url, timeout=10)
        else:
            log.debug("Using requests.get fallback for diagnostics.")
            resp = requests.get(url, timeout=10)
        return resp.status_code, resp.headers, resp.text[:4000]  # cap large bodies
    except RequestException as e:
        return None, None, f"requests exception: {e}"

def get_usd_spot_balance(client=None, return_account=False):
    """
    Returns USD balance as float. If return_account=True returns (balance, account_obj_or_None).
    This function now captures raw response text if JSON parsing fails so we can debug.
    """
    if client is None:
        client = get_coinbase_client()

    try:
        accounts = client.get_accounts()
        # accounts is expected to be a dict-like with ['data'] list (coinbase sdk format)
        for acc in accounts.get('data', []):
            bal = acc.get('balance', {})
            if bal.get('currency') == "USD":
                amt = float(bal.get('amount', 0))
                return (amt, acc) if return_account else amt

        log.warning("No USD balance present in accounts list.")
        return (0.0, None) if return_account else 0.0

    except JSONDecodeError as je:
        # SDK attempted to json.loads empty or non-json response
        log.error("Error fetching USD balance: JSONDecodeError %s", je)
        code, headers, text = _dump_raw_accounts_request(client)
        log.error("Raw diagnostic response (status, headers, body_snippet): %s, %s, %s", code, headers, repr(text))
        raise

    except Exception as e:
        # Generic catch: try to surface response content if possible
        log.error("Error fetching USD balance: %s %s", type(e).__name__, e)
        # Best-effort diagnostic
        try:
            code, headers, text = _dump_raw_accounts_request(client)
            log.error("Raw diagnostic response (status, headers, body_snippet): %s, %s, %s", code, headers, repr(text))
        except Exception as inner:
            log.error("Diagnostic attempt failed: %s %s", type(inner).__name__, inner)
        raise
