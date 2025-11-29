# web/wsgi.py
import sys
import threading

# Ensure the parent directory is in sys.path
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

# Import your Flask app
from app.nija_client import app  # Flask instance

# Import your bot startup function
from app.nija_client.start_bot_main import start_trading_loop

# Run trading loop in a separate thread so Flask/Gunicorn can serve requests
bot_thread = threading.Thread(target=start_trading_loop, daemon=True)
bot_thread.start()

# Gunicorn expects this variable
application = app

if __name__ == "__main__":
    # Useful for local testing
    app.run(host="0.0.0.0", port=8080)
