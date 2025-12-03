import time
import hmac
import hashlib
import base64
import requests
import json

# --------------------------
# Coinbase API credentials (fill in your keys)
# --------------------------
API_KEY = "your_api_key_here"
API_SECRET = "your_base64_secret_here"
API_PASSPHRASE = "your_passphrase_here"
API_BASE = "https://api.coinbase.com"

# --------------------------
# Bot Settings
# --------------------------
PAIRS = ["BTC-USD", "ETH-USD"]  # coins to trade
BASE_ALLOCATION_PERCENT = 5      # default allocation per trade (% of USD balance)
MAX_DAILY_LOSS = 0.1             # max loss per day (10% of account)
MAX_EXPOSURE = 0.5               # max % of account in open positions

TRADE_HISTORY = []               # stores trade results for dynamic sizing

# --------------------------
# Coinbase API Helpers
# --------------------------
def generate_signature(path, method="GET", body=""):
    ts = str(int(time.time()))
    prehash = ts + method.upper() + path + body
    sig = base64.b64encode(
        hmac.new(base64.b64decode(API_SECRET), prehash.encode(), hashlib.sha256).digest()
    ).decode()
    return ts, sig

def api_request(method, path, body_dict=None):
    body = json.dumps(body_dict) if body_dict else ""
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
# Account & Market
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

def get_volatility(pair, lookback=10):
    prices = []
    for _ in range(lookback):
        price = get_ticker_price(pair)
        if price:
            prices.append(price)
        time.sleep(1)
    if not prices:
        return 0.0
    return (max(prices) - min(prices)) / min(prices) * 100

# --------------------------
# Trading Functions
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

def manage_trade(entry_price, pair, trail_percent, stop_loss_percent):
    peak_price = entry_price
    print(f"Managing {pair} trade at entry {entry_price}")
    while True:
        price = get_ticker_price(pair)
        if not price:
            time.sleep(5)
            continue
        peak_price = max(peak_price, price)
        trailing_stop = peak_price * (1 - trail_percent / 100)
        stop_loss = entry_price * (1 - stop_loss_percent / 100)
        if price <= trailing_stop or price <= stop_loss:
            print(f"Exiting trade: Current {price:.2f}, Trailing stop {trailing_stop:.2f}, Stop {stop_loss:.2f}")
            place_order(pair, "sell", get_usd_balance())
            TRADE_HISTORY.append({"pair": pair, "entry": entry_price, "exit": price})
            break
        time.sleep(5)

def compute_dynamic_allocation(pair):
    usd_balance = get_usd_balance()
    vol = get_volatility(pair)
    perf_factor = 1.0
    # adjust based on previous trades
    recent_trades = [t for t in TRADE_HISTORY if t["pair"] == pair][-5:]
    if recent_trades:
        wins = sum(1 for t in recent_trades if t["exit"] > t["entry"])
        perf_factor += (wins - (5 - wins)) * 0.05  # +-5% per win/loss
    alloc_percent = BASE_ALLOCATION_PERCENT * max(0.5, 1 - vol / 50) * perf_factor
    return min(alloc_percent, 10)  # cap at 10%

# --------------------------
# Nija AI Smart Bot
# --------------------------
def nija_ai_bot():
    while True:
        usd_balance = get_usd_balance()
        total_exposure = sum([t.get("size",0)*get_ticker_price(t["pair"]) for t in TRADE_HISTORY])
        if total_exposure / usd_balance > MAX_EXPOSURE:
            print("Max exposure reached, waiting...")
            time.sleep(10)
            continue

        print(f"USD Balance: ${usd_balance:.2f}")
        for pair in PAIRS:
            alloc_percent = compute_dynamic_allocation(pair)
            usd_amount = usd_balance * alloc_percent / 100
            print(f"Trading {pair} with allocation ${usd_amount:.2f}")
            order = place_order(pair, "buy", usd_amount)
            if order:
                # adaptive trailing based on volatility
                vol = get_volatility(pair)
                trail = max(1, vol / 2)
                stop = max(1, vol / 1.5)
                manage_trade(order["price"], pair, trail, stop)
        print("Cycle complete. Waiting 10 seconds.\n")
        time.sleep(10)

# --------------------------
# Run Bot
# --------------------------
if __name__ == "__main__":
    nija_ai_bot()
