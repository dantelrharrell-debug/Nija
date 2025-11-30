from flask import Flask
from .routes import register_routes
from .config import configure_logging

def create_app():
    app = Flask(__name__)
    
    # Setup logging
    configure_logging(app)

    # Register routes
    register_routes(app)
    
    return app
