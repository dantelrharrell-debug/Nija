# nija_app.py
from flask import Flask, jsonify

def create_app():
    app = Flask(__name__)

    @app.get("/health")
    def health():
        return jsonify({"status": "ok"})

    @app.get("/nija")
    def nija():
        return "Nija Bot Running!"

    @app.get("/debug/coinbase")
    def debug_coinbase():
        out = {"coinbase_import": False, "coinbase_version": None, "pyjwt_version": None}
        try:
            import importlib.metadata as md
        except Exception:
            md = None

        try:
            # this import will succeed if coinbase-advanced-py installed properly
            from coinbase_advanced.client import Client  # type: ignore
            out["coinbase_import"] = True
        except Exception as e:
            out["coinbase_error"] = str(e)

        if md:
            try:
                out["coinbase_version"] = md.version("coinbase-advanced-py")
            except Exception:
                out["coinbase_version"] = None
            try:
                out["pyjwt_version"] = md.version("PyJWT")
            except Exception:
                out["pyjwt_version"] = None

        return jsonify(out)

    return app

# create and export top-level callable expected by Gunicorn
app = create_app()
