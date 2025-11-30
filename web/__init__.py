# web/__init__.py

import sys
import os

# Add root folder to Python path so 'bot' can be imported
sys.path.append(os.path.dirname(os.path.dirname(__file__)))

from bot.live_bot_script import start_trading_loop
from flask import Flask

app = Flask(__name__)
from flask import Flask
from bot.live_bot_script import start_trading_loop

app = Flask(__name__)

@app.route("/")
def index():
    return "Nija Bot Running!", 200

# Start the trading loop
start_trading_loop()
