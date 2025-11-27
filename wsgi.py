# wsgi.py
"""
Create a guaranteed Flask WSGI app object called `app` for Gunicorn to consume.

This avoids circular imports / non-callable symbols by constructing the app
here and then trying (non-fatally) to import your larger app module and
register blueprints/routes if present.
"""
import logging
from flask import Flask

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")

def create_app():
    app = Flask(__name__)

    # lightweight health endpoint so container is healthy even if other modules fail to import
    @app.route("/")
    def _index():
        return "Nija Bot Running (wsgi root)!"

    # keep a simple debug route available
    @app.route("/health")
    def health():
        return {"status": "ok"}

    # Try to import your richer app module (if present) and register its "app"
    # This is non-fatal — if importing fails we still return the simple app above.
    try:
        # attempt to import your app file (app.py) or package
        import importlib
        mod = importlib.import_module("app")  # your existing file app.py
        # If the app module exposes a function to attach to an app, call it.
        if hasattr(mod, "register_to_app"):
            # optional pattern: app.py can provide register_to_app(app)
            mod.register_to_app(app)
            logging.info("Registered routes via app.register_to_app")
        elif hasattr(mod, "bp"):
            # if app.py exposes a blueprint `bp`, register it.
            app.register_blueprint(getattr(mod, "bp"))
            logging.info("Registered blueprint 'bp' from app module")
        elif hasattr(mod, "app") and getattr(mod, "app") is not None:
            # If app.py itself created a Flask app, try to copy its routes onto ours.
            other = getattr(mod, "app")
            # If other is callable and is a Flask instance, try to import its view functions as blueprint
            try:
                from flask import Blueprint
                bp = Blueprint("imported_app", __name__)
                for rule in other.url_map.iter_rules():
                    # skip internal rules
                    if rule.endpoint == "static":
                        continue
                    # create a proxy that forwards to the function
                    view = other.view_functions[rule.endpoint]
                    # register using original rule - careful: this may duplicate endpoints
                    bp.add_url_rule(str(rule), endpoint=rule.endpoint, view_func=view, methods=list(rule.methods - {"HEAD","OPTIONS"}))
                app.register_blueprint(bp)
                logging.info("Imported routes from existing app object in app.py")
            except Exception as e:
                logging.warning("Couldn't import routes from app.app: %s", e)
        else:
            logging.info("app module imported but no known attach point found (register_to_app, bp, or app).")
    except Exception as e:
        logging.info("Optional import of app module failed (that's okay). Error: %s", e)

    return app

# WSGI callable
app = create_app()

if __name__ == "__main__":
    # quick local run
    app.run(host="0.0.0.0", port=5000)
