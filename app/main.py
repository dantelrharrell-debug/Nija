from flask import Flask
import os
from app.nija_client import CoinbaseClient

app = Flask(__name__)

# Initialize Coinbase client
client = CoinbaseClient()

@app.route("/")
def index():
    return "NIJA Bot is online"

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
