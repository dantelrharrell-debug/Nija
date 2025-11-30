# wsgi.py
import os
import traceback
from flask import Flask, jsonify

app = Flask(__name__)

@app.route("/")
def root():
    return "Hello World", 200

@app.route("/__nija_probe", methods=["GET"])
def nija_probe():
    return jsonify({"status": "ok", "message": "NIJA bot is live"}), 200

# Optional: accounts endpoint (requires coinbase-advanced-py and env vars)
@app.route("/accounts", methods=["GET"])
def accounts_route():
    try:
        from coinbase.rest import RESTClient
    except Exception:
        return jsonify({"ok": False, "error": "coinbase-advanced-py not installed"}), 500

    try:
        client = None
        api_key = os.environ.get("COINBASE_API_KEY")
        api_secret = os.environ.get("COINBASE_API_SECRET")
        key_file = os.environ.get("COINBASE_KEY_FILE")
        if api_key and api_secret:
            client = RESTClient(api_key=api_key, api_secret=api_secret)
        elif key_file:
            client = RESTClient(key_file=key_file)
        else:
            client = RESTClient()  # let SDK fallback to env or default behavior

        accounts = client.get_accounts()
        # best-effort convert to JSON-serializable list
        out = []
        iterable = getattr(accounts, "accounts", None) or (accounts if isinstance(accounts, (list,tuple)) else getattr(accounts, "data", []))
        for a in iterable:
            acct_id = getattr(a, "id", None) or (a.get("id") if isinstance(a, dict) else None)
            currency = getattr(a, "currency", None) or (a.get("currency") if isinstance(a, dict) else None)
            avail = None
            av = getattr(a, "available_balance", None) or (a.get("available_balance") if isinstance(a, dict) else None)
            if isinstance(av, dict):
                avail = av.get("value")
            else:
                avail = getattr(av, "value", None) if av is not None else None

            out.append({"id": acct_id, "currency": currency, "available_balance": avail})
        return jsonify({"ok": True, "count": len(out), "accounts": out}), 200
    except Exception as e:
        return jsonify({"ok": False, "error": str(e), "trace": traceback.format_exc()}), 500

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
