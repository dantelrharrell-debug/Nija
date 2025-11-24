from flask import Flask
import logging

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)

# --- Health check endpoint ---
@app.route("/health", methods=["GET"])
def health():
    return "OK", 200

# --- Register TradingView blueprint ---
try:
    from tradingview_webhook import tradingview_blueprint
    app.register_blueprint(tradingview_blueprint, url_prefix="/tv")
    logging.info("✅ TradingView blueprint registered")
except Exception as e:
    logging.warning(f"⚠️ Could not register TradingView blueprint: {e}")
