# check_accounts.py
import os, time, jwt, requests, json, sys

BASE = os.getenv("COINBASE_API_BASE", "https://api.coinbase.com")
API_KEY = os.getenv("COINBASE_API_KEY")
# We'll read the PEM from the file you wrote earlier (safer)
PEM_PATH = os.getenv("COINBASE_PEM_PATH", "coinbase_private.pem")

if not API_KEY:
    print("❌ Missing COINBASE_API_KEY in env.")
    sys.exit(1)

if not os.path.isfile(PEM_PATH):
    print(f"❌ PEM file not found at {PEM_PATH}. Create it from your env with: echo \"$COINBASE_API_SECRET\" | sed 's/\\\\n/\\n/g' > {PEM_PATH}")
    sys.exit(1)

with open(PEM_PATH, "r") as f:
    API_SECRET = f.read()

def make_jwt():
    now = int(time.time())
    payload = {
        "iat": now,
        "exp": now + 120,   # short-lived
        "sub": API_KEY
    }
    try:
        token = jwt.encode(payload, API_SECRET, algorithm="ES256")
        return token
    except Exception as e:
        print("❌ JWT encode error:", e)
        sys.exit(1)

def api_get(path):
    token = make_jwt()
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }
    url = BASE.rstrip("/") + path
    try:
        r = requests.get(url, headers=headers, timeout=15)
        return r
    except Exception as e:
        print("❌ Request error:", e)
        sys.exit(1)

def pretty_print_accounts(resp):
    try:
        data = resp.json()
    except Exception:
        print("❌ Response not valid JSON:", resp.status_code, resp.text[:800])
        return

    # Coinbase returns {"data": [ ... ]}
    accounts = data.get("data") or data.get("accounts") or data
    if not isinstance(accounts, list):
        print("❌ Unexpected accounts format:", json.dumps(data)[:800])
        return

    print("🔹 Accounts visible to this API key:")
    funded = []
    for acct in accounts:
        curr = acct.get("currency") or acct.get("currency_code") or acct.get("currency_id")
        bal = acct.get("balance", {}).get("amount") if isinstance(acct.get("balance"), dict) else acct.get("balance")
        bal = bal or "0"
        acct_type = acct.get("type", acct.get("account_type", "unknown"))
        print(f"  • {curr}: {bal}  (type: {acct_type})")
        try:
            if float(bal) > 0:
                funded.append((curr, bal, acct_type))
        except Exception:
            pass

    if funded:
        print("\n✅ Funded accounts found:")
        for f in funded:
            print(f"  → {f[0]} : {f[1]} (type: {f[2]})")
    else:
        print("\n⚠️ No funded accounts visible to this API key (all balances 0 or inaccessible).")

def main():
    print("🔎 Testing GET /v2/accounts")
    resp = api_get("/v2/accounts")
    print("HTTP status:", resp.status_code)
    if resp.ok:
        pretty_print_accounts(resp)
    else:
        print("❌ API returned error:", resp.status_code, resp.text[:800])
        # Try /accounts (some endpoints differ)
        if resp.status_code in (401, 404):
            print("\nℹ️ Also try checking whether the API key is Advanced vs Base and that it has 'view' and 'trade' permissions.")
    return

if __name__ == "__main__":
    main()
