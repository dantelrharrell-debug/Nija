"""
web/wsgi.py - Flask application factory with lazy nija_client imports for health checks.
Expose `app` variable for gunicorn:  e.g. gunicorn -c gunicorn.conf.py web.wsgi:app
"""

from flask import Flask, jsonify

def create_app():
    app = Flask(__name__)

    @app.route("/")
    def index():
        return "Nija App — healthy"

    @app.route("/healthz")
    def healthz():
        """
        Lazy-import nija_client to avoid import-time side effects in Gunicorn workers.
        Returns basic status - does not attempt destructive actions.
        """
        try:
            import nija_client as nc  # lazy import
            client_present = bool(getattr(nc, "coinbase_client", None))
            test_fn = getattr(nc, "test_coinbase_connection", None)
            test_ok = False
            if callable(test_fn):
                try:
                    test_ok = bool(test_fn())
                except Exception as e:
                    test_ok = False
            return jsonify({
                "status": "ok",
                "coinbase_client_present": client_present,
                "coinbase_test_ok": test_ok,
                "simulation_mode": getattr(nc, "simulation_mode", True),
            }), 200
        except Exception as e:
            # If import fails, return 200 but include diagnostic info
            return jsonify({
                "status": "ok",
                "coinbase_client_present": False,
                "coinbase_test_ok": False,
                "error": str(e)
            }), 200

    return app

# expose to gunicorn
app = create_app()
