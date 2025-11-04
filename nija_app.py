# nija_app.py
from flask import Flask, jsonify
import os, time, hmac, hashlib, base64, requests

app = Flask(__name__)

# --------------------------
# Coinbase API credentials (no passphrase)
# --------------------------
API_KEY = os.getenv("COINBASE_API_KEY")
API_SECRET = os.getenv("COINBASE_API_SECRET")  # must be base64 encoded
API_BASE = os.getenv("COINBASE_API_BASE", "https://api.coinbase.com")

if not API_KEY or not API_SECRET:
    raise RuntimeError("Coinbase API_KEY and API_SECRET must be set in environment variables.")

# --------------------------
# Helper: generate HMAC signature
# --------------------------
def generate_signature(path, method="GET", body=""):
    ts = str(int(time.time()))
    prehash = ts + method.upper() + path + body
    sig = base64.b64encode(
        hmac.new(base64.b64decode(API_SECRET), prehash.encode(), hashlib.sha256).digest()
    ).decode()
    return ts, sig

# --------------------------
# Get account info from Coinbase
# --------------------------
def get_all_accounts():
    path = "/v2/accounts"
    ts, sig = generate_signature(path)
    headers = {
        "CB-ACCESS-KEY": API_KEY,
        "CB-ACCESS-SIGN": sig,
        "CB-ACCESS-TIMESTAMP": ts,
        "CB-VERSION": "2025-11-02",
        "Content-Type": "application/json"
    }
    try:
        r = requests.get(API_BASE + path, headers=headers, timeout=15)
        r.raise_for_status()
        return r.json()
    except requests.exceptions.RequestException as e:
        print("❌ Coinbase API request failed:", e)
        return None

# --------------------------
# Get USD balance
# --------------------------
def get_usd_balance():
    data = get_all_accounts()
    if not data or "data" not in data:
        return 0.0
    for account in data["data"]:
        if account.get("currency") == "USD":
            return float(account.get("balance", {}).get("amount", 0))
    return 0.0

# --------------------------
# Flask endpoints
# --------------------------
@app.route("/test-balance")
def test_balance():
    balance = get_usd_balance()
    return jsonify({"USD_Balance": balance})

@app.route("/")
def index():
    return "Nija AI Bot Web Service Running"

# --------------------------
# Run locally if needed
# --------------------------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 10000)))
