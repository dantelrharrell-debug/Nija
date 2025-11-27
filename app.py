import logging
from flask import Flask

app = Flask(__name__)

try:
    from coinbase_advanced.client import Client
    COINBASE_AVAILABLE = True
except Exception as e:
    logging.error(f"Coinbase module failed: {e}")
    COINBASE_AVAILABLE = False

@app.route("/")
def index():
    return f"Nija Bot Running! Coinbase module loaded: {COINBASE_AVAILABLE}"

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
