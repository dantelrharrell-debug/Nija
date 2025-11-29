from flask import Flask
from bot.live_bot_script import start_trading_loop

app = Flask(__name__)

@app.route("/")
def index():
    return "Nija Bot Running!", 200

# Start the trading loop
start_trading_loop()
