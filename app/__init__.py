# app/__init__.py
from flask import Flask

def create_app():
    """
    Minimal Flask factory. Add config/env wiring here as needed.
    """
    app = Flask(__name__)
    # Example: load from env or config file if present
    # app.config.from_prefixed_env()

    @app.route("/healthz")
    def health():
        return "OK", 200

    return app

# create top-level `app` variable so gunicorn can import `app.wsgi:app`
app = create_app()
