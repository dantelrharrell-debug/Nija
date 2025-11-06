# nija_app.py
from flask import Flask, jsonify
import os
import traceback

app = Flask(__name__)

# Lazy import so this file always starts even if coinbase keys are wrong
try:
    from nija_client import CoinbaseClient
except Exception as e:
    CoinbaseClient = None
    import_err = traceback.format_exc()
else:
    import_err = None

@app.route("/", methods=["GET", "HEAD"])
def index():
    return "N I J A — service up", 200

@app.route("/health", methods=["GET"])
def health():
    """
    Health endpoint returns:
    - ok: overall boolean
    - service: always 'nija'
    - coinbase: object with status and short payload (no secrets)
    - env: which env vars are present (no values printed)
    """
    res = {"ok": True, "service": "nija", "time": None, "coinbase": {}, "env": {}}
    from datetime import datetime
    res["time"] = datetime.utcnow().isoformat() + "Z"

    # environment presence (no values)
    keys_to_check = [
        "COINBASE_API_KEY",
        "COINBASE_API_SECRET",
        "COINBASE_API_PASSPHRASE",
        "COINBASE_API_BASE",
        "LIVE_TRADING"
    ]
    for k in keys_to_check:
        res["env"][k] = bool(os.getenv(k))

    # If nija_client import failed, include that info but still return 200
    if import_err:
        res["coinbase"] = {
            "ok": False,
            "status": None,
            "payload": "nija_client import error",
            "import_error": import_err.splitlines()[-1]
        }
        return jsonify(res), 200

    # Try to instantiate client and fetch accounts in a robust way
    try:
        client = CoinbaseClient()
    except Exception as e:
        res["coinbase"] = {
            "ok": False,
            "status": None,
            "payload": f"CoinbaseClient init error: {str(e)}"
        }
        return jsonify(res), 200

    try:
        accounts = client.get_accounts()
        # get_accounts returns None on unauthorized/404; or dict on success
        if accounts is None:
            res["coinbase"] = {"ok": False, "status": 401, "payload": "unauthorized or no accounts returned"}
        elif isinstance(accounts, dict) and "ok" in accounts:
            # client returned a structured result
            res["coinbase"] = accounts
            res["coinbase"]["ok"] = res["coinbase"].get("ok", True)
        else:
            res["coinbase"] = {"ok": True, "status": 200, "payload": "accounts fetched", "accounts_summary": summarize_accounts(accounts)}
    except Exception as e:
        res["coinbase"] = {"ok": False, "status": None, "payload": f"Error fetching accounts: {str(e)}"}
    return jsonify(res), 200

def summarize_accounts(accounts):
    """
    Produce a tiny summary of accounts object or JSON
    """
    try:
        if isinstance(accounts, dict):
            # often accounts JSON has 'data' key
            if "data" in accounts and isinstance(accounts["data"], list):
                return {"count": len(accounts["data"]), "first_keys": list(accounts["data"][0].keys())[:6] if accounts["data"] else []}
            return {"keys": list(accounts.keys())[:10]}
        if isinstance(accounts, list):
            return {"count": len(accounts)}
    except Exception:
        pass
    return {"type": type(accounts).__name__}

if __name__ == "__main__":
    # for local dev
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 10000)))
