# /app/web/wsgi.py
from flask import Flask, jsonify

def create_app():
    app = Flask(__name__)

    @app.route("/")
    def index():
        return "Nija App — healthy"

    @app.route("/healthz")
    def healthz():
        # Keep healthz tiny and import-safe
        return jsonify({"status": "ok"}), 200

    return app

# Expose app for gunicorn: web.wsgi:app
app = create_app()
