# web/__init__.py
import sys
import os

# Add the project root to sys.path so 'bot' can be imported
sys.path.append(os.path.dirname(os.path.dirname(__file__)))

from flask import Flask

# Import the bot script safely
try:
    from bot.live_bot_script import start_trading_loop
except ModuleNotFoundError:
    start_trading_loop = None

app = Flask(__name__)

@app.route("/")
def home():
    return "NIJA Trading Bot is Running!"

# Optional: start trading loop in background when Flask starts
if start_trading_loop:
    @app.before_first_request
    def start_bot():
        import threading
        threading.Thread(target=start_trading_loop, daemon=True).start()
