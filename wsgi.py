So this is not correct # wsgi.py
from nija_app import app

# Expose "app" for Gunicorn
if __name__ == "__main__":
    app.run()

# wsgi.py
"""
Create a guaranteed Flask WSGI app object called `app` for Gunicorn to consume.
It will try to import app.py (non-fatally) and attach routes if available.
"""
import logging
from flask import Flask

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")

def create_app():
    app = Flask(__name__)

    @app.route("/")
    def _index():
        return "Nija Bot Running (wsgi root)!"

    @app.route("/health")
    def health():
        return {"status": "ok"}

    # Optional: try to import your richer app module and attach safely.
    try:
        import importlib
        mod = importlib.import_module("app")  # your app.py
        if hasattr(mod, "register_to_app"):
            try:
                mod.register_to_app(app)
                logging.info("Registered routes via app.register_to_app")
            except Exception as e:
                logging.warning("register_to_app raised: %s", e)
        if hasattr(mod, "bp"):
            try:
                app.register_blueprint(getattr(mod, "bp"))
                logging.info("Registered blueprint 'bp' from app module")
            except Exception as e:
                logging.warning("registering bp failed: %s", e)
        # If module defines an app object, attempt to import its view functions
        if hasattr(mod, "app") and getattr(mod, "app") is not None:
            other = getattr(mod, "app")
            try:
                from flask import Blueprint
                bp = Blueprint("imported_app", __name__)
                for rule in other.url_map.iter_rules():
                    if rule.endpoint == "static":
                        continue
                    view = other.view_functions[rule.endpoint]
                    methods = list(rule.methods - {"HEAD", "OPTIONS"})
                    # use unique endpoint name to avoid collisions
                    ep = f"imported_{rule.endpoint}"
                    bp.add_url_rule(str(rule), endpoint=ep, view_func=view, methods=methods)
                app.register_blueprint(bp)
                logging.info("Imported routes from app.app")
            except Exception as e:
                logging.warning("Couldn't import routes from app.app: %s", e)
    except Exception as e:
        logging.info("Optional import of app module failed (that's okay). Error: %s", e)

    return app

# WSGI callable
app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
