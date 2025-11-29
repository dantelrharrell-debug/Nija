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
        """
        Lazy diagnostic endpoint. Attempts to import the nija_client module
        from the `app` package (app/nija_client). This avoids import-time
        side effects during gunicorn worker startup.
        """
        try:
            # Try the package path that matches your repo layout first
            try:
                nc = importlib.import_module("app.nija_client")
            except Exception:
                # Fallback if layout differs
                nc = importlib.import_module("nija_client")

            client_present = bool(getattr(nc, "coinbase_client", None))
            simulation = bool(getattr(nc, "simulation_mode", True))

            test_fn = getattr(nc, "test_coinbase_connection", None) or getattr(nc, "test_coinbase_client", None)

            test_ok = None
            if callable(test_fn):
                try:
                    test_ok = bool(test_fn())
                except Exception:
                    test_ok = False

            return jsonify({
                "status": "ok",
                "coinbase_client_present": client_present,
                "coinbase_test_ok": test_ok,
                "simulation_mode": simulation,
            }), 200

        except Exception as e:
            # Return diagnostics but do not crash worker on import-time errors
            err = repr(e)
            if len(err) > 1000:
                err = err[:1000] + "..."
            return jsonify({
                "status": "ok",
                "coinbase_client_present": False,
                "coinbase_test_ok": False,
                "error": err
            }), 200

    return app

# Expose the WSGI app for gunicorn: web.wsgi:app
app = create_app()
