from flask import Flask
from .routes import register_routes
from .config import configure_logging
from .coinbase_client import start_trading_thread

def create_app():
    app = Flask(__name__)
    
    # Setup logging
    configure_logging(app)

    # Register routes
    register_routes(app)

    # Start live trading in background
    start_trading_thread()
    
    return app
