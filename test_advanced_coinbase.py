# test_advanced_coinbase.py  (put in project root)
import os, time, jwt, requests
BASE = os.getenv("COINBASE_ADVANCED_BASE", "https://api.cdp.coinbase.com")
COINBASE_ISS = os.getenv("COINBASE_ISS", "")
COINBASE_PEM_CONTENT = os.getenv("COINBASE_PEM_CONTENT", "").replace("\\n", "\n")

def run_tests():
    print("Base:", BASE)
    if not COINBASE_ISS or not COINBASE_PEM_CONTENT:
        print("Missing COINBASE_ISS or COINBASE_PEM_CONTENT")
        return
    ts = int(time.time())
    payload = {"iss": COINBASE_ISS, "iat": ts, "exp": ts + 300}
    try:
        token = jwt.encode(payload, COINBASE_PEM_CONTENT, algorithm="ES256")
        if isinstance(token, bytes):
            token = token.decode("utf-8")
    except Exception as e:
        print("JWT generation failed:", e)
        return
    headers = {"Authorization": f"Bearer {token}"}
    endpoints = ["/accounts", "/v2/accounts", "/v2/brokerage/accounts", "/api/v3/trading/accounts", "/api/v3/portfolios"]
    for ep in endpoints:
        url = BASE.rstrip("/") + ep
        try:
            r = requests.get(url, headers=headers, timeout=8)
            print(ep, "→", r.status_code, r.text[:400])
        except Exception as e:
            print(ep, "request failed:", e)

if __name__ == "__main__":
    run_tests()
