# Example simplified nija_client.py
import os, time, json, requests, hmac, hashlib, base64

API_KEY_ID     = os.getenv("COINBASE_KEY_NAME")
API_KEY_SECRET = os.getenv("COINBASE_KEY_SECRET")
REQUEST_HOST   = os.getenv("COINBASE_REQUEST_HOST", "api.exchange.coinbase.com")
BASE_URL       = os.getenv("COINBASE_API_BASE", f"https://{REQUEST_HOST}")

if not all([API_KEY_ID, API_KEY_SECRET]):
    raise EnvironmentError("Missing Coinbase CDP API credentials")

def _generate_signature(method, path, body=""):
    timestamp = str(int(time.time()))
    message = timestamp + method.upper() + path + body
    key_bytes = API_KEY_SECRET.encode('utf-8')  # raw string
    signature = hmac.new(key_bytes, message.encode('utf-8'), hashlib.sha256).digest()
    return timestamp, base64.b64encode(signature).decode()

def _get_headers(method, path, body=None):
    body_json = json.dumps(body, separators=(",", ":")) if body else ""
    timestamp, signature = _generate_signature(method, path, body_json)
    return {
        "CB-ACCESS-KEY": API_KEY_ID,
        "CB-ACCESS-SIGN": signature,
        "CB-ACCESS-TIMESTAMP": timestamp,
        "Content-Type": "application/json"
    }

def get_account_balance():
    path = "/v2/accounts"
    url = BASE_URL + path
    headers = _get_headers("GET", path)
    resp = requests.get(url, headers=headers, timeout=10)
    resp.raise_for_status()
    return resp.json().get("data", [])

def calculate_position_size(account, risk_percent=2):
    available = float(account.get("available", 0))
    return round(available * (risk_percent / 100), 8)

def place_order(product_id, side, size, price=None):
    path = "/v2/orders"
    url = BASE_URL + path
    body = {"type": "market" if not price else "limit", "side": side, "product_id": product_id, "size": str(size)}
    if price: body["price"] = str(price)
    headers = _get_headers("POST", path, body)
    resp = requests.post(url, headers=headers, json=body, timeout=10)
    resp.raise_for_status()
    return resp.json()
