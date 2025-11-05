from flask import Flask, jsonify
from nija_client import CoinbaseClient

app = Flask(__name__)

@app.route("/status")
def status():
    try:
        client = CoinbaseClient()
        account = client.get_funded_account()
        if not account:
            return jsonify({"status": "no funded account"}), 200
        return jsonify({"status": "ok", "balance": account.get("balance")}), 200
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
