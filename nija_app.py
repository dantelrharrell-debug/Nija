from flask import Flask, jsonify
from nija_client import cdp_get

app = Flask(__name__)

@app.route("/")
def home():
    return "Nija Bot Live Debug Endpoint ✅"

@app.route("/debug_accounts")
def debug_accounts():
    result = cdp_get()
    return jsonify(result)

if __name__ == "__main__":
    app.run(debug=True)
