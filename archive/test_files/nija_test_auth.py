# nija_test_auth.py
# Place in repo root and run: python3 nija_test_auth.py
import os, time, hmac, hashlib, json, sys
from urllib.parse import urljoin, urlparse
import requests

BASE = os.getenv("COINBASE_API_BASE", "https://api.cdp.coinbase.com")
API_KEY = os.getenv("COINBASE_API_KEY")
API_SECRET = os.getenv("COINBASE_API_SECRET")
API_PASSPHRASE = os.getenv("COINBASE_API_PASSPHRASE")
JWT = os.getenv("COINBASE_JWT")  # optional fallback
TIMEOUT = 10.0

candidate_paths = [
    "/platform/v2/evm/accounts",
    "/platform/v2/accounts",
    "/v2/accounts",
]

def sign_hmac(timestamp, method, request_path, body=""):
    msg = timestamp + method.upper() + request_path + (body or "")
    sig = hmac.new(API_SECRET.encode(), msg.encode(), hashlib.sha256).hexdigest()
    return sig

def try_hmac(url, path):
    parsed = urlparse(url)
    request_path = parsed.path + ("?" + parsed.query if parsed.query else "")
    ts = str(int(time.time()))
    sig = sign_hmac(ts, "GET", request_path, "")
    headers = {
        "CB-ACCESS-KEY": API_KEY,
        "CB-ACCESS-SIGN": sig,
        "CB-ACCESS-TIMESTAMP": ts,
        "Accept": "application/json",
        "Content-Type": "application/json",
    }
    # set passphrase only if present and likely needed
    if API_PASSPHRASE:
        headers["CB-ACCESS-PASSPHRASE"] = API_PASSPHRASE
    print(f"\n[HMAC] GET {url}")
    try:
        r = requests.get(url, headers=headers, timeout=TIMEOUT)
        print(f"Status: {r.status_code}")
        try:
            print("Body:", json.dumps(r.json(), indent=2))
        except Exception:
            print("Body (raw):", r.text[:2000])
        return r
    except requests.exceptions.RequestException as e:
        print("Network error:", e)
        return None

def try_jwt(url):
    if not JWT:
        print("No COINBASE_JWT env var set; skipping JWT attempt.")
        return None
    headers = {
        "Authorization": f"Bearer {JWT}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }
    print(f"\n[JWT] GET {url}")
    try:
        r = requests.get(url, headers=headers, timeout=TIMEOUT)
        print(f"Status: {r.status_code}")
        try:
            print("Body:", json.dumps(r.json(), indent=2))
        except Exception:
            print("Body (raw):", r.text[:2000])
        return r
    except requests.exceptions.RequestException as e:
        print("Network error:", e)
        return None

def main():
    if not API_KEY or not API_SECRET:
        print("ERROR: COINBASE_API_KEY and COINBASE_API_SECRET must be set in env. Aborting.")
        sys.exit(1)
    print("Using COINBASE_API_BASE =", BASE)
    for path in candidate_paths:
        url = urljoin(BASE.rstrip("/") + "/", path.lstrip("/"))
        print("\n--- Trying endpoint:", path, "---")
        r = try_hmac(url, path)
        if r is None:
            continue
        if r.status_code == 200:
            print("[RESULT] HMAC succeeded. You are AUTHENTICATED and can list accounts.")
            return
        if r.status_code in (401, 403):
            print(f"[RESULT] HMAC returned {r.status_code}. Authentication/permission issue.")
            if JWT:
                # try JWT fallback
                r2 = try_jwt(url)
                if r2 is None:
                    continue
                if r2.status_code == 200:
                    print("[RESULT] JWT succeeded. Use COINBASE_JWT in your container (and ensure code will use it).")
                    return
                else:
                    print("[RESULT] JWT also failed with status", r2.status_code)
            else:
                print("[HINT] If this is an Advanced/CDP key requiring JWT, set COINBASE_JWT (JWT generation tools exist in repo).")
            # continue trying next candidate path
        else:
            print("[INFO] Non-auth error or unexpected status:", r.status_code)
            # keep trying next candidate
    print("\nFINAL: All candidate endpoints tried and none returned a successful account listing.")
    print("Suggestions:")
    print("- Verify the API key has 'Accounts (read)' permission and is scoped to the correct organization.")
    print("- If this is Coinbase Advanced (CDP) and your key requires JWT, generate a JWT and set COINBASE_JWT.")
    print("- Ensure COINBASE_API_BASE matches the key type (CDP vs standard).")
    print("- Consider regenerating the API key with explicit account-read permission and update your env vars.")

if __name__ == '__main__':
    main()
