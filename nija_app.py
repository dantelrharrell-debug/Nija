# nija_app.py
from flask import Flask, request, jsonify
from nija_client import CoinbaseClient

app = Flask(__name__)
client = CoinbaseClient()

# -------------------------
# Quick test trade endpoint
# -------------------------
@app.route("/test-buy", methods=["POST"])
def test_buy():
    """
    Trigger a test buy (dry-run by default).
    JSON body:
    {
        "product_id": "BTC-USD",
        "usd_quote": 10,
        "dry_run": true  # optional, defaults to True if LIVE_TRADING != "1"
    }
    """
    try:
        data = request.get_json(force=True)
        product_id = data.get("product_id", "BTC-USD")
        usd_quote = float(data.get("usd_quote", 10))
        dry_run = data.get("dry_run", None)  # None will auto-use LIVE_TRADING setting

        resp = client.place_market_buy_by_quote(product_id, usd_quote, dry_run=dry_run)
        return jsonify({"success": True, "result": resp})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
