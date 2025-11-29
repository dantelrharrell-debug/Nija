# web/wsgi.py
from flask import Flask, jsonify
import importlib

def create_app():
    app = Flask(__name__)

    @app.route("/")
    def index():
        return "Nija App — healthy"

    @app.route("/healthz")
    def healthz():
        # very small, non-blocking diagnostic
        return jsonify({"status": "ok"}), 200

    return app

app = create_app()
