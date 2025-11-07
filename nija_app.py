# nija_app.py
from flask import Flask, request, jsonify
from nija_client import CoinbaseClient

# ---- LIVE FLASK APP ----
app = Flask(__name__)
client = CoinbaseClient()  # Live trading client

@app.route("/accounts", methods=["GET"])
def get_accounts():
    try:
        accounts = client.get_accounts()
        return jsonify({"status": "success", "accounts": accounts})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route("/trade", methods=["POST"])
def trade():
    """
    Place a LIVE trade.
    JSON payload example:
    {
        "side": "buy",
        "product_id": "BTC-USD",
        "size": "0.001"
    }
    """
    try:
        data = request.get_json()
        side = data.get("side")
        product_id = data.get("product_id")
        size = data.get("size")

        if not all([side, product_id, size]):
            return jsonify({"status": "error", "message": "Missing parameters"}), 400

        order = client.place_order(side, product_id, size)
        return jsonify({"status": "success", "order": order})

    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

# ---- RUN ONLY IF LOCAL, NOT RENDER ----
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
