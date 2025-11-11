# test_hmac_coinbase.py  (put in project root)
import os, time, hmac, hashlib, requests
BASE = os.getenv("COINBASE_API_BASE", "https://api.coinbase.com")
API_KEY = os.getenv("COINBASE_API_KEY", "")
API_SECRET = os.getenv("COINBASE_API_SECRET", "")

def run_hmac():
    if not API_KEY or not API_SECRET:
        print("Missing HMAC keys")
        return
    ts = str(int(time.time()))
    method = "GET"
    path = "/v2/accounts"
    message = ts + method + path + ""
    sig = hmac.new(API_SECRET.encode(), message.encode(), hashlib.sha256).hexdigest()
    headers = {
        "CB-ACCESS-KEY": API_KEY,
        "CB-ACCESS-SIGN": sig,
        "CB-ACCESS-TIMESTAMP": ts,
        "CB-VERSION": "2025-11-11",
    }
    url = BASE.rstrip("/") + path
    print("URL:", url)
    r = requests.get(url, headers=headers, timeout=8)
    print("Status:", r.status_code)
    print("Body:", r.text[:800])

if __name__ == "__main__":
    run_hmac()
