# nija_client.py
import os
import time
import json
import requests
import hmac
import hashlib
import base64

# Environment variables
API_KEY_ID     = os.getenv("COINBASE_KEY_NAME")      # e.g., organizations/{org_id}/apiKeys/{key_id}
API_KEY_SECRET = os.getenv("COINBASE_KEY_SECRET")    # private key or secret
REQUEST_HOST   = os.getenv("COINBASE_REQUEST_HOST", "api.exchange.coinbase.com")
BASE_URL       = os.getenv("COINBASE_API_BASE", f"https://{REQUEST_HOST}")

if not all([API_KEY_ID, API_KEY_SECRET]):
    raise EnvironmentError("Missing Coinbase CDP server‑side API credentials")

def _generate_signature(method: str, path: str, body: str="") -> str:
    """
    Generate the signature according to Coinbase CDP REST API specification.
    """
    timestamp = str(int(time.time()))
    # According to spec: message = timestamp + method + request_path + body
    message = timestamp + method.upper() + path + body
    # Depending on algorithm: if secret is base64 or PEM private key...
    key_bytes = base64.b64decode(API_KEY_SECRET)
    signature = hmac.new(key_bytes, message.encode('utf-8'), hashlib.sha256).digest()
    signature_b64 = base64.b64encode(signature).decode()
    return timestamp, signature_b64

def _get_headers(method: str, path: str, body: dict=None) -> dict:
    body_json = ""
    if body is not None:
        body_json = json.dumps(body, separators=(",", ":"))
    timestamp, signature = _generate_signature(method, path, body_json)
    return {
        "CB-ACCESS-KEY": API_KEY_ID,
        "CB-ACCESS-SIGN": signature,
        "CB-ACCESS-TIMESTAMP": timestamp,
        "Content-Type": "application/json"
    }

def get_account_balance():
    path = "/v2/accounts"
    url  = BASE_URL + path
    headers = _get_headers("GET", path, body=None)
    resp = requests.get(url, headers=headers, timeout=10)
    try:
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        return {"error": str(e), "status_code": resp.status_code}

def place_order(product_id: str, side: str, size: str, price: str=None):
    path = "/v2/orders"
    url  = BASE_URL + path
    body = {
        "type": "market" if price is None else "limit",
        "side": side,
        "product_id": product_id,
        "size": size
    }
    if price is not None:
        body["price"] = price
    headers = _get_headers("POST", path, body=body)
    resp = requests.post(url, headers=headers, json=body, timeout=10)
    try:
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        return {"error": str(e), "status_code": resp.status_code}
