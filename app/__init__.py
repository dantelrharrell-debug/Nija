from flask import Flask
from .routes import register_routes
from .config import configure_logging
from .coinbase_client import start_trading_thread, Client


def create_app():
    app = Flask(__name__)

    # Setup logging
    configure_logging(app)

    # Register routes
    register_routes(app)

    # Start live trading thread safely
    if Client is not None:
        start_trading_thread()
    else:
        app.logger.warning("Skipping trading thread: Client not available")

    return app
