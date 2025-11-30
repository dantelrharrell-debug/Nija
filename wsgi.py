# wsgi.py  — simple probe endpoint, no background threads
import logging
from flask import Flask, jsonify
import traceback
import os

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
logger = logging.getLogger("nija-wsgi-probe")

app = Flask(__name__)

@app.route("/")
def index():
    return "NIJA TRADING BOT — up"

@app.route("/__nija_probe")
def probe():
    """Non-destructive probe: shows import status, env var presence, and (if possible) account list.
       DOES NOT echo any secret values."""
    resp = {"import_coinbase_advanced": False,
            "env": {"COINBASE_API_KEY": False, "COINBASE_API_SECRET": False},
            "client_instantiated": False,
            "accounts_summary": None,
            "errors": []}

    # env presence
    if os.environ.get("COINBASE_API_KEY"):
        resp["env"]["COINBASE_API_KEY"] = True
    if os.environ.get("COINBASE_API_SECRET"):
        resp["env"]["COINBASE_API_SECRET"] = True

    # try import
    try:
        from coinbase_advanced.client import Client  # noqa: F401
        resp["import_coinbase_advanced"] = True
    except Exception as e:
        err = f"import_error: {type(e).__name__}: {e}"
        logger.warning(err)
        resp["errors"].append(err)
        return jsonify(resp), 200

    # try to instantiate client but don't return secrets
    try:
        from coinbase_advanced.client import Client
        api_key = os.environ.get("COINBASE_API_KEY")
        api_secret = os.environ.get("COINBASE_API_SECRET")
        if not api_key or not api_secret:
            resp["errors"].append("missing_api_key_or_secret")
            return jsonify(resp), 200

        # best-effort normalize any literal \n sequences (non-destructive)
        if "\\n" in api_secret:
            api_secret = api_secret.replace("\\n", "\n")

        try:
            client = Client(api_key=api_key, api_secret=api_secret)
            resp["client_instantiated"] = True
        except Exception as e:
            resp["errors"].append(f"client_init_error: {type(e).__name__}: {e}")
            logger.warning(traceback.format_exc())
            return jsonify(resp), 200

        # try to list accounts; redact sensitive fields
        try:
            accounts = client.get_accounts()
            # build small summary (do NOT include account IDs or keys)
            summary = []
            if isinstance(accounts, (list, tuple)):
                for a in accounts:
                    # safe extraction for dict-like or attr-like objects
                    cur = None
                    bal = None
                    try:
                        if isinstance(a, dict):
                            cur = a.get("currency") or a.get("asset") or a.get("type")
                            bal = a.get("balance") or a.get("available") or a.get("amount")
                        else:
                            cur = getattr(a, "currency", None) or getattr(a, "asset", None) or getattr(a, "type", None)
                            bal = getattr(a, "balance", None) or getattr(a, "available", None)
                    except Exception:
                        cur = str(a)[:30]
                        bal = None
                    summary.append({"currency": cur, "balance": str(bal)})
            else:
                # not a list — show repr trimmed
                summary = str(accounts)[:800]
            resp["accounts_summary"] = summary
            return jsonify(resp), 200
        except Exception as e:
            resp["errors"].append(f"accounts_error: {type(e).__name__}: {e}")
            logger.warning(traceback.format_exc())
            return jsonify(resp), 200

    except Exception as e:
        resp["errors"].append(f"unexpected_probe_error: {type(e).__name__}: {e}")
        logger.warning(traceback.format_exc())
        return jsonify(resp), 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
