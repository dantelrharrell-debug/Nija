# app.py
import os
import logging
from flask import Flask, jsonify
from functools import lru_cache

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
logger = logging.getLogger("nija_web")

app = Flask(__name__)

# Reuse the same client factory logic (or import from a shared utils module)
def get_coinbase_client():
    # minimal fallback: try likely imports
    candidates = [
        ("coinbase_advanced.client", "AdvancedClient"),
        ("coinbase_advanced.client", "Client"),
        ("coinbase_advanced_py.client", "AdvancedClient"),
        ("coinbase_advanced_py.client", "Client"),
    ]
    pem = os.environ.get("COINBASE_PEM_CONTENT")
    org = os.environ.get("COINBASE_ORG_ID")
    for module_name, class_name in candidates:
        try:
            mod = __import__(module_name, fromlist=[class_name])
            ClientClass = getattr(mod, class_name)
            try:
                return ClientClass(pem=pem, org_id=org)
            except TypeError:
                try:
                    return ClientClass(pem)
                except Exception:
                    return ClientClass()
        except Exception:
            continue
    # Mock fallback
    class MockClient:
        def get_accounts(self):
            return [{"id": "mock-1", "currency": "USD", "balance": "1000.00"}]
    logger.warning("Using MockClient for Coinbase")
    return MockClient()

@lru_cache(maxsize=1)
def _client():
    return get_coinbase_client()

@app.route("/")
def index():
    return "NIJA Bot Web - healthy"

@app.route("/status")
def status():
    return jsonify({
        "status": "ok",
        "env": os.environ.get("RAILWAY_ENVIRONMENT", "unknown")
    })

@app.route("/funded")
def funded():
    """
    Returns the balances for the funded accounts (simple).
    """
    client = _client()
    try:
        accounts = client.get_accounts()
    except Exception as e:
        logger.exception("Error getting accounts: %s", e)
        return jsonify({"error": "failed to fetch accounts"}), 500

    # normalize accounts to list of {id, currency, balance}
    resp = []
    for a in accounts:
        # accept either dict-like or objects with attrs
        try:
            if isinstance(a, dict):
                resp.append({
                    "id": a.get("id"),
                    "currency": a.get("currency"),
                    "balance": a.get("balance")
                })
            else:
                resp.append({
                    "id": getattr(a, "id", None),
                    "currency": getattr(a, "currency", None),
                    "balance": getattr(a, "balance", None)
                })
        except Exception:
            continue

    return jsonify({"accounts": resp})

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
