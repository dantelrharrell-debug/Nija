# nija_client.py
# Requires: requests, PyJWT (with crypto)
#
# Env vars used:
# - COINBASE_API_KEY        (required) e.g. "organizations/{org_id}/apiKeys/{key_id}"
# - COINBASE_API_SECRET     (required) PEM private key as a string (newlines preserved) OR escaped newlines like "\\n"
# - COINBASE_PEM_PATH       (optional) path to PEM file - used if COINBASE_API_SECRET not set
#
# This generates a short-lived JWT (120s) signed ES256, calls the
# GET https://api.coinbase.com/api/v3/brokerage/accounts endpoint,
# pages through results, converts balances to USD using public spot-price
# endpoints and filters out zero balances.

import os
import time
import uuid
import requests
import jwt  # PyJWT
from typing import List, Dict, Any

ACCOUNTS_ENDPOINT = "https://api.coinbase.com/api/v3/brokerage/accounts"
COINBASE_PRICE_URL = "https://api.coinbase.com/v2/prices/{currency}-USD/spot"  # public

# ---------- JWT generation ----------
def _load_private_key_pem() -> str:
    pem = os.getenv("COINBASE_API_SECRET")
    pem_path = os.getenv("COINBASE_PEM_PATH")
    if pem and "\\n" in pem:
        # convert escaped newlines to real newlines if user pasted single-line env var
        pem = pem.replace("\\n", "\n")
    if not pem and pem_path:
        with open(pem_path, "r") as f:
            pem = f.read()
    if not pem:
        raise RuntimeError("COINBASE_API_SECRET or COINBASE_PEM_PATH must be set")
    return pem

def generate_cdp_jwt(api_key: str, valid_seconds: int = 120, method: str = None, host: str = None, path: str = None) -> str:
    """
    Generate a short-lived CDP JWT for REST calls.
    - api_key: the key identifier (used in kid and sub), e.g. "organizations/{org_id}/apiKeys/{key_id}"
    - valid_seconds: token lifetime, default 120s (2 minutes) per Coinbase docs.
    - If you want to bind the JWT to a particular REST URI, you can pass method/host/path and
      add a 'uris' claim (not always required for basic REST calls).
    """
    private_key_pem = _load_private_key_pem()
    now = int(time.time())
    payload = {
        "iss": "cdp",            # Coinbase uses "cdp" as issuer in examples
        "nbf": now,
        "iat": now,
        "exp": now + valid_seconds,
        "sub": api_key
    }

    # Optional: bind to a specific URI (some SDKs show this behavior). We'll include URIs if method/host/path passed.
    if method and host and path:
        # Format like "GET api.coinbase.com /api/v3/brokerage/accounts"
        # Some SDKs implement a 'uris' or 'request' claim — examples vary; this optional inclusion won't break typical usage.
        formatted = f"{method.upper()} {host} {path}"
        payload["uris"] = [formatted]

    headers = {
        "kid": api_key,
        "nonce": uuid.uuid4().hex
    }

    token = jwt.encode(payload, private_key_pem, algorithm="ES256", headers=headers)
    # PyJWT >=2 returns a str; older returns bytes — ensure str
    if isinstance(token, bytes):
        token = token.decode("utf-8")
    return token

# ---------- Helper: get USD spot price ----------
def get_spot_price_usd(currency: str) -> float:
    """
    Returns USD price per 1 unit of `currency` (e.g. 'BTC' -> 56000.0).
    For USD or already-fiat USD, this returns 1.0
    """
    currency = currency.upper()
    if currency in ("USD", "USDC", "USDT"):  # treat USD stablecoins simply as 1:1 (you can extend logic)
        return 1.0
    url = COINBASE_PRICE_URL.format(currency=currency + "")  # e.g. BTC -> BTC-USD
    # currency param must look like "BTC-USD" per URL; above format string expects currency part "BTC-USD"
    # If user passes only "BTC", we need "BTC-USD" in URL:
    if "-" not in currency:
        pair = f"{currency}-USD"
        url = COINBASE_PRICE_URL.format(currency=pair)
    try:
        resp = requests.get(url, timeout=8)
        resp.raise_for_status()
        j = resp.json()
        amount = j.get("data", {}).get("amount")
        if amount is None:
            raise ValueError(f"No spot price returned for {currency}")
        return float(amount)
    except Exception as e:
        # If spot price lookup fails, raise so caller can decide fallback
        raise RuntimeError(f"Failed to fetch spot price for {currency}: {e}")

