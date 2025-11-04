# nija_app.py
from flask import Flask, jsonify
import time, hmac, hashlib, base64, requests, os, threading

app = Flask(__name__)

# --------------------------
# Coinbase API credentials
# --------------------------
API_KEY = os.getenv("COINBASE_API_KEY")
API_SECRET = os.getenv("COINBASE_API_SECRET")
API_PASSPHRASE = os.getenv("COINBASE_API_PASSPHRASE")
API_BASE = os.getenv("COINBASE_API_BASE", "https://api.coinbase.com")

# --------------------------
# Nija Bot Settings
# --------------------------
PAIRS = ["BTC-USD", "ETH-USD"]      # Coins to trade
BASE_ALLOCATION_PERCENT = 5          # Allocation per trade (% of USD balance)
MAX_EXPOSURE = 0.5                   # Max % of account in open positions
TRADE_HISTORY = []                    # Logs past trades

# --------------------------
# Coinbase helpers
# --------------------------
def generate_signature(path, method="GET", body=""):
    ts = str(int(time.time()))
    prehash = ts + method.upper() + path + body
    sig = base64.b64encode(
        hmac.new(base64.b64decode(API_SECRET), prehash.encode(), hashlib.sha256).digest()
    ).decode()
    return ts, sig

def api_request(method, path, body_dict=None):
    body = "" if body_dict is None else json.dumps(body_dict)
    ts, sig = generate_signature(path, method, body)
    headers = {
        "CB-ACCESS-KEY": API_KEY,
        "CB-ACCESS-SIGN": sig,
        "CB-ACCESS-TIMESTAMP": ts,
        "CB-ACCESS-PASSPHRASE": API_PASSPHRASE,
        "CB-VERSION": "2025-11-02",
        "Content-Type": "application/json"
    }
    try:
        if method == "GET":
            r = requests.get(API_BASE + path, headers=headers, timeout=15)
        elif method == "POST":
            r = requests.post(API_BASE + path, headers=headers, data=body, timeout=15)
        else:
            return None
        r.raise_for_status()
        return r.json()
    except requests.exceptions.RequestException as e:
        print("API request failed:", e)
        return None

# --------------------------
# Account & Market functions
# --------------------------
def get_usd_balance():
    data = api_request("GET", "/v2/accounts")
    if not data or "data" not in data:
        return 0.0
    for account in data["data"]:
        if account.get("currency") == "USD":
            return float(account.get("balance", {}).get("amount", 0))
    return 0.0

def get_ticker_price(pair):
    data = api_request("GET", f"/v2/prices/{pair}/spot")
    if not data or "data" not in data:
        return None
    return float(data["data"]["amount"])

# --------------------------
# Trading functions
# --------------------------
def place_order(pair, side, usd_amount):
    price = get_ticker_price(pair)
    if not price:
        return None
    size = round(usd_amount / price, 8)
    body = {"type":"market","side":side,"product_id":pair,"size":str(size)}
    result = api_request("POST", "/v2/accounts/primary/orders", body)
    if result:
        print(f"Order placed: {side.upper()} {size} {pair} (~${usd_amount:.2f})")
    return {"price": price, "size": size} if result else None

def compute_dynamic_allocation(pair):
    usd_balance = get_usd_balance()
    alloc_percent = BASE_ALLOCATION_PERCENT
    return min(alloc_percent, 10)  # cap at 10%

def nija_ai_bot():
    print("🚀 Nija AI Bot started")
    while True:
        usd_balance = get_usd_balance()
        print(f"USD Balance: ${usd_balance:.2f}")

        total_exposure = sum([t.get("size",0)*get_ticker_price(t["pair"]) for t in TRADE_HISTORY])
        if usd_balance == 0 or total_exposure / usd_balance > MAX_EXPOSURE:
            print("Max exposure reached or zero balance. Waiting...")
            time.sleep(10)
            continue

        for pair in PAIRS:
            usd_amount = usd_balance * compute_dynamic_allocation(pair) / 100
            print(f"Trading {pair} with ${usd_amount:.2f}")
            place_order(pair, "buy", usd_amount)

        time.sleep(10)

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
# Start Nija Bot in background
# --------------------------
def start_bot_thread():
    bot_thread = threading.Thread(target=nija_ai_bot)
    bot_thread.daemon = True  # so it exits if Flask exits
    bot_thread.start()

# --------------------------
# Main
# --------------------------
if __name__ == "__main__":
    start_bot_thread()
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 10000)))
