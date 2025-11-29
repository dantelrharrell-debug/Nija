from flask import Flask
import threading

app = Flask(__name__)

def init_bot():
    print(f"Initializing bot in thread {threading.get_ident()} ...")
    # Place your bot setup here (Coinbase connection, background threads, etc.)
    # Example:
    # bot = NijaBot()
    # bot.start()

# Flask hook: runs before the first HTTP request
@app.before_first_request
def before_first_request():
    init_bot()
