from flask import Flask
from nija_client import CoinbaseClient  # from coinbase-advanced

import os

app = Flask(__name__)

# Example: load API keys from .env
API_KEY = os.getenv("COINBASE_API_KEY")
API_SECRET = os.getenv("COINBASE_API_SECRET")
API_PASSPHRASE = os.getenv("COINBASE_API_PASSPHRASE")

client = CoinbaseClient(api_key=API_KEY, api_secret=API_SECRET, passphrase=API_PASSPHRASE)

@app.route("/")
def home():
    return "✅ Nija bot is running!"

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 5000)))
