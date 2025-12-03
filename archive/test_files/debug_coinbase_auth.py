# debug_coinbase_auth.py
import os, time, hmac, hashlib, base64, requests, json

API_KEY = os.getenv("COINBASE_API_KEY")
API_SECRET = os.getenv("COINBASE_API_SECRET")
API_PASSPHRASE = os.getenv("COINBASE_API_PASSPHRASE") or ""
API_BASE = os.getenv("COINBASE_API_BASE", "https://api.coinbase.com")
API_VERSION = os.getenv("COINBASE_API_VERSION", "2025-11-02")

def sig_b64_method(ts, method, path, body=""):
    prehash = ts + method.upper() + path + body
    try:
        secret_bytes = base64.b64decode(API_SECRET)
    except Exception:
        secret_bytes = API_SECRET.encode()
    sig = base64.b64encode(hmac.new(secret_bytes, prehash.encode(), hashlib.sha256).digest()).decode()
    return sig

def sig_hex_method(ts, method, path, body=""):
    prehash = ts + method.upper() + path + body
    return hmac.new(API_SECRET.encode(), prehash.encode(), hashlib.sha256).hexdigest()

def call(path, method="GET", sig_method="b64"):
    ts = str(int(time.time()))
    if sig_method == "b64":
        sig = sig_b64_method(ts, method, path, "")
    else:
        sig = sig_hex_method(ts, method, path, "")
    headers = {
        "CB-ACCESS-KEY": API_KEY,
        "CB-ACCESS-SIGN": sig,
        "CB-ACCESS-TIMESTAMP": ts,
        "CB-VERSION": API_VERSION,
        "Content-Type": "application/json",
    }
    if API_PASSPHRASE:
        headers["CB-ACCESS-PASSPHRASE"] = API_PASSPHRASE

    print("\n=== Attempt:", sig_method, "===\nHeaders:")
    for k,v in headers.items():
        if k in ("CB-ACCESS-KEY",):
            print(k, ":", (v[:8] + "..." if v else v))
        elif k in ("CB-ACCESS-SIGN",):
            print(k, ":", v[:12] + "...")
        else:
            print(k, ":", v)
    try:
        r = requests.get(API_BASE + path, headers=headers, timeout=10)
        print("Status:", r.status_code)
        print("Response body preview:", r.text[:1000])
    except Exception as e:
        print("Request error:", e)

if __name__ == "__main__":
    if not API_KEY or not API_SECRET:
        print("Set COINBASE_API_KEY and COINBASE_API_SECRET in env before running.")
        raise SystemExit(1)
    print("Local unix ts:", int(time.time()))
    # test /time first
    try:
        r = requests.get(API_BASE + "/time", timeout=6)
        print("/time status", r.status_code, "body:", r.text[:400])
    except Exception as e:
        print("time request failed:", e)
    call("/v2/accounts", "GET", "b64")
    call("/v2/accounts", "GET", "hex")
