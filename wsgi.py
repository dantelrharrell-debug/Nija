# wsgi.py (or app.py)
from flask import Flask, jsonify
import os

app = Flask(__name__)

# NIJA bot health-check endpoint
@app.route("/__nija_probe", methods=["GET"])
def nija_probe():
    return jsonify({
        "status": "ok",
        "message": "NIJA bot is live",
    }), 200

# Root route
@app.route("/")
def root():
    return "Hello World", 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
