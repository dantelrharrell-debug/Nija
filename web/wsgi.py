"""
web/wsgi.py - Flask app (exposes `app` for gunicorn)
Health endpoint uses lazy import of nija_client.test_coinbase_connection
"""
from flask import Flask, jsonify

def create_app():
    app = Flask(__name__)

    @app.route("/")
    def index():
        return "Nija App — healthy"

    @app.route("/healthz")
    def healthz():
        try:
            # lazy import
            import nija_client as nc
            test_fn = getattr(nc, "test_coinbase_connection", None)
            if callable(test_fn):
                ok = bool(test_fn())
            else:
                ok = False
            return jsonify({
                "status": "ok",
                "coinbase_test_ok": ok,
            }), 200
        except Exception as e:
            # return info but don't let worker crash
            return jsonify({
                "status": "ok",
                "coinbase_test_ok": False,
                "error": str(e)
            }), 200

    return app

app = create_app()
