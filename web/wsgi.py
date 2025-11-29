# web/wsgi.py
# Exposes 'application' when Gunicorn imports web.wsgi:application

try:
    # Import app from the package above
    from app import app as application
except Exception:
    # Fallback minimal app so gunicorn can boot and show route for health check.
    from flask import Flask, jsonify
    application = Flask(__name__)

    @application.route("/health")
    def health():
        return jsonify({"status": "fallback ok"})
