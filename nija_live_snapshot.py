# nija_live_snapshot.py

from flask import Flask, jsonify
from nija_client import check_live_status

app = Flask(__name__)

@app.route("/health")
def health():
    live = check_live_status()
    status = "alive"
    trading = "live" if live else "not live"
    return jsonify({"status": status, "trading": trading}), 200

if __name__ == "__main__":
    import os
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
