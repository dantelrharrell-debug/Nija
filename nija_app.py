# --------------------------
# Coinbase preflight check
# --------------------------
def preflight_check():
    missing = []
    for var in ["COINBASE_API_KEY", "COINBASE_API_SECRET", "COINBASE_API_PASSPHRASE"]:
        if not os.getenv(var):
            missing.append(var)
    if missing:
        raise RuntimeError(f"Missing Coinbase environment variables: {', '.join(missing)}")

    # Optional: test the API credentials with a minimal request
    ts = str(int(time.time()))
    path = "/v2/accounts"
    method = "GET"
    prehash = ts + method.upper() + path
    sig = base64.b64encode(
        hmac.new(base64.b64decode(os.getenv("COINBASE_API_SECRET")), prehash.encode(), hashlib.sha256).digest()
    ).decode()
    headers = {
        "CB-ACCESS-KEY": os.getenv("COINBASE_API_KEY"),
        "CB-ACCESS-SIGN": sig,
        "CB-ACCESS-TIMESTAMP": ts,
        "CB-ACCESS-PASSPHRASE": os.getenv("COINBASE_API_PASSPHRASE"),
        "CB-VERSION": "2025-11-02",
        "Content-Type": "application/json"
    }
    r = requests.get(os.getenv("COINBASE_API_BASE", "https://api.coinbase.com") + path, headers=headers)
    if r.status_code != 200:
        raise RuntimeError(f"Coinbase API preflight failed: {r.status_code} {r.text}")
    print("✅ Coinbase preflight check passed.")

# Run preflight before starting bot
preflight_check()
