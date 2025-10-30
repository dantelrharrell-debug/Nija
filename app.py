from nija_client import run_trading_loop
from flask import Flask

app = Flask(__name__)

@app.route("/")
def index():
    return "NIJA Trading Bot is LIVE!"

# Start trading in background
import threading
threading.Thread(target=run_trading_loop, daemon=True).start()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))
