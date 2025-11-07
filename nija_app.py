# nija_app.py
import os
from flask import Flask, jsonify
from nija_client import NijaCoinbaseClient

app = Flask(__name__)
client = NijaCoinbaseClient()

@app.route("/accounts")
def accounts():
    try:
        data = client.get_accounts()
        return jsonify(data)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 5000)))
