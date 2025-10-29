# nija_live_snapshot.py
from flask import Flask, jsonify
from nija_client import check_live_status
import logging

app = Flask(__name__)
app.logger.setLevel(logging.INFO)

@app.route("/health")
def health():
    live = False
    try:
        live = check_live_status()
    except Exception as e:
        app.logger.exception("Health check raised: %s", e)
    status = "alive"
    trading = "live" if live else "not live"
    return jsonify({"status": status, "trading": trading}), 200

if __name__ == "__main__":
    import os
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
