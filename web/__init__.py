# web/__init__.py

import sys
import os

# Add root directory to path so 'bot' can be imported
sys.path.append(os.path.dirname(os.path.dirname(__file__)))

from flask import Flask
from bot.live_bot_script import start_trading_loop

app = Flask(__name__)

@app.route("/")
def home():
    return "NIJA Trading Bot is Running!"

# Optional: start trading loop in background
# Uncomment if you want it to auto-start with Flask
# import threading
# threading.Thread(target=start_trading_loop, daemon=True).start()
