# nija_app.py
# IMPORTANT: import startup_env BEFORE creating/instantiating any Coinbase client
import startup_env   # MUST run first

import os
from flask import Flask, jsonify
from nija_client import NijaCoinbaseClient  # ensure this module does NOT create the client at import-time

app = Flask(__name__)

# Create the client now that startup_env has validated/written envs
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
