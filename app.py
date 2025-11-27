from flask import Flask
import logging

app = Flask(__name__)

# Optional: import coinbase safely
try:
    from coinbase_advanced.client import Client
    COINBASE_AVAILABLE = True
except ModuleNotFoundError:
    logging.error("Coinbase module not found. Bot will run in limited mode.")
    COINBASE_AVAILABLE = False

@app.route("/")
def index():
    return "Nija Bot Running! Coinbase module loaded: {}".format(COINBASE_AVAILABLE)

if __name__ == "__main__":
    # Only used if running directly
    app.run(host="0.0.0.0", port=5000)
