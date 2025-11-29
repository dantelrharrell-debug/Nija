from flask import Flask

app = Flask(__name__)

# Import the trading loop starter
from app.nija_trading_loop import start_trading_loop

@app.before_first_request
def start_loop():
    # Start your trading loop when the first request hits
    start_trading_loop()
