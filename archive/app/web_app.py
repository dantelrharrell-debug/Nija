# app/web_app.py
from flask import Flask, jsonify

def create_app():
    app = Flask(__name__)
    # configure app from env or config file if needed
    @app.route("/")
    def index():
        return jsonify({"status": "nija bot running"}), 200

    # health endpoint for Railway or uptime checks
    @app.route("/_health")
    def health():
        return "ok", 200

    return app

# provide a module-level app (helpful if someone expects `app` name)
app = create_app()