# ---------- List accounts and convert balances ----------
def list_accounts_with_usd(limit_per_page: int = 100, convert_to_usd: bool = True) -> Dict[str, Any]:
    """
    Returns:
      {
        "accounts": [ { uuid, name, currency, available_value, available_currency, converted_usd }, ... ],
        "total_usd": float
      }
    """
    api_key = os.getenv("COINBASE_API_KEY")
    if not api_key:
        raise RuntimeError("Set COINBASE_API_KEY env var (e.g. organizations/{org}/apiKeys/{id})")

    headers = {}
    all_accounts: List[Dict[str, Any]] = []
    params = {"limit": limit_per_page}
    url = ACCOUNTS_ENDPOINT

    while True:
        # generate fresh JWT for each request (token valid for 120s per docs)
        jwt_token = generate_cdp_jwt(api_key, valid_seconds=120, method="GET", host="api.coinbase.com", path="/api/v3/brokerage/accounts")
        headers["Authorization"] = f"Bearer {jwt_token}"

        resp = requests.get(url, headers=headers, params=params, timeout=15)
        resp.raise_for_status()
        j = resp.json()
        accounts = j.get("accounts", []) or []
        for a in accounts:
            # normalize account structure
            avail = a.get("available_balance") or {}
            value_str = avail.get("value") or "0"
            currency = avail.get("currency") or a.get("currency") or "USD"
            try:
                available_value = float(value_str)
            except Exception:
                available_value = 0.0
            all_accounts.append({
                "uuid": a.get("uuid"),
                "name": a.get("name"),
                "currency": currency,
                "available_value": available_value,
                "available_currency": currency,
                "raw": a
            })

        # pagination
        if j.get("has_next"):
            cursor = j.get("cursor")
            if not cursor:
                break
            params["cursor"] = cursor
            # continue loop; fresh JWT generation will happen again
        else:
            break

    # Convert to USD where requested and filter out zero balances
    total_usd = 0.0
    converted_accounts = []
    prices_cache = {}

    for acct in all_accounts:
        cur = acct["available_currency"].upper()
        amt = acct["available_value"]

        if amt <= 0:
            # filter zeros
            continue

        # conversion
        if cur == "USD":
            usd = amt
        else:
            # caching prices to avoid repeated public calls
            if cur in prices_cache:
                price = prices_cache[cur]
            else:
                try:
                    price = get_spot_price_usd(cur)
                except Exception as e:
                    # If price fetch fails, skip this asset but log as 0 conversion
                    # In production you might retry or use a fallback pricing source.
                    price = 0.0
                prices_cache[cur] = price
            usd = amt * price

        if usd <= 0:
            continue

        acct_out = {
            "uuid": acct["uuid"],
            "name": acct["name"],
            "currency": acct["available_currency"],
            "available": acct["available_value"],
            "converted_usd": round(usd, 8) if usd < 1 else round(usd, 2),
            "raw": acct["raw"]
        }
        converted_accounts.append(acct_out)
        total_usd += usd

    # sort by USD value descending
    converted_accounts.sort(key=lambda x: x["converted_usd"], reverse=True)

    return {"accounts": converted_accounts, "total_usd": round(total_usd, 2)}

# ---------- Standalone test runner ----------
if __name__ == "__main__":
    try:
        out = list_accounts_with_usd(limit_per_page=100)
        print("Total USD across accounts:", out["total_usd"])
        for a in out["accounts"]:
            print(f"{a['currency']:>6} {a['available']:>15}  => ${a['converted_usd']:,}  {a['name']} ({a['uuid']})")
    except Exception as e:
        print("Error:", e)
