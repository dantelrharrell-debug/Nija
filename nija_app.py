from flask import Flask, jsonify
from nija_client import get_usd_spot_balance, get_all_accounts

app = Flask(__name__)

@app.route("/balance")
def balance():
    try:
        usd = get_usd_spot_balance()
        return jsonify({"usd_balance": usd})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/accounts")
def accounts():
    try:
        data = get_all_accounts()
        return jsonify({"accounts": data})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 5000)))
