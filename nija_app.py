# nija_app.py
from flask import Flask, jsonify
import os, time, hmac, hashlib, base64, requests

app = Flask(__name__)

# --------------------------
# Load Coinbase credentials
# --------------------------
API_KEY = os.getenv("COINBASE_API_KEY")
API_SECRET = os.getenv("COINBASE_API_SECRET")
API_PASSPHRASE = os.getenv("COINBASE_API_PASSPHRASE")
API_BASE = os.getenv("COINBASE_API_BASE", "https://api.coinbase.com")

# --------------------------
# Preflight: validate credentials
# --------------------------
def preflight_check():
    missing = []
    for var, val in [("API_KEY", API_KEY), ("API_SECRET", API_SECRET), ("API_PASSPHRASE", API_PASSPHRASE)]:
        if not val:
            missing.append(var)
    if missing:
        raise RuntimeError(f"Missing Coinbase credentials: {', '.join(missing)}")

    # Minimal test to validate credentials
    ts = str(int(time.time()))
    path = "/v2/accounts"
    prehash = ts + "GET" + path
    try:
        sig = base64.b64encode(hmac.new(base64.b64decode(API_SECRET), prehash.encode(), hashlib.sha256).digest()).decode()
    except Exception as e:
        raise RuntimeError(f"Error decoding API_SECRET: {e}")

    headers = {
        "CB-ACCESS-KEY": API_KEY,
        "CB-ACCESS-SIGN": sig,
        "CB-ACCESS-TIMESTAMP": ts,
        "CB-ACCESS-PASSPHRASE": API_PASSPHRASE,
        "CB-VERSION": "2025-11-02",
        "Content-Type": "application/json"
    }

    resp = requests.get(API_BASE + path, headers=headers, timeout=15)
    if resp.status_code != 200:
        raise RuntimeError(f"Coinbase preflight failed: {resp.status_code} {resp.text}")
    print("✅ Coinbase preflight check passed.")

# Run preflight before starting bot
preflight_check()

# --------------------------
# Helper: generate Coinbase signature
# --------------------------
def generate_signature(path, method="GET", body=""):
    ts = str(int(time.time()))
    prehash = ts + method.upper() + path + body
    sig = base64.b64encode(
        hmac.new(base64.b64decode(API_SECRET), prehash.encode(), hashlib.sha256).digest()
    ).decode()
    return ts, sig

# --------------------------
# Fetch USD balance
# --------------------------
def get_usd_balance():
    path = "/v2/accounts"
    ts, sig = generate_signature(path)
    headers = {
        "CB-ACCESS-KEY": API_KEY,
        "CB-ACCESS-SIGN": sig,
        "CB-ACCESS-TIMESTAMP": ts,
        "CB-ACCESS-PASSPHRASE": API_PASSPHRASE,
        "CB-VERSION": "2025-11-02",
        "Content-Type": "application/json"
    }
    try:
        r = requests.get(API_BASE + path, headers=headers, timeout=15)
        r.raise_for_status()
        data = r.json()
        for account in data.get("data", []):
            if account.get("currency") == "USD":
                return float(account.get("balance", {}).get("amount", 0))
        return 0.0
    except requests.exceptions.RequestException as e:
        print("Error fetching USD balance:", e)
        return 0.0

# --------------------------
# Flask endpoints
# --------------------------
@app.route("/")
def index():
    return "Nija AI Bot Web Service Running"

@app.route("/test-balance")
def test_balance():
    balance = get_usd_balance()
    return jsonify({"USD_Balance": balance})

# --------------------------
# Run app
# --------------------------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 10000)))
