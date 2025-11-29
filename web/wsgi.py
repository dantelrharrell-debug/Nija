import logging
from web import create_app  # your Flask app factory

# Create Flask app
app = create_app()

# =========================
# Optional bot startup
# =========================
try:
    from app.nija_client import start_trading_loop
    start_trading_loop()  # only runs if module exists
except ModuleNotFoundError:
    logging.warning("nija_client not found — skipping bot startup.")
except FileNotFoundError:
    logging.warning("check_funded.py missing — skipping bot startup.")
except Exception as e:
    logging.error(f"Failed to start trading bot: {e}")

# Gunicorn uses this
application = app
