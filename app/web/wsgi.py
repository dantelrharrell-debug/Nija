"""
web/wsgi.py - simple Flask app with lazy nija_client usage.
Expose `app` to gunicorn:  web.wsgi:app
"""
from flask import Flask, jsonify

def create_app():
    app = Flask(__name__)

    @app.route("/")
    def index():
        return "Nija App — healthy"

    @app.route("/healthz")
    def healthz():
        # Lazy import so gunicorn workers start quickly and don't evaluate nija_client top-level side-effects
        try:
            import nija_client as nc
            client_present = bool(getattr(nc, "coinbase_client", None))
            simulation = bool(getattr(nc, "simulation_mode", True))

            # prefer the well-known test function if available
            test_fn = getattr(nc, "test_coinbase_connection", None) or getattr(nc, "test_coinbase_client", None)

            test_ok = None
            if callable(test_fn):
                try:
                    test_ok = bool(test_fn())
                except Exception as e:
                    test_ok = False

            return jsonify({
                "status": "ok",
                "coinbase_client_present": client_present,
                "coinbase_test_ok": test_ok,
                "simulation_mode": simulation,
            }), 200
        except Exception as e:
            # Return status = ok but include diagnostic detail; avoids worker crash on import-time errors
            return jsonify({
                "status": "ok",
                "coinbase_client_present": False,
                "coinbase_test_ok": False,
                "error": str(e)
            }), 200

    return app

app = create_app()
