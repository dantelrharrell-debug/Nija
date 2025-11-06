# nija_app.py
from flask import Flask, jsonify

app = Flask(__name__)

# --- Health check endpoint ---
@app.route("/", methods=["GET", "HEAD"])
def health_check():
    return jsonify({
        "status": "ok",
        "message": "Nija bot is alive"
    }), 200

# --- Example API endpoint ---
@app.route("/api/test", methods=["GET"])
def test_endpoint():
    return jsonify({
        "status": "ok",
        "message": "This is a test endpoint"
    }), 200

if __name__ == "__main__":
    # For local testing
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
