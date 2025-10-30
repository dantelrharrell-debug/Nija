from flask import Flask
from nija_client import start_trading

app = Flask(__name__)

@app.route("/")
def index():
    return "Nija Trading Bot online!"

# Start trading automatically when the app runs
start_trading()
