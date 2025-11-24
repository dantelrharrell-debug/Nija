# src/wsgi.py
from flask import Flask
import logging

# Attempt to import canonical blueprint; fallback to top-level locations
try:
    from src.trading.tradingview_webhook import bp as tv_bp
except Exception:
    try:
        from trading.tradingview_webhook import bp as tv_bp
    except Exception:
        # If we can't import, create a dummy blueprint so server still starts
        tv_bp = None

app = Flask(__name__)
if tv_bp:
    app.register_blueprint(tv_bp, url_prefix="/tv")

@app.route("/health", methods=["GET"])
def health():
    return "OK", 200

if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG)
    app.run(host="0.0.0.0", port=5000)
